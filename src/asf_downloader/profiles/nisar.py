"""NISAR mission profile: L1 RSLC + L2 GSLC products."""

from __future__ import annotations

from asf_downloader.profiles.base import MissionProfile

#: S3 prefixes for the NISAR Earthdata Cloud bucket
#: (``sds-n-cumulus-prod-nisar-products``), one per product type and maturity level. These are
#: used only by a (future) direct-S3 transfer backend — see ``docs/download_options.md``.
_NISAR_S3_PREFIXES: dict[str, dict[str, str]] = {
    "RSLC": {
        "BETA": "NISAR_L1_RSLC_BETA_V1/",
        "PROVISIONAL": "NISAR_L1_RSLC_PROVISIONAL_V1/",
    },
    "GSLC": {
        "BETA": "NISAR_L2_GSLC_BETA_V1/",
        "PROVISIONAL": "NISAR_L2_GSLC_PROVISIONAL_V1/",
    },
}


#: NISAR profile: the first (and only) target mission of this project.
nisar_profile = MissionProfile(
    name="NISAR",
    asf_dataset="NISAR",
    supported_products=[("L1", "RSLC"), ("L2", "GSLC")],
    s3_prefixes=_NISAR_S3_PREFIXES,
)


__all__ = ["nisar_profile"]
