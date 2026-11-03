"""Tests for the transfer backends (HTTPS backend with a stubbed ``asf_search``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import asf_search as asf
import pytest

from asf_downloader.transfer import UnknownBackendError, get_backend
from asf_downloader.transfer.base import TransferResult
from asf_downloader.transfer.https import AsfHttpsBackend


class FakeProduct:
    """Minimal stand-in for ``asf_search.ASFProduct``.

    ``download`` writes a small file named ``fileName`` into the destination so the backend's
    on-disk checks behave like the real client.
    """

    def __init__(self, scene_name: str, file_name: str | None = None, fail: bool = False) -> None:
        self.sceneName = scene_name
        self.fileName = file_name or f"{scene_name}.h5"
        self.fail = fail
        self.calls = 0

    def download(self, path: str, session: Any = None, **kwargs: Any) -> str:
        self.calls += 1
        if self.fail:
            raise ConnectionError("simulated network failure")
        target = Path(path) / self.fileName
        target.write_bytes(b"fake-sar-bytes")
        return str(target)


def _install_fake_search(monkeypatch: pytest.MonkeyPatch, products: list[FakeProduct]) -> None:
    """Point ``asf_search.granule_search`` at a stub returning the given products."""

    def fake_granule_search(granule_list: list[str], session: Any = None, **kw: Any) -> list[Any]:
        wanted = set(granule_list)
        return [p for p in products if p.sceneName in wanted]

    monkeypatch.setattr(asf, "granule_search", fake_granule_search)


def test_get_backend_https() -> None:
    """The ``https`` backend is registered and instantiable."""
    backend = get_backend("https")
    assert isinstance(backend, AsfHttpsBackend)
    assert backend.name == "https"


def test_get_backend_unknown() -> None:
    """An unregistered backend name raises listing the available ones."""
    with pytest.raises(UnknownBackendError) as excinfo:
        get_backend("s3")
    assert "https" in str(excinfo.value)


def test_download_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every listed product is downloaded, results ordered like the input."""
    _install_fake_search(monkeypatch, [FakeProduct("A"), FakeProduct("B")])
    backend = AsfHttpsBackend()
    results = backend.download(["A", "B"], tmp_path, processes=2)
    assert [r.granule_id for r in results] == ["A", "B"]
    assert all(r.status == "downloaded" for r in results)
    assert (tmp_path / "A.h5").exists()
    assert (tmp_path / "B.h5").exists()


def test_download_skips_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A product whose file already exists is skipped, not re-downloaded."""
    (tmp_path / "A.h5").write_bytes(b"already-here")
    prod_b = FakeProduct("B")
    _install_fake_search(monkeypatch, [FakeProduct("A"), prod_b])
    backend = AsfHttpsBackend()
    results = backend.download(["A", "B"], tmp_path, processes=1)
    by_id = {r.granule_id: r for r in results}
    assert by_id["A"].status == "skipped"
    assert by_id["A"].size == len(b"already-here")
    assert by_id["B"].status == "downloaded"
    assert prod_b.calls == 1


def test_download_overwrite_forces_refetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """skip_existing=False re-downloads a product that is already present."""
    (tmp_path / "A.h5").write_bytes(b"stale")
    prod_a = FakeProduct("A")
    _install_fake_search(monkeypatch, [prod_a])
    backend = AsfHttpsBackend()
    results = backend.download(["A"], tmp_path, processes=1, skip_existing=False)
    assert results[0].status == "downloaded"
    assert prod_a.calls == 1


def test_download_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A listed id absent from the ASF catalog is reported as failed/not-found."""
    _install_fake_search(monkeypatch, [FakeProduct("A")])
    backend = AsfHttpsBackend()
    results = backend.download(["A", "GHOST"], tmp_path, processes=1)
    by_id = {r.granule_id: r for r in results}
    assert by_id["A"].status == "downloaded"
    assert by_id["GHOST"].status == "failed"
    assert "not found" in (by_id["GHOST"].error or "")


def test_download_failure_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One failing product does not prevent the others from downloading."""
    _install_fake_search(monkeypatch, [FakeProduct("A"), FakeProduct("B", fail=True)])
    backend = AsfHttpsBackend()
    results = backend.download(["A", "B"], tmp_path, processes=1)
    by_id = {r.granule_id: r for r in results}
    assert by_id["A"].status == "downloaded"
    assert by_id["B"].status == "failed"
    assert by_id["B"].error is not None


def test_result_ok_property() -> None:
    """``ok`` is True for downloaded/skipped and False for failed."""
    assert TransferResult("a", "downloaded").ok
    assert TransferResult("a", "skipped").ok
    assert not TransferResult("a", "failed", error="x").ok


def test_context_manager_closes_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Using the backend as a context manager closes the session on exit."""
    _install_fake_search(monkeypatch, [FakeProduct("A")])
    backend = AsfHttpsBackend()
    with backend:
        backend.download(["A"], tmp_path, processes=1)
        assert backend._session is not None
    assert backend._session is None
