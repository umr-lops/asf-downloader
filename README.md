# asf-downloader

[![CI](https://github.com/umr-lops/asf-downloader/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/umr-lops/asf-downloader/actions/workflows/ci.yml?branch=main)
[![codecov](https://codecov.io/gh/umr-lops/asf-downloader/branch/main/graph/badge.svg)](https://codecov.io/gh/umr-lops/asf-downloader)
[![PyPI](https://img.shields.io/pypi/v/asf-downloader)](https://pypi.org/project/asf-downloader/)
[![PyPI — Python versions](https://img.shields.io/pypi/pyversions/asf-downloader)](https://pypi.org/project/asf-downloader/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Python library and CLI to **download NISAR RSLC/GSLC products from ASF**, driven by the daily
Parquet catalogs produced by the companion repository [`metadata-asf`].

`metadata-asf` is read-only by design and never transfers product data; `asf-downloader` is its
counterpart: it reads the `granule_id` column of the daily Parquet catalogs (the interface
contract), resolves those products against the ASF API and downloads them to a local directory.

[metadata-asf]: https://github.com/umr-lops/metadata-asf

## Scope

- Provider: **ASF** (Alaska Satellite Facility), through `asf_search`.
- Mission: **NISAR** (first and only target for now).
- Products downloaded: **L1 — RSLC**, **L2 — GSLC** (HDF5 files, typically several GB each).
- Listing source: `metadata-asf` daily Parquet catalogs (`{mission}_ocean_YYYYMMDD.parquet`).
- Transfer backend: authenticated **HTTPS** (`asf_search`), selectable through a pluggable
  backend interface so a direct **S3** backend (in-cloud only) can be added later without CLI
  changes — see [`docs/download_options.md`](docs/download_options.md).
- Archiving: `nisar-archive` moves downloaded products from a spool into an
  `<archive>/<PT>/<AM>/<YYYY>/<MM>/<DD>/` tree.

Out of scope: product search/discovery (that is `metadata-asf`), scientific SAR processing, and
in-cloud S3 access (planned, not implemented).

## Installation (development)

```bash
pip install -e ".[dev]"
pre-commit install
```

Python ≥ 3.10 is required. The project uses a `src/` layout with Hatchling as build backend,
version derived from the Git history via `hatch-vcs`, and two entry points: `asf-downloader`
(product download) and `nisar-archive` (spool → archive tree).

## Authentication

Downloading NISAR data requires a free [Earthdata Login](https://urs.earthdata.nasa.gov) account.
The ASF-recommended mechanism is a `~/.netrc` entry, which `requests` (and therefore
`asf_search`) picks up automatically — no credentials ever appear in code, config or logs:

```
machine urs.earthdata.nasa.gov
    login <EDL username>
    password <EDL password or token>
```

Alternatively, set the `ASF_EDL_TOKEN` environment variable to an EDL token and the tool will
authenticate with it instead of `.netrc`. For HPC/Airflow deployments keep the credential in an
external secret (never in this repository).

## Usage

### CLI — `download`

Download every product listed in a `metadata-asf` catalog:

```bash
asf-downloader download \
  --catalog /data/nisar_catalog \
  --outputdir /data/nisar \
  --log-verbosity INFO \
  --conf config.yaml
```

`--catalog` may be a single daily Parquet file or the directory holding them (read
oldest-first). Products whose file already exists in `--outputdir` are skipped, so an
interrupted run can simply be re-executed to completion; `--overwrite` forces a re-download.

| Option            | Required | Description                                                        |
|-------------------|----------|--------------------------------------------------------------------|
| `--catalog`       | yes      | A `metadata-asf` Parquet catalog, or a directory of such files.     |
| `--outputdir`     | yes      | Directory the product files are written to (created if missing).    |
| `--mission`       | no       | Target mission (default: `NISAR`).                                  |
| `--backend`       | no       | Transfer backend (default: `https`; the only one available today).  |
| `--processes`     | no       | Parallel download workers (default: `3`; keep it courteous).        |
| `--product-types` | no       | Only download these product types, e.g. `RSLC GSLC` (default: all). |
| `--overwrite`     | no       | Re-download products already present in `--outputdir`.              |
| `--log-verbosity` | no       | `DEBUG`, `INFO`, `WARNING` or `ERROR` (default: `INFO`).            |
| `--conf`          | no       | YAML configuration file (see `config.example.yaml`).                |

Precedence is **CLI > `--conf` file > defaults**. Exit codes: `0` all products downloaded or
already present, `1` at least one product failed (or the API raised), `2` invalid usage.

### CLI — `nisar-archive`

Move the NISAR products of a *spool* directory (typically `--outputdir` of `download`) into an
archive tree laid out as `<archive>/<PT>/<AM>/<YYYY>/<MM>/<DD>/<product>.h5`:

- `PT` — product type, field 4 of the NISAR file name (`RSLC`, `GSLC`, …);
- `AM` — acquisition mode code, field 9 (e.g. `4005` = 40 MHz band A + 5 MHz band B, `2005`,
  `7700`, `0005`, …);
- `YYYY/MM/DD` — acquisition start date, field 12.

The file name is parsed locally (no ASF API call). Only the products of the `--input-listing`
file (txt/csv, one `.h5` product per line, with or without the extension) are archived; a spool
file whose NISAR name is unreadable, or that is not listed, is moved to `<archive>/quarantine`
instead of being dropped, and non-NISAR files are left untouched. Re-running is a no-op for
products already archived.

```bash
nisar-archive \
  --input-listing /data/to_archive.txt \
  --config-path archive.yaml \
  --log-level INFO
```

`archive.yaml` (see `archive.example.yaml`):

```yaml
spool: /data/nisar            # directory the .h5 products are currently in
archive_dir: /data/nisar_archive
log_level: INFO
```

> **Shared operational config:** one YAML file can drive both commands (e.g. a single
> `config_production_hpc.yaml`). Each command reads only the keys it knows; any key that
> belongs to the other command is ignored with a warning. Required keys of the running
> command must still be present.

| Option            | Required | Description                                                        |
|-------------------|----------|--------------------------------------------------------------------|
| `--input-listing` | yes      | Listing of the products to archive (one `.h5` product per line).   |
| `--config-path`   | yes      | YAML configuration file (`spool`, `archive_dir`, `log_level`).     |
| `--log-level`     | no       | `DEBUG`, `INFO`, `WARNING` or `ERROR` (default: config, else INFO).|

Precedence is **CLI > `--config-path` file > defaults**. Exit codes: `0` every listed product
archived (or already archived), `1` at least one product missing or quarantined, `2` invalid
usage.

### Python API

The public API consumed by downstream tools:

```python
from pathlib import Path

from asf_downloader.catalog import read_catalog
from asf_downloader.nisar_archive import archive_spool, read_listing
from asf_downloader.profiles import get_profile
from asf_downloader.transfer import get_backend

refs = read_catalog(Path("/data/nisar_catalog"))            # metadata-asf contract
with get_backend("https") as backend:                        # pluggable transfer layer
    results = backend.download([r.granule_id for r in refs], Path("/data/nisar"), processes=3)

summary = archive_spool(Path("/data/nisar"), Path("/data/nisar_archive"),
                        read_listing(Path("/data/to_archive.txt")))  # spool → archive tree
```

### Quotas & limits (summary)

No hard public quota on ASF HTTPS downloads, but be courteous: keep `--processes` small
(2–4), batch API calls (done internally), and expect multi-GB files per product. The direct-S3
path (not implemented here) is region-locked to AWS `us-west-2` — see
[`docs/download_options.md`](docs/download_options.md).

## Development

```bash
make install          # editable install + dev dependencies
make test             # pytest with branch coverage (>= 80 % required)
make check-codestyle  # ruff + black --check
make mypy             # mypy --strict on src/ and tests/
```

Integration tests performing real ASF API / network calls opt in explicitly:
`pytest -m integration` (deselected by default).

## License

MIT — see [LICENSE](LICENSE).
