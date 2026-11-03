Contributing
============

Contributions are welcome. Please read ``AGENTS.md`` first — it documents the
project scope, the ``metadata-asf`` / ``asf-downloader`` boundary, the transfer
backend interface and the code conventions (``ruff`` + ``black``, ``mypy
--strict``, ``pytest`` with >= 80 % coverage).

Development
-----------

.. code-block:: bash

   make install          # editable install + dev dependencies
   make test             # pytest with branch coverage
   make check-codestyle  # ruff + black --check
   make mypy             # mypy --strict on src/ and tests/

Integration tests performing real ASF API / network calls are deselected by
default; opt in explicitly with ``pytest -m integration``.

Branching
---------

Create a feature branch off ``main`` (tag it with your name/model, e.g.
``feat/<topic>-<who>``), open a merge/pull request, and keep ``main`` free of
direct pushes.
