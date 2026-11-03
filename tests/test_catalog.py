"""Tests for reading product listings from metadata-asf Parquet catalogs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from asf_downloader.catalog import CatalogError, read_catalog


def _write_catalog(path: Path, granules: list[str], product_types: list[str] | None = None) -> None:
    """Write a minimal ``metadata-asf``-shaped catalog file."""
    data: dict[str, list[str]] = {"granule_id": granules}
    if product_types is not None:
        data["product_type"] = product_types
    pd.DataFrame(data).to_parquet(path, index=False)


def test_read_single_file(tmp_path: Path) -> None:
    """A single catalog file yields its granule ids in order, de-duplicated."""
    path = tmp_path / "NISAR_ocean_20260101.parquet"
    _write_catalog(path, ["A", "B", "A", "C"])
    refs = read_catalog(path)
    assert [r.granule_id for r in refs] == ["A", "B", "C"]
    assert all(r.source_file == path.name for r in refs)


def test_read_directory_oldest_first(tmp_path: Path) -> None:
    """A directory is read in filename order (daily layout ⇒ oldest-first)."""
    _write_catalog(tmp_path / "NISAR_ocean_20260101.parquet", ["A"])
    _write_catalog(tmp_path / "NISAR_ocean_20260102.parquet", ["B", "A"])
    refs = read_catalog(tmp_path)
    assert [r.granule_id for r in refs] == ["A", "B"]  # A from day 1, B from day 2.


def test_read_product_type_filter(tmp_path: Path) -> None:
    """A product-type filter keeps only the wanted types."""
    path = tmp_path / "NISAR_ocean_20260101.parquet"
    _write_catalog(path, ["A", "B", "C"], ["RSLC", "GSLC", "RSLC"])
    refs = read_catalog(path, product_types=["RSLC"])
    assert [r.granule_id for r in refs] == ["A", "C"]


def test_read_filter_missing_product_column(tmp_path: Path) -> None:
    """Filtering by product type on a catalog without the column raises."""
    path = tmp_path / "NISAR_ocean_20260101.parquet"
    _write_catalog(path, ["A"], product_types=None)
    with pytest.raises(CatalogError):
        read_catalog(path, product_types=["RSLC"])


def test_read_missing_granule_column(tmp_path: Path) -> None:
    """A catalog without the granule_id column raises."""
    path = tmp_path / "bad.parquet"
    pd.DataFrame({"other": ["x"]}).to_parquet(path, index=False)
    with pytest.raises(CatalogError):
        read_catalog(path)


def test_read_empty_catalog_raises(tmp_path: Path) -> None:
    """A catalog whose identifiers are all blank/NaN raises."""
    path = tmp_path / "empty.parquet"
    _write_catalog(path, ["", "  "])
    with pytest.raises(CatalogError):
        read_catalog(path)


def test_read_missing_path_raises(tmp_path: Path) -> None:
    """A non-existent catalog path raises."""
    with pytest.raises(CatalogError):
        read_catalog(tmp_path / "nope.parquet")


def test_read_directory_without_parquet_raises(tmp_path: Path) -> None:
    """A directory with no Parquet file raises."""
    (tmp_path / "readme.txt").write_text("hi")
    with pytest.raises(CatalogError):
        read_catalog(tmp_path)


def test_read_non_parquet_file_raises(tmp_path: Path) -> None:
    """A catalog file that is not a Parquet file raises."""
    path = tmp_path / "notes.txt"
    path.write_text("hi")
    with pytest.raises(CatalogError):
        read_catalog(path)
