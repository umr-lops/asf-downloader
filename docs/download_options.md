# asf-downloader — Download options for NISAR RSLC & GSLC from ASF

**Purpose of this note** (2026-11-03): decide the download strategy before implementing.
Use case: **punctual download driven by a listing of products** (the daily Parquet catalogs
produced by the companion repo `metadata-asf`, column `granule_id`). Not a bulk/historical
sweep tool.

Products of interest: **NISAR L1 RSLC** and **L2 GSLC** (single HDF5 `.h5` files, typically
several GB per scene). Two maturity collections coexist in the archive:
**BETA** (Jan–Feb 2026 releases) and **PROVISIONAL** (fully calibrated, acquisitions from
2026-06-17). A search/download tool must be able to address both.

---

## Option A — `asf_search` HTTPS download (official ASF Python client) — RECOMMENDED

Mechanism (from ASF docs, `docs.asf.alaska.edu/asf_search/downloading`):

```python
import asf_search as asf

# 1. batched lookup of the whole listing in ONE API call (best practice,
#    asf_search splits large lists internally — do NOT loop per granule)
results = asf.granule_search(granule_list=[...granule ids from the parquet...])

# 2. authenticated download, N parallel worker processes
results.download(path='/data/nisar', session=session, processes=4)
```

- `session` = `asf_search.ASFSession()` (thread-safe, reusable); `requests`-based.
- `download_urls(urls=..., path=..., session=..., processes=N)` also available for raw URL lists.
- `remotezip()` exists to pull single files out of a zip without downloading the whole
  archive — **not relevant here** (NISAR products are single `.h5` files, not zips).

**Why it fits the punctual-listing use case:**
- Built exactly for "given a list of granules, fetch them": one batched `granule_search`,
  then parallel `download` with a `processes` parameter.
- Official, maintained by ASF; same package `metadata-asf` already depends on
  (consistent ecosystem, one auth setup shared by both repos).
- Works from anywhere over plain HTTPS (our on-prem HPC in France included) — no region
  restriction.
- Easy to wrap with `tenacity` retries, skip-if-exists, and per-file logging to match
  `metadata-asf` conventions.

**Costs:**
- Throughput limited by ASF HTTPS egress + our internet link (much slower than S3),
  but NISAR scenes are only a handful per day per track — fine for punctual downloads.
- Full-file download only (no S3-style multipart), so a interrupted large `.h5` is
  re-downloaded unless we add our own resume logic (`.part` + `Range` header).

## Option B — Direct AWS S3 (Earthdata Cloud bucket)

All NISAR data is hosted in NASA Earthdata Cloud (AWS). ASF issues **temporary AWS
credentials** (1-hour lifetime) from EDL:

- endpoint: `https://nisar.asf.earthdatacloud.nasa.gov/s3credentials` (or
  `earthaccess.login().get_s3_credentials(endpoint=...)`),
- bucket: `sds-n-cumulus-prod-nisar-products`,
- prefixes: `NISAR_L1_RSLC_{BETA|PROVISIONAL}_V1/`, `NISAR_L2_GSLC_{BETA|PROVISIONAL}_V1/`,
  path = `s3://bucket/PREFIX/PRODUCT_NAME_PREFIX/PRODUCT_NAME.h5`,
- then `aws s3 cp` (or boto3) to download.

**Documented hard limitations (deal-breakers for on-prem):**
1. **Access only from within AWS region `us-west-2`.** From outside AWS / other regions you
   get `Access Denied`. → Not usable from our on-prem HPC; only relevant if we ever run
   the tool on EC2/Lambda in us-west-2.
2. Temporary credentials expire after **1 hour** (must be refreshed for long runs).
3. Direct copy from the NISAR bucket to another S3 bucket is **not supported** (download
   locally or process in-cloud only).

**Conclusion:** best raw throughput, but unusable from our HPC. Keep as a *future* backend
option (e.g. an `--access s3` mode) only if/when we process in-cloud.

## Option C — `earthaccess` (generic NASA/CMR client)

- Same EDL auth; CMR-based search + `open()` for HTTPS, plus `get_s3_credentials()`.
- Known NISAR-specific friction: must pass `endpoint=` explicitly (earthaccess issue #1184);
  `daac='ASF'` is wrong for NISAR.
- More generic/less SAR-specific than `asf_search` (no granule-list batched download, no
  SAR metadata conveniences). Nothing it does that Option A can't do better for this case.

## Options out of scope

- **GDAL `vsicurl`** — streams subsets of the HDF5 without full download; a different
  problem (direct-read), not a downloader.
- **Vertex / Earthdata Search web UI** — manual, not scriptable.
- **ISRO Bhoonidhi** — S-band data only; L-band RSLC/GSLC live on ASF.

---

## Credentials (all options)

- One free **Earthdata Login (EDL)** account (https://urs.earthdata.nasa.gov) — no ASF
  account needed.
- **Preferred: `~/.netrc`** (ASF-recommended):

  ```
  machine urs.earthdata.nasa.gov
      login <EDL user>
      password <EDL password or token>
  ```

  `requests` (hence `asf_search`) picks it up automatically; credentials never appear in
  code or logs.
- Alternatives in `asf_search`: `ASFSession().auth_with_creds(user, pass)`,
  `.auth_with_token(EDL token)`, `.auth_with_cookiejar(...)`.
- Option B additionally needs the temporary AWS credentials (auto from EDL, 1 h lifetime).
- For HPC/Airflow deployment: keep the EDL pair in an external secret (same pattern as the
  CDSE config on `/scale`), never in the repo.

## Quotas / limits

| Constraint | Value | Source / note |
|---|---|---|
| S3 temp-credential lifetime | 1 hour | NISAR docs (documented) |
| S3 region | us-west-2 only | NISAR docs (documented) |
| S3 cross-bucket copy | not supported | NISAR docs (documented) |
| CMR search page size | 250 granules/page | `asf_search` docs |
| CMR query rate | batch the granule list, don't loop per granule | `asf_search` best practices |
| ASF HTTPS download quota | **no hard public quota documented**; ASF asks users to be courteous | keep `processes` modest (2–4); monitor for 429s |
| Product size | RSLC/GSLC `.h5` typically several GB each | to be measured in an integration test |
| Checksums | availability/format for NISAR `.h5` to be verified | integration test |

---

## Recommendation

**Option A** — `asf_search` batched `granule_search` + `results.download(processes=N)` with
`.netrc`/`ASFSession` EDL auth. It is the only option that (1) works from our on-prem HPC,
(2) is purpose-built for "download this listing", and (3) reuses the exact same dependency
and auth story as `metadata-asf`. Design the transfer layer behind a small internal
interface so an S3 backend (Option B) can be added later for in-cloud runs without touching
the CLI.

Suggested defaults: `processes=3`, `tenacity` retry (3×, exponential backoff, on
`ConnectionError`/HTTP 429/5xx), skip-existing by size, per-file log lines, non-zero exit
code if any product failed.
