"""Configuration: validated run parameters (Pydantic v2)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import PydanticCustomError

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Validated configuration for one ``asf-downloader`` run.

    Field resolution order (highest priority first) is documented in ``AGENTS.md``:
    command-line options > values read from the ``--conf`` YAML file > the model's defaults.
    Every field left unset falls back to its default; :attr:`output_dir` and :attr:`catalog`
    have no sensible default and are always required.
    """

    model_config = {"frozen": True}

    catalog: Path
    """Directory of ``metadata-asf`` daily Parquet files, or a single such file."""

    output_dir: Path
    """Where product files are downloaded; created if missing."""

    mission: str = "NISAR"
    """CLI identifier of the target mission (default ``"NISAR"``)."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    """Root logging level used across the run."""

    processes: int = Field(default=3, ge=1, le=16)
    """Number of parallel download workers (be courteous; see ``docs/download_options.md``)."""

    product_types: list[str] | None = None
    """Optional restriction to a subset of the mission's product types (e.g. ``["RSLC"]``);
    ``None`` downloads every type present in the catalog."""

    skip_existing: bool = True
    """When ``True`` (default), a product whose file already exists in ``output_dir`` is not
    re-downloaded; set ``False`` to force re-download."""


def config_from_yaml(path: Path, **overrides: Any) -> Config:
    """Build a :class:`Config` from a YAML file with keyword overrides on top.

    Args:
        path: YAML file to read; keys mirror the model's own field names, unknown keys fail fast.
        **overrides: explicit non-``None`` values (usually from the CLI) overriding one file
            entry at a time.

    Returns:
        The merged, validated :class:`Config`.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        pydantic.ValidationError: if required fields are missing or inconsistent, if any
            top-level key is unknown, or if the YAML document is not a mapping.
    """
    logger.debug("Building configuration from %s", path)

    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    if not isinstance(document, dict):
        raise ValidationError.from_exception_data(
            title=f"Config input ({path.name})",
            line_errors=[
                {
                    "type": PydanticCustomError(
                        "config_input_not_mapping",
                        "Top-level YAML document must be a mapping, got {document_type}",
                        {"document_type": type(document).__name__},
                    ),
                    "input": document,
                }
            ],
        )

    unknown_keys = set(document) - set(Config.model_fields)
    if unknown_keys:
        raise ValidationError.from_exception_data(
            title=f"Config input ({path.name})",
            line_errors=[
                {
                    "type": PydanticCustomError(
                        "config_input_unknown_key",
                        "Unrecognized top-level key(s) in {path}: {keys}; expected exactly one of: "
                        "{expected}",
                        {
                            "path": path.name,
                            "keys": ", ".join(sorted(unknown_keys)),
                            "expected": ", ".join(Config.model_fields),
                        },
                    ),
                    "input": document,
                }
            ],
        )

    merged_document = dict(document)
    valid_keys = set(Config.model_fields)
    # CLI wins over the file, but only genuine (non-None) explicit values override.
    for name, value in overrides.items():
        if name in valid_keys and value is not None:
            merged_document[name] = value

    return Config(**merged_document)


__all__ = ["Config", "config_from_yaml"]
