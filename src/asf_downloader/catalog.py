"""Reading product listings from ``metadata-asf`` daily Parquet catalogs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

#: ``metadata-asf`` writes daily catalogs named ``{mission}_ocean_YYYYMMDD.parquet`` and the
#: product identifier lives in the ``granule_id`` column (contract: metadata-asf README/AGENTS.md).
_CATALOG_SUFFIX = ".parquet"
_GRANULE_COLUMN = "granule_id"
_PRODUCT_TYPE_COLUMN = "product_type"


class CatalogError(ValueError):
    """Raised when the catalog cannot be read or contains no usable product listing."""


@dataclass(frozen=True)
class ProductRef:
    """One product to download, as listed in a catalog row.

    Attributes:
        granule_id: ASF granule/scene name (the ``metadata-asf`` contract key).
        source_file: name of the catalog Parquet file the row came from (diagnostics only).
    """

    granule_id: str
    source_file: str


def read_catalog(path: Path, *, product_types: list[str] | None = None) -> list[ProductRef]:
    """Read the ``granule_id`` listing from a catalog file or a directory of catalogs.

    Args:
        path: a single ``.parquet`` file, or a directory whose ``*.parquet`` files are read in
            name order (the daily ``{mission}_ocean_YYYYMMDD.parquet`` layout is then read
            oldest-first).
        product_types: optional restriction to a subset of the catalog's ``product_type`` values
            (e.g. ``["RSLC"]``); when given, every catalog must carry a ``product_type`` column.

    Returns:
        The product references in catalog order, de-duplicated (first occurrence wins) with all
        blank/``NaN`` identifiers dropped.

    Raises:
        CatalogError: if ``path`` is missing, no Parquet file can be found, a catalog lacks the
            ``granule_id`` column (or the ``product_type`` column when filtering), or none of the
            catalog(s) yields a non-empty identifier.
    """
    files = _catalog_files(path)

    refs: list[ProductRef] = []
    seen: set[str] = set()
    for file in files:
        for granule_id, _ptype in _read_rows(file, product_types):
            if granule_id not in seen:
                seen.add(granule_id)
                refs.append(ProductRef(granule_id=granule_id, source_file=file.name))

    if not refs:
        raise CatalogError(
            f"No downloadable product found in catalog {path}: every file was empty, or had no "
            f"non-empty '{_GRANULE_COLUMN}' value matching the requested product types."
        )
    logger.info("Catalog %s: %d unique product(s) across %d file(s)", path, len(refs), len(files))
    return refs


def _catalog_files(path: Path) -> list[Path]:
    """Resolve ``path`` to an ordered list of Parquet catalog files.

    Raises:
        CatalogError: if the path does not exist, or a directory holds no ``*.parquet`` file.
    """
    if not path.exists():
        raise CatalogError(f"Catalog path not found: {path}")
    if path.is_file():
        if not path.name.endswith(_CATALOG_SUFFIX):
            raise CatalogError(f"Catalog file is not a Parquet file: {path}")
        return [path]
    files = sorted(p for p in path.glob(f"*{_CATALOG_SUFFIX}") if p.is_file())
    if not files:
        raise CatalogError(f"No '*{_CATALOG_SUFFIX}' file found in catalog directory: {path}")
    return files


def _read_rows(
    file: Path,
    product_types: list[str] | None,
) -> list[tuple[str, str | None]]:
    """Return ``(granule_id, product_type)`` rows of one catalog file, in file order.

    Blank/``NaN`` identifiers are dropped; when ``product_types`` is given, only rows whose
    ``product_type`` is in the list are kept.

    Raises:
        CatalogError: if the file has no ``granule_id`` column, or no ``product_type`` column
            while a product-type filter was requested.
    """
    columns = [_GRANULE_COLUMN]
    if product_types is not None:
        columns.append(_PRODUCT_TYPE_COLUMN)

    try:
        frame = pd.read_parquet(file, columns=columns)
    except FileNotFoundError as exc:
        raise CatalogError(f"Cannot read catalog file {file}") from exc
    except Exception as exc:  # pyarrow/pandas errors share no common public base class.
        raise CatalogError(f"Cannot read catalog file {file}: {exc}") from exc

    if _GRANULE_COLUMN not in frame.columns:
        raise CatalogError(f"Catalog file {file.name} has no '{_GRANULE_COLUMN}' column.")
    if product_types is not None and _PRODUCT_TYPE_COLUMN not in frame.columns:
        raise CatalogError(
            f"Cannot filter by product type: catalog file {file.name} has no "
            f"'{_PRODUCT_TYPE_COLUMN}' column."
        )

    wanted = set(product_types) if product_types is not None else None
    rows: list[tuple[str, str | None]] = []
    for granule_raw, *ptype_raw in frame.itertuples(index=False, name=None):
        granule_id = str(granule_raw).strip()
        if not granule_id or not pd.notna(granule_raw):
            continue
        product_type = str(ptype_raw[0]).strip() if ptype_raw else None
        if wanted is not None and product_type not in wanted:
            continue
        rows.append((granule_id, product_type))
    return rows


__all__ = ["CatalogError", "ProductRef", "read_catalog"]
