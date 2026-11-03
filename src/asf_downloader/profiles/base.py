"""Mission profiles: per-mission static description relevant to downloading."""

from __future__ import annotations


class MissionProfile:
    """Static description of a mission's products as exposed by ASF.

    A profile groups every piece of knowledge that is specific to one mission for the purpose
    of downloading, so adding a new mission never requires touching the core code (catalog
    reading, transfer backends, CLI). One module per mission lives in this package and is
    registered in :data:`asf_downloader.profiles.MISSIONS`.

    Args:
        name: CLI identifier (e.g. ``"NISAR"``).
        asf_dataset: value passed to ``asf_search`` searches; centralize it here so naming
            changes at mission launch are fixed in one place only.
        supported_products: list of ``(processing_level, product_type)`` pairs that this tool
            can download for the mission (case-sensitive, e.g. ``("L1", "RSLC")``).
        s3_prefixes: optional mapping ``product_type -> {maturity -> s3 prefix}`` consumed by a
            (future) direct-S3 transfer backend; ``None`` means "no S3 access path".
    """

    def __init__(
        self,
        name: str,
        asf_dataset: str,
        supported_products: list[tuple[str, str]],
        s3_prefixes: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.name = name
        self.asf_dataset = asf_dataset
        self.supported_products = list(supported_products)
        self.s3_prefixes = {
            ptype: dict(maturities) for ptype, maturities in (s3_prefixes or {}).items()
        }


__all__ = ["MissionProfile"]
