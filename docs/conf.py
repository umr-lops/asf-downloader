"""Sphinx configuration for asf-downloader documentation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from asf_downloader import __version__ as version
except ImportError:  # pragma: no cover
    version = "0.0.0"

project = "asf-downloader"
author = "umr-lops"
copyright = "2026, umr-lops"
release = version
version = version.split("+")[0].rsplit(".", 1)[0]

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_title = "asf-downloader"
html_short_title = "asf-downloader"

autodoc_typehints = "description"
autodoc_docstring_signature = False

napoleon_google_docstring = True
napoleon_numpy_docstring = False
