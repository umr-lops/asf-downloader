asf-downloader
==============

Python library and CLI to **download NISAR RSLC/GSLC products from ASF**, driven
by the daily Parquet catalogs produced by the companion repository
`metadata-asf <https://github.com/umr-lops/metadata-asf>`_.

``metadata-asf`` is read-only by design and never transfers product data;
``asf-downloader`` is its counterpart: it reads the ``granule_id`` column of the
daily Parquet catalogs (the interface contract), resolves those products against
the ASF API and downloads them to a local directory.

Scope
-----

- Provider: **ASF**, through ``asf_search``.
- Mission: **NISAR** (first and only target for now).
- Products downloaded: **L1 — RSLC**, **L2 — GSLC** (HDF5, several GB each).
- Listing source: ``metadata-asf`` daily Parquet catalogs.
- Transfer backend: authenticated **HTTPS** today, pluggable interface for a
  future direct-**S3** backend (in-cloud only) — see
  ``docs/download_options.md``.

Installation
------------

.. code-block:: bash

   pip install asf-downloader

For development:

.. code-block:: bash

   git clone https://github.com/umr-lops/asf-downloader.git
   cd asf-downloader
   pip install -e ".[dev,docs]"
   pre-commit install

Python >= 3.10 is required.

Authentication
--------------

A free `Earthdata Login <https://urs.earthdata.nasa.gov>`_ account is required.
The ASF-recommended mechanism is a ``~/.netrc`` entry for
``urs.earthdata.nasa.gov``; alternatively set the ``ASF_EDL_TOKEN`` environment
variable to an EDL token. No credential ever appears in code, config or logs.

CLI usage
---------

The ``asf-downloader`` command has a single subcommand, ``download``:

.. code-block:: bash

    asf-downloader download \
      --catalog /data/nisar_catalog \
      --outputdir /data/nisar \
      --log-verbosity INFO \
      --conf config.yaml

``--catalog`` may be a single daily Parquet file or the directory holding them
(read oldest-first). Products whose file already exists in ``--outputdir`` are
skipped, so an interrupted run can simply be re-executed to completion;
``--overwrite`` forces a re-download.

===============  ========  =====================================================
Option           Required  Description
===============  ========  =====================================================
--catalog         yes      A metadata-asf Parquet catalog, or a directory of such files
--outputdir       yes      Directory the product files are written to
--mission         no       Target mission (default: NISAR)
--backend         no       Transfer backend (default: https)
--processes       no       Parallel download workers (default: 3)
--product-types   no       Only download these product types, e.g. RSLC GSLC
--overwrite       no       Re-download products already present in --outputdir
--log-verbosity   no       DEBUG, INFO, WARNING or ERROR (default INFO)
--conf            no       YAML configuration file (see config.example.yaml)
===============  ========  =====================================================

Precedence is **CLI > ``--conf`` file > defaults**. Exit codes: ``0`` success,
``1`` at least one product failed (or the API raised), ``2`` invalid usage.

Python API
----------

.. code-block:: python

   from pathlib import Path

   from asf_downloader.catalog import read_catalog
   from asf_downloader.transfer import get_backend

   refs = read_catalog(Path("/data/nisar_catalog"))
   with get_backend("https") as backend:
       results = backend.download(
           [r.granule_id for r in refs], Path("/data/nisar"), processes=3
       )

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Contents

   api
   contributing
