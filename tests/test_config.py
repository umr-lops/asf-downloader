"""Tests for the Pydantic :class:`~asf_downloader.config.Config` model."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from asf_downloader import config


def test_config_defaults() -> None:
    """Only ``catalog`` and ``output_dir`` are required; the rest has documented defaults."""
    cfg = config.Config(catalog=Path("./cat"), output_dir=Path("./out"))
    assert cfg.mission == "NISAR"
    assert cfg.log_level == "INFO"
    assert cfg.processes == 3
    assert cfg.product_types is None
    assert cfg.skip_existing is True


def test_config_process_bounds() -> None:
    """The worker count is bounded to a courteous range [1, 16]."""
    with pytest.raises(ValidationError):
        config.Config(catalog=Path("./c"), output_dir=Path("./o"), processes=0)
    with pytest.raises(ValidationError):
        config.Config(catalog=Path("./c"), output_dir=Path("./o"), processes=17)


def test_config_is_frozen() -> None:
    """A validated run parameter table has no use case after creation."""
    cfg = config.Config(catalog=Path("./c"), output_dir=Path("./o"))
    with pytest.raises(ValidationError):  # frozen model rejects any mutation after validation.
        cfg.mission = "OTHER"


def test_reference_yaml_keys_match_model() -> None:
    """A document mirroring ``config.example.yaml`` parses and matches the model fields."""
    document = r"""
catalog: /data/nisar_catalog
output_dir: /data/nisar
mission: NISAR
log_level: INFO
processes: 3
product_types: ["RSLC", "GSLC"]
skip_existing: true
"""
    data = yaml.safe_load(document)
    assert set(data) == set(config.Config.model_fields)


def test_config_from_yaml_round_trip(tmp_path: Path) -> None:
    """A reference-like document loads into a validated :class:`Config`."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalog: /data/cat\n" "output_dir: /data/nisar\n" "log_level: DEBUG\n" "processes: 5\n",
        encoding="utf-8",
    )
    cfg = config.config_from_yaml(path)
    assert cfg.catalog == Path("/data/cat")
    assert cfg.output_dir == Path("/data/nisar")
    assert cfg.log_level == "DEBUG"
    assert cfg.processes == 5


def test_config_from_yaml_cli_override_wins(tmp_path: Path) -> None:
    """Non-``None`` overrides from the CLI beat the file value at a time."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalog: /from/file\noutput_dir: /from/file\nprocesses: 10\n", encoding="utf-8"
    )
    cfg = config.config_from_yaml(path, output_dir=Path("/from/cli"), processes=None)
    assert cfg.output_dir == Path("/from/cli")
    assert cfg.processes == 10  # None override leaves the file value untouched.


def test_config_from_yaml_missing_file(tmp_path: Path) -> None:
    """A missing file fails with ``FileNotFoundError``."""
    with pytest.raises(FileNotFoundError):
        config.config_from_yaml(tmp_path / "absent.yaml")


def test_config_from_yaml_non_mapping_document(tmp_path: Path) -> None:
    """A top-level YAML scalar/list raises ``ValidationError``."""
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        config.config_from_yaml(path)


def test_config_from_yaml_unknown_key(tmp_path: Path) -> None:
    """An unrecognized top-level key raises ``ValidationError``."""
    path = tmp_path / "bad.yaml"
    path.write_text("output_dir: /data\nnot_a_field: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError) as excinfo:
        config.config_from_yaml(path)
    assert "not_a_field" in str(excinfo.value)


def test_config_from_yaml_missing_required(tmp_path: Path) -> None:
    """A document without ``catalog``/``output_dir`` raises ``ValidationError``."""
    path = tmp_path / "bad.yaml"
    path.write_text("mission: NISAR\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        config.config_from_yaml(path)
