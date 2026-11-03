"""Abstract transfer backend and the per-product result type shared by all backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: Outcome of processing one listed product.
TransferStatus = Literal["downloaded", "skipped", "failed"]


@dataclass(frozen=True)
class TransferResult:
    """Outcome of transferring one product.

    Attributes:
        granule_id: the product identifier from the catalog listing.
        status: ``downloaded`` (fetched now), ``skipped`` (already present and not overridden)
            or ``failed`` (error after all retry attempts).
        path: destination file path, when the product is (or is expected to be) on disk.
        size: file size in bytes for a ``downloaded``/``skipped`` result; ``0`` otherwise.
        error: human-readable reason for a ``failed`` result; ``None`` otherwise.
    """

    granule_id: str
    status: TransferStatus
    path: Path | None = None
    size: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether this product reached a healthy end state (downloaded or skipped)."""
        return self.status in ("downloaded", "skipped")


class TransferBackend(ABC):
    """Interface every transfer backend implements.

    A backend turns a *listing* of product identifiers (read from the ``metadata-asf`` catalog
    by the caller) into files on disk, reporting one :class:`TransferResult` per identifier.
    Concrete backends know how to resolve identifiers (URL, S3 key, ...) and how to authenticate
    — the rest of the codebase stays backend-agnostic.
    """

    #: Short CLI identifier of the backend (e.g. ``"https"``).
    name: str = "base"

    @abstractmethod
    def download(
        self,
        granule_ids: list[str],
        destination: Path,
        *,
        processes: int = 3,
        skip_existing: bool = True,
    ) -> list[TransferResult]:
        """Transfer the listed products to ``destination``.

        Args:
            granule_ids: product identifiers, in listing order.
            destination: directory to create the product files in (created if missing).
            processes: number of parallel transfer workers.
            skip_existing: when ``True``, an identifier whose destination file already exists is
                reported as ``skipped`` without any network transfer.

        Returns:
            One :class:`TransferResult` per identifier, in the same order as ``granule_ids``.
        """
        raise NotImplementedError

    def __enter__(self) -> TransferBackend:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Release any session/connection resources. Default: nothing to do."""
        return None


__all__ = ["TransferBackend", "TransferResult", "TransferStatus"]
