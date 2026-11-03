"""Transfer backends: the pluggable layer that actually moves product files to disk.

The CLI and catalog logic depend only on :class:`~asf_downloader.transfer.base.TransferBackend`
and :class:`~asf_downloader.transfer.base.TransferResult`; the concrete backend in use
(``https`` today, direct ``s3`` later — see ``docs/download_options.md``) is selected through
:func:`asf_downloader.transfer.get_backend` and can be swapped without touching the rest of the
codebase.
"""

from __future__ import annotations

import logging

from asf_downloader.transfer.base import TransferBackend, TransferResult
from asf_downloader.transfer.https import AsfHttpsBackend

logger = logging.getLogger(__name__)


class UnknownBackendError(KeyError):
    """Raised when an unregistered transfer backend name is requested."""

    def __init__(self, backend: str, available: list[str]) -> None:
        self.available = available
        super().__init__(f"Unknown backend {backend!r}. Available backends: {', '.join(available)}")


#: Registry of the available transfer backends, by CLI name.
BACKENDS: dict[str, type[TransferBackend]] = {
    "https": AsfHttpsBackend,
}


def get_backend(name: str) -> TransferBackend:
    """Instantiate the transfer backend registered under ``name``.

    Args:
        name: backend identifier (case-sensitive), e.g. ``"https"``.

    Returns:
        A fresh, not-yet-used backend instance.

    Raises:
        UnknownBackendError: if no backend is registered under ``name``; the message lists every
            available backend so it can be relayed verbatim by the CLI.
    """
    try:
        return BACKENDS[name]()
    except KeyError:
        logger.warning("Backend not found: %s", name)
        raise UnknownBackendError(name, sorted(BACKENDS)) from None


__all__ = ["BACKENDS", "TransferBackend", "TransferResult", "UnknownBackendError", "get_backend"]
