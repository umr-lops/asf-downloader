"""Tests for the nisar-archive feature (name parsing, listing, archiving, CLI)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from asf_downloader.nisar_archive import (
    ArchiveConfig,
    NisarNameError,
    archive_config_from_yaml,
    archive_spool,
    main,
    parse_nisar_name,
    read_listing,
)

RSLC_NAME = (
    "NISAR_L1_PR_RSLC_025_148_A_013_4005_DHDH_A_" "20260718T105152_20260718T105222_P05023_N_F_J_001"
)
GSLC_NAME = (
    "NISAR_L2_PR_GSLC_028_148_D_078_2005_SHSH_M_" "20260823T112852_20260823T112927_P05023_N_F_J_001"
)
MODE_7700_NAME = (
    "NISAR_L1_PR_RSLC_032_038_A_010_7700_SHNA_A_" "20261002T194308_20261002T194327_P05023_N_P_J_001"
)


class TestParseNisarName:
    def test_rslc_fields(self) -> None:
        parsed = parse_nisar_name(RSLC_NAME)
        assert parsed.name == RSLC_NAME
        assert parsed.product_type == "RSLC"
        assert parsed.mode == "4005"
        assert parsed.start_date == date(2026, 7, 18)

    def test_gslc_fields(self) -> None:
        parsed = parse_nisar_name(GSLC_NAME)
        assert parsed.product_type == "GSLC"
        assert parsed.mode == "2005"
        assert parsed.start_date == date(2026, 8, 23)

    def test_mode_7700(self) -> None:
        assert parse_nisar_name(MODE_7700_NAME).mode == "7700"

    def test_extension_is_stripped(self) -> None:
        parsed = parse_nisar_name(f"{RSLC_NAME}.h5")
        assert parsed.name == RSLC_NAME

    @pytest.mark.parametrize(
        "bad_name",
        [
            "not-a-nisar-name",
            "SENTINEL1_IW_20260101",
            RSLC_NAME[:20],  # too few fields
            f"{RSLC_NAME}_EXTRA",  # too many fields
            RSLC_NAME.replace("_4005_", "_ABCD_"),  # non-numeric mode
            RSLC_NAME.replace("_4005_", "_405_"),  # 3-digit mode
            RSLC_NAME.replace("20260718T105152", "20260718"),  # bad start time
            RSLC_NAME.replace("20260718T105152", "20261399T105152"),  # impossible date
        ],
    )
    def test_invalid_names_raise(self, bad_name: str) -> None:
        with pytest.raises(NisarNameError):
            parse_nisar_name(bad_name)


class TestReadListing:
    def test_reads_scenes_and_strips_extension(self, tmp_path: Path) -> None:
        listing = tmp_path / "listing.txt"
        listing.write_text(f"{RSLC_NAME}.h5\n\n{GSLC_NAME}\n# comment\n", encoding="utf-8")
        assert read_listing(listing) == [RSLC_NAME, GSLC_NAME]

    def test_deduplicates_and_keeps_order(self, tmp_path: Path) -> None:
        listing = tmp_path / "listing.txt"
        listing.write_text(f"{RSLC_NAME}\n{RSLC_NAME}.h5\n{GSLC_NAME}\n", encoding="utf-8")
        assert read_listing(listing) == [RSLC_NAME, GSLC_NAME]

    def test_skips_non_nisar_lines(self, tmp_path: Path) -> None:
        listing = tmp_path / "listing.csv"
        listing.write_text(f"granule_id\n{RSLC_NAME}\n", encoding="utf-8")
        assert read_listing(listing) == [RSLC_NAME]

    def test_empty_listing(self, tmp_path: Path) -> None:
        listing = tmp_path / "listing.txt"
        listing.write_text("\n# nothing\n", encoding="utf-8")
        assert read_listing(listing) == []


class TestArchiveConfig:
    def test_from_yaml(self, tmp_path: Path) -> None:
        config_path = tmp_path / "archive.yaml"
        config_path.write_text(
            f"spool: {tmp_path / 'spool'}\narchive_dir: {tmp_path / 'archive'}\n", encoding="utf-8"
        )
        config = archive_config_from_yaml(config_path)
        assert config.spool == tmp_path / "spool"
        assert config.archive_dir == tmp_path / "archive"
        assert config.log_level == "INFO"

    def test_cli_override_wins(self, tmp_path: Path) -> None:
        config_path = tmp_path / "archive.yaml"
        config_path.write_text(
            f"spool: {tmp_path / 'spool'}\narchive_dir: {tmp_path / 'archive'}\nlog_level: DEBUG\n",
            encoding="utf-8",
        )
        config = archive_config_from_yaml(config_path, log_level="ERROR")
        assert config.log_level == "ERROR"

    def test_unknown_key_warns(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """An unrecognized top-level key is ignored with a warning (shared config file)."""
        config_path = tmp_path / "archive.yaml"
        config_path.write_text(
            f"spool: {tmp_path / 'spool'}\n"
            f"archive_dir: {tmp_path / 'archive'}\n"
            "catalog: /data/cat\n",
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING):
            config = archive_config_from_yaml(config_path)
        assert config.spool == tmp_path / "spool"
        assert config.archive_dir == tmp_path / "archive"
        assert "catalog" in caplog.text

    def test_missing_required_key_rejected(self, tmp_path: Path) -> None:
        config_path = tmp_path / "archive.yaml"
        config_path.write_text(f"spool: {tmp_path / 'spool'}\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            archive_config_from_yaml(config_path)


def _write_config(tmp_path: Path, spool: Path, archive: Path) -> Path:
    config_path = tmp_path / "archive.yaml"
    config_path.write_text(f"spool: {spool}\narchive_dir: {archive}\n", encoding="utf-8")
    return config_path


class TestArchiveSpool:
    def test_moves_listed_products_into_tree(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")
        (spool / f"{GSLC_NAME}.h5").write_bytes(b"gslc-data")

        summary = archive_spool(spool, archive, [RSLC_NAME, GSLC_NAME])

        assert summary.archived == [RSLC_NAME, GSLC_NAME]
        assert summary.skipped == []
        assert summary.quarantined == {}
        assert summary.missing == []
        assert (
            archive / "RSLC" / "4005" / "2026" / "07" / "18" / f"{RSLC_NAME}.h5"
        ).read_bytes() == b"rslc-data"
        assert (
            archive / "GSLC" / "2005" / "2026" / "08" / "23" / f"{GSLC_NAME}.h5"
        ).read_bytes() == b"gslc-data"
        assert list(spool.iterdir()) == []

    def test_unlisted_nisar_product_is_quarantined(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")
        (spool / f"{GSLC_NAME}.h5").write_bytes(b"gslc-data")

        summary = archive_spool(spool, archive, [RSLC_NAME])

        assert summary.archived == [RSLC_NAME]
        assert summary.quarantined == {f"{GSLC_NAME}.h5": "not present in the input listing"}
        assert (archive / "quarantine" / f"{GSLC_NAME}.h5").exists()

    def test_unreadable_nisar_name_is_quarantined(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        bad_name = f"{RSLC_NAME}_EXTRA"
        (spool / f"{bad_name}.h5").write_bytes(b"bad")
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")

        summary = archive_spool(spool, archive, [RSLC_NAME])

        assert summary.archived == [RSLC_NAME]
        assert f"{bad_name}.h5" in summary.quarantined
        assert (archive / "quarantine" / f"{bad_name}.h5").exists()

    def test_non_nisar_files_are_ignored(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / "notes.txt").write_text("hello", encoding="utf-8")
        (spool / "random.h5").write_bytes(b"not nisar")
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")

        summary = archive_spool(spool, archive, [RSLC_NAME])

        assert summary.archived == [RSLC_NAME]
        assert summary.ignored == ["notes.txt", "random.h5"]
        assert (spool / "notes.txt").exists()
        assert (spool / "random.h5").exists()

    def test_listed_product_absent_from_spool_is_missing(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")

        summary = archive_spool(spool, archive, [RSLC_NAME, GSLC_NAME])

        assert summary.archived == [RSLC_NAME]
        assert summary.missing == [GSLC_NAME]
        assert not summary.ok

    def test_rerun_is_a_noop(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")

        first = archive_spool(spool, archive, [RSLC_NAME])
        assert first.archived == [RSLC_NAME]

        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")
        second = archive_spool(spool, archive, [RSLC_NAME])
        assert second.skipped == [RSLC_NAME]
        assert second.archived == []
        assert second.ok

    def test_size_mismatch_is_quarantined(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")
        archive_spool(spool, archive, [RSLC_NAME])

        (spool / f"{RSLC_NAME}.h5").write_bytes(b"DIFFERENT-CONTENT")
        summary = archive_spool(spool, archive, [RSLC_NAME])

        assert summary.quarantined == {f"{RSLC_NAME}.h5": summary.quarantined[f"{RSLC_NAME}.h5"]}
        assert "different size" in summary.quarantined[f"{RSLC_NAME}.h5"]
        assert (
            archive / "RSLC" / "4005" / "2026" / "07" / "18" / f"{RSLC_NAME}.h5"
        ).read_bytes() == b"rslc-data"


class TestArchiveConfigModel:
    def test_fields(self, tmp_path: Path) -> None:
        config = ArchiveConfig(spool=tmp_path / "s", archive_dir=tmp_path / "a")
        assert config.log_level == "INFO"


class TestArchiveCli:
    def _run(self, tmp_path: Path, spool: Path, archive: Path, listing: Path) -> int:
        config_path = _write_config(tmp_path, spool, archive)
        return main(
            [
                "--input-listing",
                str(listing),
                "--config-path",
                str(config_path),
                "--log-level",
                "ERROR",
            ]
        )

    def test_happy_path_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / f"{RSLC_NAME}.h5").write_bytes(b"rslc-data")
        listing = tmp_path / "listing.txt"
        listing.write_text(f"{RSLC_NAME}\n", encoding="utf-8")

        code = self._run(tmp_path, spool, archive, listing)

        assert code == 0
        assert (archive / "RSLC" / "4005" / "2026" / "07" / "18" / f"{RSLC_NAME}.h5").exists()
        assert "Produits archivés    : 1" in capsys.readouterr().out

    def test_missing_product_exits_one(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        listing = tmp_path / "listing.txt"
        listing.write_text(f"{RSLC_NAME}\n", encoding="utf-8")

        assert self._run(tmp_path, spool, archive, listing) == 1

    def test_quarantine_exits_one(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        (spool / f"{GSLC_NAME}.h5").write_bytes(b"gslc-data")
        listing = tmp_path / "listing.txt"
        listing.write_text(f"{RSLC_NAME}\n", encoding="utf-8")

        assert self._run(tmp_path, spool, archive, listing) == 1
        assert (archive / "quarantine" / f"{GSLC_NAME}.h5").exists()

    def test_missing_config_exits_two(self, tmp_path: Path) -> None:
        listing = tmp_path / "listing.txt"
        listing.write_text(f"{RSLC_NAME}\n", encoding="utf-8")
        code = main(
            [
                "--input-listing",
                str(listing),
                "--config-path",
                str(tmp_path / "absent.yaml"),
            ]
        )
        assert code == 2

    def test_empty_listing_exits_two(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        listing = tmp_path / "listing.txt"
        listing.write_text("# empty\n", encoding="utf-8")

        assert self._run(tmp_path, spool, archive, listing) == 2

    def test_missing_listing_exits_two(self, tmp_path: Path) -> None:
        spool = tmp_path / "spool"
        archive = tmp_path / "archive"
        spool.mkdir()
        config_path = _write_config(tmp_path, spool, archive)
        code = main(
            [
                "--input-listing",
                str(tmp_path / "absent.txt"),
                "--config-path",
                str(config_path),
            ]
        )
        assert code == 2

    def test_missing_spool_exits_two(self, tmp_path: Path) -> None:
        spool = tmp_path / "no-such-spool"
        archive = tmp_path / "archive"
        listing = tmp_path / "listing.txt"
        listing.write_text(f"{RSLC_NAME}\n", encoding="utf-8")

        assert self._run(tmp_path, spool, archive, listing) == 2
