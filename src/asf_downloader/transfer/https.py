"""HTTPS transfer backend built on the official ``asf_search`` client.

This is the backend recommended for on-premises use (see ``docs/download_options.md``,
Option A): the listing is resolved in one batched ``granule_search`` call per chunk, then each
product is fetched over authenticated HTTPS with a bounded number of parallel workers.

Authentication follows the ASF-recommended pattern: a ``~/.netrc`` entry for
``urs.earthdata.nasa.gov`` is picked up automatically by ``requests``; alternatively an EDL
token may be provided through the ``ASF_EDL_TOKEN`` environment variable (never in code or in
the configuration file).
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import asf_search as asf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from asf_downloader.transfer.base import TransferBackend, TransferResult

logger = logging.getLogger(__name__)

#: Error classes retried with exponential backoff before giving up on a product.
_RETRYABLE: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    asf.exceptions.ASFSearchError,
)

#: Granule ids per batched ``granule_search`` call (CMR page size; asf_search would split a
#: larger list internally, but explicit chunks keep the API traffic predictable).
_CHUNK_SIZE = 250


def _prop(product: Any, key: str) -> str:
    """Read a metadata field from an ``ASFProduct`` robustly.

    ``asf_search`` products (notably the NISAR ``NISARProduct`` subclass) expose their metadata
    through the ``product.properties`` dict rather than as plain attributes, so the dict is tried
    first and a direct attribute is used as a fallback (keeps the backend tolerant to asf_search
    representation changes and to lightweight test doubles).

    Args:
        product: an ``asf_search.ASFProduct`` (or a test double exposing the same fields).
        key: the field name, e.g. ``"sceneName"`` or ``"fileName"``.

    Returns:
        The field value as a string.

    Raises:
        KeyError: if neither the ``properties`` dict nor a matching attribute carries the field.
    """
    properties = getattr(product, "properties", None)
    if isinstance(properties, dict) and properties.get(key) is not None:
        return str(properties[key])
    value = getattr(product, key, None)
    if value is not None:
        return str(value)
    raise KeyError(f"Product is missing the '{key}' field")


class AsfHttpsBackend(TransferBackend):
    """Download products over authenticated ASF HTTPS (``asf_search``).

    The backend resolves the whole listing against the ASF API in batched calls, then runs the
    actual transfers in a thread pool (the shared ``ASFSession`` is thread-safe by design).
    """

    name = "https"

    def __init__(self) -> None:
        self._session: Any | None = None

    def download(
        self,
        granule_ids: list[str],
        destination: Path,
        *,
        processes: int = 3,
        skip_existing: bool = True,
    ) -> list[TransferResult]:
        """Resolve and download ``granule_ids`` into ``destination`` (see the base class)."""
        destination.mkdir(parents=True, exist_ok=True)
        session = self._get_session()

        products = self._resolve(granule_ids, session)
        logger.info("ASF lookup: %d/%d listed product(s) resolved", len(products), len(granule_ids))

        results: dict[str, TransferResult] = {}
        pending: list[tuple[str, Any, Path]] = []
        for granule_id in granule_ids:
            product = products.get(granule_id)
            if product is None:
                logger.warning("Product not found in the ASF catalog: %s", granule_id)
                results[granule_id] = TransferResult(
                    granule_id=granule_id, status="failed", error="not found in the ASF catalog"
                )
                continue
            target = destination / _prop(product, "fileName")
            if skip_existing and target.exists() and target.stat().st_size > 0:
                results[granule_id] = TransferResult(
                    granule_id=granule_id,
                    status="skipped",
                    path=target,
                    size=target.stat().st_size,
                )
                continue
            pending.append((granule_id, product, target))

        if pending:
            logger.info(
                "Downloading %d product(s) with %d worker(s) → %s",
                len(pending),
                processes,
                destination,
            )
            with ThreadPoolExecutor(max_workers=max(1, processes)) as pool:
                futures = {
                    pool.submit(self._download_one, product, destination): (granule_id, target)
                    for granule_id, product, target in pending
                }
                for future in as_completed(futures):
                    granule_id, target = futures[future]
                    results[granule_id] = future.result()

        return [results[granule_id] for granule_id in granule_ids]

    def _resolve(self, granule_ids: list[str], session: Any) -> dict[str, Any]:
        """Resolve the listing to ``ASFProduct`` objects in batched, retried API calls.

        Returns:
            Mapping ``granule_id -> ASFProduct``; identifiers the catalog does not know are
            simply absent from the mapping.
        """
        products: dict[str, Any] = {}
        for start in range(0, len(granule_ids), _CHUNK_SIZE):
            chunk = granule_ids[start : start + _CHUNK_SIZE]
            found = self._granule_search(chunk, session)
            for product in found:
                products[_prop(product, "sceneName")] = product
        return products

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=60),
        reraise=True,
    )
    def _granule_search(self, granule_ids: list[str], session: Any) -> list[Any]:
        """One batched ``asf_search.granule_search`` call, retried on transient failures.

        The authenticated session is passed through ``ASFSearchOptions`` (``asf_search``'s
        ``granule_search`` does not take a ``session`` keyword directly).
        """
        options = asf.ASFSearchOptions(session=session)
        return list(asf.granule_search(granule_list=list(granule_ids), opts=options))

    def _download_one(self, product: Any, destination: Path) -> TransferResult:
        """Fetch a single product (with retry) and report its outcome."""
        granule_id = _prop(product, "sceneName")
        target = destination / _prop(product, "fileName")
        try:
            self._fetch(product, destination)
            size = target.stat().st_size if target.exists() else 0
            logger.info("Downloaded %s (%d bytes)", granule_id, size)
            return TransferResult(
                granule_id=granule_id, status="downloaded", path=target, size=size
            )
        except Exception as exc:  # noqa: BLE001 - one bad product must not sink the whole run.
            logger.error("Download failed for %s: %s", granule_id, exc)
            return TransferResult(granule_id=granule_id, status="failed", error=str(exc))

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=60),
        reraise=True,
    )
    def _fetch(self, product: Any, destination: Path) -> None:
        """One ``ASFProduct.download`` attempt (the retried unit)."""
        product.download(path=str(destination), session=self._get_session())

    def _get_session(self) -> Any:
        """Lazily build the shared, thread-safe ``ASFSession`` (once per backend instance)."""
        if self._session is None:
            session = asf.ASFSession()
            token = os.environ.get("ASF_EDL_TOKEN")
            if token:
                session.auth_with_token(token)
                logger.debug("ASFSession authenticated with the EDL token from ASF_EDL_TOKEN")
            else:
                logger.debug("Relying on ~/.netrc (machine urs.earthdata.nasa.gov) for EDL auth")
            self._session = session
        return self._session

    def close(self) -> None:
        """Close the underlying HTTP session, if one was created."""
        if self._session is not None:
            self._session.close()
            self._session = None


__all__ = ["AsfHttpsBackend"]
