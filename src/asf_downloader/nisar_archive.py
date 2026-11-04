"""Archive NISAR ``.h5`` products from a spool directory.

Moves the NISAR products of a spool directory (where ``asf-downloader`` drops its downloads)
into an archive tree laid out as ``<archive>/<PT>/<AM>/<YYYY>/<MM>/<DD>/<filename>``:

- ``PT`` — product type, field 4 of the 18-field NISAR file name (e.g. ``RSLC``, ``GSLC``).
- ``AM`` — acquisition mode code, field 9 (e.g. ``4005`` = 40 MHz band A + 5 MHz band B).
- ``YYYY/MM/DD`` — acquisition start date, field 12.

Every move is driven by a *listing* (plain text or CSV, one ``.h5`` product per line, with or
without the ``.h5`` extension): a file is archived only if its scene name appears in the
listing. Files whose ``NISAR_``-prefixed name is unreadable, or whose valid NISAR name is not
in the listing, are moved to ``<archive>/quarantine`` instead of being dropped. Files that are
not NISAR products at all are left untouched. The file name is parsed offline (no ASF API
call), so the tool works fully disconnected; see the JPL D-102255 naming convention for the
field layout.

Console script: ``nisar-archive --input-listing LISTING --config-path CONFIG [--log-level L]``.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticCustomError

from asf_downloader.utils import setup_logging

logger = logging.getLogger(__name__)

#: Number of underscore-separated fields in a NISAR product file name (JPL D-102255).
NISAR_NAME_FIELD_COUNT = 18

#: Field positions (0-based) used by the archive layout.
PRODUCT_TYPE_INDEX = 3
MODE_INDEX = 8
START_TIME_INDEX = 11

_EXTENSION = ".h5"


class NisarNameError(ValueError):
    """Raised when a file name does not follow the NISAR 18-field naming convention.

    Attributes:
        name: the offending name, for logging.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        super().__init__(f"{name}: {reason}")


@dataclass(frozen=True)
class NisarName:
    """Fields of a valid NISAR product file name that drive the archive layout."""

    name: str
    """Scene name (file name without the ``.h5`` extension)."""

    product_type: str
    """Product type, e.g. ``RSLC`` or ``GSLC`` (archive directory level 1)."""

    mode: str
    """Acquisition mode code, 4 digits, e.g. ``4005`` (archive directory level 2)."""

    start_date: date
    """Acquisition start date (archive directory levels 3 to 5)."""


def parse_nisar_name(name: str) -> NisarName:
    """Parse a NISAR product file name into its archivable fields.

    The scene name may be given with or without the trailing ``.h5`` extension.

    Args:
        name: scene name, e.g. ``NISAR_L1_PR_RSLC_025_148_A_013_4005_DHDH_A_
            20260718T105152_20260718T105222_P05023_N_F_J_001``.

    Returns:
        The parsed :class:`NisarName`.

    Raises:
        NisarNameError: if the name is not a valid NISAR product name.
    """
    scene = name[: -len(_EXTENSION)] if name.endswith(_EXTENSION) else name
    fields = scene.split("_")

    if len(fields) != NISAR_NAME_FIELD_COUNT:
        raise NisarNameError(name, f"expected {NISAR_NAME_FIELD_COUNT} fields, got {len(fields)}")
    if fields[0] != "NISAR":
        raise NisarNameError(name, "does not start with NISAR")

    mode = fields[MODE_INDEX]
    if not mode.isdigit() or len(mode) != 4:
        raise NisarNameError(name, f"acquisition mode field {mode!r} is not a 4-digit code")

    start_time = fields[START_TIME_INDEX]
    try:
        parsed_date = datetime.strptime(start_time, "%Y%m%dT%H%M%S").date()
    except ValueError as exc:
        reason = f"start time field {start_time!r} is not YYYYMMDDTHHMMSS"
        raise NisarNameError(name, reason) from exc

    return NisarName(
        name=scene,
        product_type=fields[PRODUCT_TYPE_INDEX],
        mode=mode,
        start_date=parsed_date,
    )


def read_listing(path: Path) -> list[str]:
    """Read a listing of products to archive (plain text or CSV, one per line).

    Blank lines, comment lines (starting with ``#``) and any line that is not a NISAR scene
    name (e.g. a CSV header) are skipped. The ``.h5`` extension is stripped, duplicates are
    removed and the input order is preserved.

    Args:
        path: the listing file.

    Returns:
        The scene names to archive.

    Raises:
        OSError: if the file cannot be read.
    """
    scenes: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        scene = entry[: -len(_EXTENSION)] if entry.endswith(_EXTENSION) else entry
        if not scene.startswith("NISAR_"):
            logger.warning("Skipping non-NISAR listing line: %r", entry)
            continue
        if scene not in seen:
            seen.add(scene)
            scenes.append(scene)
    return scenes


class ArchiveConfig(BaseModel):
    """Validated configuration for one ``nisar-archive`` run.

    Priority (highest first), mirroring ``asf-downloader``: command-line options > values
    from the ``--config-path`` YAML file > the model's defaults.
    """

    model_config = {"frozen": True}

    spool: Path
    """Directory the ``.h5`` products are currently in (moved out of it)."""

    archive_dir: Path
    """Root of the archive tree ``<archive>/<PT>/<AM>/<YYYY>/<MM>/<DD>/``."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    """Root logging level used across the run."""


def archive_config_from_yaml(path: Path, **overrides: Any) -> ArchiveConfig:
    """Build an :class:`ArchiveConfig` from a YAML file with keyword overrides on top.

    Args:
        path: YAML file to read; keys mirror the model's field names, unknown keys fail fast.
        **overrides: explicit non-``None`` values (usually from the CLI).

    Returns:
        The merged, validated :class:`ArchiveConfig`.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        pydantic.ValidationError: if required fields are missing, a key is unknown, or the
            document is not a mapping.
    """
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    if not isinstance(document, dict):
        raise ValidationError.from_exception_data(
            title=f"Archive config input ({path.name})",
            line_errors=[
                {
                    "type": PydanticCustomError(
                        "archive_config_not_mapping",
                        "Top-level YAML document must be a mapping, got {document_type}",
                        {"document_type": type(document).__name__},
                    ),
                    "input": document,
                }
            ],
        )

    unknown_keys = set(document) - set(ArchiveConfig.model_fields)
    if unknown_keys:
        raise ValidationError.from_exception_data(
            title=f"Archive config input ({path.name})",
            line_errors=[
                {
                    "type": PydanticCustomError(
                        "archive_config_unknown_key",
                        "Unrecognized top-level key(s) in {path}: {keys}",
                        {"path": path.name, "keys": ", ".join(sorted(unknown_keys))},
                    ),
                    "input": document,
                }
            ],
        )

    merged = dict(document)
    for name, value in overrides.items():
        if name in ArchiveConfig.model_fields and value is not None:
            merged[name] = value
    return ArchiveConfig(**merged)


@dataclass
class ArchiveSummary:
    """Outcome of one archive run."""

    archived: list[str] = field(default_factory=list)
    """Scene names moved into the archive tree."""

    skipped: list[str] = field(default_factory=list)
    """Scene names already present in the archive with an identical size (no-op re-run)."""

    quarantined: dict[str, str] = field(default_factory=dict)
    """File names moved to the quarantine directory, mapped to the reason."""

    missing: list[str] = field(default_factory=list)
    """Scene names in the listing for which no file was found in the spool."""

    ignored: list[str] = field(default_factory=list)
    """Spool files left untouched (not ``.h5`` or not a NISAR product name)."""

    @property
    def ok(self) -> bool:
        """``True`` when nothing was missing or quarantined."""
        return not self.missing and not self.quarantined


def _archive_destination(parsed: NisarName, archive_dir: Path) -> Path:
    """Compute the archive destination for a parsed product name."""
    return (
        archive_dir
        / parsed.product_type
        / parsed.mode
        / f"{parsed.start_date.year:04d}"
        / f"{parsed.start_date.month:02d}"
        / f"{parsed.start_date.day:02d}"
        / f"{parsed.name}{_EXTENSION}"
    )


def archive_spool(spool: Path, archive_dir: Path, scenes: list[str]) -> ArchiveSummary:
    """Move the listed NISAR ``.h5`` products of a spool into the archive tree.

    Each ``.h5`` file of the spool is archived (moved) only if its scene name is in
    ``scenes``. A ``NISAR_``-prefixed file whose name is unreadable, or whose valid NISAR name
    is not listed, is moved to ``<archive_dir>/quarantine``. Files that are neither ``.h5``
    nor a NISAR product are left untouched. A destination that already exists with an
    identical size is a no-op (idempotent re-run); a size mismatch is quarantined.

    Args:
        spool: directory the products are currently in.
        archive_dir: root of the archive tree (created on demand).
        scenes: scene names to archive (see :func:`read_listing`).

    Returns:
        The :class:`ArchiveSummary` of the run.

    Raises:
        OSError: if the spool is not a readable directory or a move fails.
    """
    summary = ArchiveSummary()
    wanted = set(scenes)
    quarantined_scenes: set[str] = set()

    for file_path in sorted(spool.iterdir()):
        if not file_path.is_file():
            summary.ignored.append(file_path.name)
            continue
        if not file_path.name.endswith(_EXTENSION):
            logger.debug("Ignoring non-%s file in spool: %s", _EXTENSION, file_path.name)
            summary.ignored.append(file_path.name)
            continue

        try:
            parsed = parse_nisar_name(file_path.name)
        except NisarNameError as exc:
            if not file_path.name.startswith("NISAR_"):
                logger.debug("Ignoring non-NISAR file in spool: %s", file_path.name)
                summary.ignored.append(file_path.name)
                continue
            logger.warning("Quarantining unreadable NISAR name: %s", exc)
            _quarantine(file_path, archive_dir, summary, str(exc))
            continue

        if parsed.name not in wanted:
            reason = "not present in the input listing"
            logger.warning("Quarantining unlisted product: %s", file_path.name)
            _quarantine(file_path, archive_dir, summary, reason)
            quarantined_scenes.add(parsed.name)
            continue

        destination = _archive_destination(parsed, archive_dir)
        if destination.exists():
            if destination.stat().st_size == file_path.stat().st_size:
                logger.info("Already archived (skipped): %s", file_path.name)
                summary.skipped.append(parsed.name)
            else:
                reason = f"destination exists with a different size ({destination})"
                logger.warning("Quarantining conflicting product: %s", file_path.name)
                _quarantine(file_path, archive_dir, summary, reason)
                quarantined_scenes.add(parsed.name)
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(file_path), str(destination))
        logger.info("Archived %s → %s", file_path.name, destination)
        summary.archived.append(parsed.name)

    handled = set(summary.archived) | set(summary.skipped) | quarantined_scenes
    summary.missing = [scene for scene in scenes if scene not in handled]
    for scene in summary.missing:
        logger.warning("Listed product not found in spool: %s", scene)

    return summary


def _quarantine(file_path: Path, archive_dir: Path, summary: ArchiveSummary, reason: str) -> None:
    """Move a spool file to ``<archive_dir>/quarantine`` and record why."""
    quarantine_dir = archive_dir / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    target = quarantine_dir / file_path.name
    counter = 1
    while target.exists():  # never overwrite a previous quarantine entry.
        target = quarantine_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
        counter += 1
    shutil.move(str(file_path), str(target))
    summary.quarantined[file_path.name] = reason


def build_parser() -> argparse.ArgumentParser:
    """Build the ``nisar-archive`` argument parser.

    Returns:
        The argument parser with ``--input-listing``, ``--config-path`` and ``--log-level``.
    """
    parser = argparse.ArgumentParser(
        prog="nisar-archive",
        description="Move NISAR .h5 products from a spool directory into a "
        "<archive>/<PT>/<AM>/<YYYY>/<MM>/<DD>/ tree, driven by a product listing.",
    )
    parser.add_argument(
        "--input-listing",
        type=Path,
        required=True,
        help="Listing of the products to archive (txt/csv, one .h5 product per line).",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        required=True,
        help="YAML configuration file (keys: spool, archive_dir, log_level).",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Logging level (default: the config file value, else INFO).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``nisar-archive`` console script.

    Args:
        argv: command-line tokens (defaults to ``sys.argv[1:]``); injected in tests.

    Returns:
        ``0`` when every listed product is archived (or already archived); ``1`` when at
        least one product is missing or quarantined; ``2`` on invalid usage.
    """
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level or "INFO")

    try:
        config = archive_config_from_yaml(args.config_path, log_level=args.log_level)
    except FileNotFoundError:
        logger.error("Configuration file not found: %s", args.config_path)
        return 2
    except ValidationError as exc:
        logger.error("Invalid archive configuration:\n%s", exc)
        return 2
    setup_logging(config.log_level)

    try:
        scenes = read_listing(args.input_listing)
    except OSError as exc:
        logger.error("Cannot read listing %s: %s", args.input_listing, exc)
        return 2
    if not scenes:
        logger.error("Listing %s contains no NISAR product", args.input_listing)
        return 2

    if not config.spool.is_dir():
        logger.error("Spool directory not found: %s", config.spool)
        return 2

    try:
        summary = archive_spool(config.spool, config.archive_dir, scenes)
    except OSError as exc:
        logger.error("Archive run failed: %s", exc)
        return 1

    _log_summary(config, summary)
    return 0 if summary.ok else 1


def _log_summary(config: ArchiveConfig, summary: ArchiveSummary) -> None:
    """Print the final run summary and one line per problem product."""
    print("=== Résumé ===")
    print(f"Spool                : {config.spool}")
    print(f"Archive              : {config.archive_dir}")
    print(f"Produits archivés    : {len(summary.archived)}")
    print(f"Déjà archivés (skip) : {len(summary.skipped)}")
    print(f"En quarantaine       : {len(summary.quarantined)}")
    print(f"Manquants (listés)   : {len(summary.missing)}")
    for file_name, reason in sorted(summary.quarantined.items()):
        print(f"  QUARANTINE  {file_name}: {reason}")
    for scene in summary.missing:
        print(f"  MANQUANT    {scene}")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ArchiveConfig",
    "ArchiveSummary",
    "NisarName",
    "NisarNameError",
    "archive_config_from_yaml",
    "archive_spool",
    "build_parser",
    "main",
    "parse_nisar_name",
    "read_listing",
]
