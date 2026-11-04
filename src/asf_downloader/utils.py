"""Assorted helpers: logging setup and config-file key filtering."""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def warn_unknown_keys(document: dict[str, Any], source: str, known: set[str]) -> None:
    """Log a warning for top-level keys of a config document that are not in ``known``.

    A single operational YAML file may be shared by several commands (e.g. ``download`` and
    ``nisar-archive``); each command only understands its own keys. Unknown keys are therefore
    not an error — they are reported so a typo is visible in the logs, and left in the document
    (the caller builds its model from the known keys only, so they are never passed to it).

    Args:
        document: the parsed top-level mapping of the config file.
        source: human-readable name of the file, for the log message.
        known: the set of field names the consuming model accepts.
    """
    unknown = sorted(set(document) - known)
    if unknown:
        logger.warning(
            "Ignoring key(s) not used by this command in %s: %s", source, ", ".join(unknown)
        )


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
