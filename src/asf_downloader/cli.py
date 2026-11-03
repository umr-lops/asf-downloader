"""Command-line interface for asf-downloader.

A single ``download`` subcommand: read a listing of products from the ``metadata-asf`` daily
Parquet catalogs, resolve them against the ASF API and transfer them to a local directory with
the selected backend (``https`` today; see ``docs/download_options.md`` for the alternatives and
the planned S3 backend).

Exit codes (mirroring ``metadata-asf``): ``0`` success, ``1`` a runtime error (one or more
products failed to download, a catalog/API error), ``2`` invalid usage (bad arguments, unknown
mission or backend, missing catalog).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from asf_downloader import config as config_module
from asf_downloader.catalog import CatalogError, read_catalog
from asf_downloader.profiles import UnknownMissionError, get_profile
from asf_downloader.transfer import BACKENDS, UnknownBackendError, get_backend
from asf_downloader.transfer.base import TransferResult
from asf_downloader.utils import setup_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with the ``download`` subcommand.

    Returns:
        The argument parser. Options that can also come from a ``--conf`` file default to
        ``None`` (not to their documented fallback) so that only the values the user actually
        typed override the file; the documented defaults then come from the file or the model.
    """
    parser = argparse.ArgumentParser(
        prog="asf-downloader",
        description="Download NISAR RSLC/GSLC products from ASF, driven by metadata-asf "
        "Parquet catalogs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser(
        "download",
        help="Download the products listed in a metadata-asf catalog.",
        description="Download the products listed in a metadata-asf Parquet catalog.",
    )
    _add_download_args(download)
    return parser


def _add_download_args(sub: argparse.ArgumentParser) -> None:
    """Register the ``download`` options on a (sub)parser."""
    sub.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="A metadata-asf daily Parquet file, or a directory of such files (the listing to "
        "download).",
    )
    sub.add_argument(
        "--outputdir",
        type=Path,
        required=True,
        help="Directory the product files are downloaded to (created if missing).",
    )
    sub.add_argument("--mission", default=None, help="Target mission (default: NISAR).")
    sub.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        default=None,
        help="Transfer backend to use (default: https).",
    )
    sub.add_argument(
        "--processes",
        type=int,
        default=None,
        help="Number of parallel download workers (default: 3).",
    )
    sub.add_argument(
        "--product-types",
        nargs="+",
        default=None,
        metavar="TYPE",
        help="Only download these product types, e.g. RSLC GSLC (default: all in the catalog).",
    )
    sub.add_argument(
        "--overwrite",
        action="store_true",
        default=None,
        help="Re-download products whose file already exists in --outputdir (default: skip them).",
    )
    _add_log_verbosity(sub)
    sub.add_argument("--conf", type=Path, default=None, help="YAML configuration file.")


def _add_log_verbosity(sub: argparse.ArgumentParser) -> None:
    """Register the shared ``--log-verbosity`` flag on a (sub)parser."""
    sub.add_argument(
        "--log-verbosity",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Logging verbosity (default: INFO).",
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``asf-downloader`` console script.

    Args:
        argv: command-line tokens (defaults to ``sys.argv[1:]``); injected in tests.

    Returns:
        ``0`` on success, ``1`` on a runtime error, ``2`` on invalid usage.
    """
    args = build_parser().parse_args(argv)
    if args.command == "download":
        return run_download(args)
    logger.error("Unknown command: %s", args.command)
    return 2


def run_download(args: argparse.Namespace) -> int:
    """Read the catalog listing and download the products with the selected backend.

    Args:
        args: the parsed ``download`` subcommand namespace.

    Returns:
        ``0`` when every listed product is downloaded or already present; ``1`` when at least
        one product failed, or the catalog / ASF API raised; ``2`` for invalid usage (unknown
        mission or backend, unreadable/empty catalog, bad config).
    """
    setup_logging(args.log_verbosity or "INFO")

    try:
        config = _build_config(args)
    except FileNotFoundError:
        logger.error("Configuration file not found: %s", args.conf)
        return 2
    except ValidationError as exc:
        logger.error("Invalid configuration:\n%s", exc)
        return 2
    setup_logging(config.log_level)

    try:
        get_profile(config.mission)
    except UnknownMissionError as exc:
        logger.error("%s", exc)
        return 2

    backend_name = args.backend or "https"
    try:
        backend = get_backend(backend_name)
    except UnknownBackendError as exc:
        logger.error("%s", exc)
        return 2

    try:
        refs = read_catalog(config.catalog, product_types=config.product_types)
    except CatalogError as exc:
        logger.error("%s", exc)
        return 2

    try:
        config.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Cannot create output directory %s: %s", config.output_dir, exc)
        return 1

    granule_ids = [ref.granule_id for ref in refs]
    logger.info(
        "Downloading %d product(s) for %s via '%s' → %s",
        len(granule_ids),
        config.mission,
        backend.name,
        config.output_dir,
    )

    try:
        with backend:
            results = backend.download(
                granule_ids,
                config.output_dir,
                processes=config.processes,
                skip_existing=not (args.overwrite or False),
            )
    except Exception as exc:  # noqa: BLE001 - a backend/API failure is a runtime error.
        logger.error("Download run failed: %s", exc)
        return 1

    _log_summary(config, results)
    if any(not r.ok for r in results):
        return 1
    return 0


def _build_config(args: argparse.Namespace) -> config_module.Config:
    """Merge the CLI values with an optional ``--conf`` file into a validated Config.

    Only the CLI values the user actually supplied override the file; the rest falls back to
    the file, then to the model defaults (AGENTS.md). ``--overwrite`` maps to
    ``skip_existing=False``.
    """
    overrides: dict[str, Any] = {
        "catalog": args.catalog,
        "output_dir": args.outputdir,
        "mission": args.mission,
        "log_level": args.log_verbosity,
        "processes": args.processes,
        "product_types": args.product_types,
        "skip_existing": False if (args.overwrite or False) else None,
    }
    if args.conf is not None:
        return config_module.config_from_yaml(args.conf, **overrides)
    return config_module.Config(**{k: v for k, v in overrides.items() if v is not None})


def _log_summary(config: config_module.Config, results: list[TransferResult]) -> None:
    """Print the final run summary and one line per failed product."""
    downloaded = [r for r in results if r.status == "downloaded"]
    skipped = [r for r in results if r.status == "skipped"]
    failed = [r for r in results if r.status == "failed"]
    total_bytes = sum(r.size for r in downloaded + skipped)

    print("=== Résumé ===")
    print(f"Mission                : {config.mission}")
    print(f"Products listés        : {len(results)}")
    print(f"  téléchargés          : {len(downloaded)}")
    print(f"  déjà présents (skip) : {len(skipped)}")
    print(f"  en échec             : {len(failed)}")
    print(f"Volume (tél.+skip)     : {total_bytes / (1024**2):.1f} Mo")
    print(f"Dossier de sortie      : {config.output_dir}")
    for result in failed:
        print(f"  ÉCHEC  {result.granule_id}: {result.error}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main", "run_download"]
