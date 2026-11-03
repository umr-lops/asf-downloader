"""End-to-end CLI tests (download subcommand, stubbed ``asf_search``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import asf_search as asf
import pandas as pd
import pytest

from asf_downloader.cli import main
from tests.test_transfer import FakeProduct


def _write_catalog(dir_path: Path, granules: list[str]) -> Path:
    path = dir_path / "NISAR_ocean_20260101.parquet"
    pd.DataFrame({"granule_id": granules}).to_parquet(path, index=False)
    return path


def _install_fake_search(monkeypatch: pytest.MonkeyPatch, products: list[FakeProduct]) -> None:
    def fake_granule_search(granule_list: list[str], session: Any = None, **kw: Any) -> list[Any]:
        wanted = set(granule_list)
        return [p for p in products if p.sceneName in wanted]

    monkeypatch.setattr(asf, "granule_search", fake_granule_search)


def test_download_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI reads the catalog, downloads everything and exits 0."""
    catalog_dir = tmp_path / "cat"
    catalog_dir.mkdir()
    _write_catalog(catalog_dir, ["A", "B"])
    out = tmp_path / "out"
    _install_fake_search(monkeypatch, [FakeProduct("A"), FakeProduct("B")])

    code = main(
        [
            "download",
            "--catalog",
            str(catalog_dir),
            "--outputdir",
            str(out),
            "--log-verbosity",
            "ERROR",
        ],
    )
    assert code == 0
    assert (out / "A.h5").exists()
    assert (out / "B.h5").exists()


def test_download_rerun_skips_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second run skips already-downloaded products and still exits 0."""
    catalog_dir = tmp_path / "cat"
    catalog_dir.mkdir()
    _write_catalog(catalog_dir, ["A"])
    out = tmp_path / "out"
    prod_a = FakeProduct("A")
    _install_fake_search(monkeypatch, [prod_a])

    assert (
        main(
            [
                "download",
                "--catalog",
                str(catalog_dir),
                "--outputdir",
                str(out),
                "--log-verbosity",
                "ERROR",
            ]
        )
        == 0
    )
    prod_a.calls = 0
    assert (
        main(
            [
                "download",
                "--catalog",
                str(catalog_dir),
                "--outputdir",
                str(out),
                "--log-verbosity",
                "ERROR",
            ]
        )
        == 0
    )
    assert prod_a.calls == 0  # skipped on the second run: no network call.


def test_download_partial_failure_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A product missing from the ASF catalog makes the run exit 1."""
    catalog_dir = tmp_path / "cat"
    catalog_dir.mkdir()
    _write_catalog(catalog_dir, ["A", "GHOST"])
    out = tmp_path / "out"
    _install_fake_search(monkeypatch, [FakeProduct("A")])

    code = main(
        [
            "download",
            "--catalog",
            str(catalog_dir),
            "--outputdir",
            str(out),
            "--log-verbosity",
            "ERROR",
        ]
    )
    assert code == 1
    assert (out / "A.h5").exists()


def test_download_unknown_mission_exits_two(tmp_path: Path) -> None:
    """An unknown mission is a usage error (exit 2)."""
    code = main(
        [
            "download",
            "--catalog",
            str(tmp_path),
            "--outputdir",
            str(tmp_path / "o"),
            "--mission",
            "SENTINEL-2",
            "--log-verbosity",
            "ERROR",
        ],
    )
    assert code == 2


def test_download_missing_catalog_exits_two(tmp_path: Path) -> None:
    """A missing catalog path is a usage error (exit 2)."""
    code = main(
        [
            "download",
            "--catalog",
            str(tmp_path / "absent"),
            "--outputdir",
            str(tmp_path / "o"),
            "--log-verbosity",
            "ERROR",
        ],
    )
    assert code == 2


def test_download_conf_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Values can come from a --conf YAML file; the CLI still supplies what the file omits."""
    catalog_dir = tmp_path / "cat"
    catalog_dir.mkdir()
    _write_catalog(catalog_dir, ["A"])
    out = tmp_path / "out"
    conf = tmp_path / "conf.yaml"
    conf.write_text("processes: 2\n", encoding="utf-8")
    _install_fake_search(monkeypatch, [FakeProduct("A")])

    code = main(
        [
            "download",
            "--catalog",
            str(catalog_dir),
            "--outputdir",
            str(out),
            "--conf",
            str(conf),
            "--log-verbosity",
            "ERROR",
        ],
    )
    assert code == 0
    assert (out / "A.h5").exists()
