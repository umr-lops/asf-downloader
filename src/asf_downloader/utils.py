"""Assorted helpers: logging setup."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str) -> None:
    """Configure root logging for an asf-downloader run.

    Applies the format fixed in ``AGENTS.md`` (``%(asctime)s | %(levelname)-8s |
    %(name)s | %(message)s``), writes to stdout and sets the given level. Calling it twice is
    safe — existing handlers are removed first, never stacked on top of each other.

    Args:
        level: one of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR`` — validated by the config
            layer above; an unknown value simply falls back to INFO instead of aborting.
    """
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(log_format))
    root.addHandler(stream_handler)

    name = str(level).strip().upper()
    candidate: object = getattr(logging, name, None)  # fallback is purely defensive.
    root.setLevel(candidate if isinstance(candidate, int) else logging.INFO)


__all__ = ["setup_logging"]
