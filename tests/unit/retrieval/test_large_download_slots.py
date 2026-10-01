"""Large downloads share two process-wide slots; downloads stay in memory."""

from __future__ import annotations

import tempfile
import threading
import time

import pytest

from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.infra.google_drive import export
from google_drive_mcp.infra.google_drive.export import LARGE_DOWNLOAD_BYTES, fetch_text
from google_drive_mcp.retrieval.grep import drive_grep
from google_drive_mcp.retrieval.read import drive_read

BIG = LARGE_DOWNLOAD_BYTES + 1


@pytest.fixture(autouse=True)
def fresh_slots(monkeypatch):
    monkeypatch.setattr(export, "_large_downloads", threading.BoundedSemaphore(2))


class _BlockingDrive:
    """get_media / export wait until released, and record how many run at once."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.started = threading.Semaphore(0)

    def _download(self) -> bytes:
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        self.started.release()
        try:
            assert self.release.wait(5)
            return b"payload"
        finally:
            with self.lock:
                self.running -= 1

    def get_media(self, file_id: str) -> bytes:
        return self._download()

    def export(self, file_id: str, mime: str) -> str:
        return self._download().decode()


def _fetch(drive, *, size: int | None, mime: str = "text/plain") -> object:
    representation = "text/plain"
    return fetch_text(drive, "f", mime, representation, max_bytes=1_000, size=size)


def _run(target, count: int) -> tuple[list[threading.Thread], list[object]]:
    results: list[object] = []

    def worker() -> None:
        try:
            results.append(target())
        except Exception as exc:
            results.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    return threads, results


def test_at_most_two_large_downloads_run_at_once():
    drive = _BlockingDrive()
    threads, results = _run(lambda: _fetch(drive, size=BIG), 4)
    assert drive.started.acquire(timeout=5) and drive.started.acquire(timeout=5)
    time.sleep(0.2)
    assert drive.running == 2
    drive.release.set()
    for thread in threads:
        thread.join(5)
    assert drive.peak == 2
    assert [r.text for r in results] == ["payload"] * 4


def test_unknown_size_and_workspace_exports_count_as_large():
    drive = _BlockingDrive()
    threads, _ = _run(lambda: _fetch(drive, size=None), 1)
    threads += _run(lambda: _fetch(drive, size=10, mime=DOC_MIME), 2)[0]
    assert drive.started.acquire(timeout=5) and drive.started.acquire(timeout=5)
    time.sleep(0.2)
    assert drive.running == 2
    drive.release.set()
    for thread in threads:
        thread.join(5)
    assert drive.peak == 2


def test_small_known_size_downloads_never_wait_for_a_slot():
    drive = _BlockingDrive()
    threads, _ = _run(lambda: _fetch(drive, size=BIG), 2)
    assert drive.started.acquire(timeout=5) and drive.started.acquire(timeout=5)
    small, _ = _run(lambda: _fetch(drive, size=LARGE_DOWNLOAD_BYTES), 3)
    for _ in range(3):
        assert drive.started.acquire(timeout=5)
    assert drive.running == 5
    drive.release.set()
    for thread in threads + small:
        thread.join(5)


def test_no_free_slot_in_time_is_rate_limited(monkeypatch):
    monkeypatch.setattr(export, "LARGE_DOWNLOAD_WAIT_SECONDS", 0.05)
    drive = _BlockingDrive()
    threads, _ = _run(lambda: _fetch(drive, size=BIG), 2)
    assert drive.started.acquire(timeout=5) and drive.started.acquire(timeout=5)
    with pytest.raises(DomainError) as caught:
        _fetch(drive, size=BIG)
    assert caught.value.error.category == ErrorCategory.RATE_LIMITED
    drive.release.set()
    for thread in threads:
        thread.join(5)
    # The slots come back once the downloads finish.
    assert _fetch(drive, size=BIG).text == "payload"


def _hold_both_slots(monkeypatch) -> None:
    monkeypatch.setattr(export, "LARGE_DOWNLOAD_WAIT_SECONDS", 0.05)
    held = threading.BoundedSemaphore(2)
    held.acquire()
    held.acquire()
    monkeypatch.setattr(export, "_large_downloads", held)


def test_drive_read_without_a_slot_is_rate_limited_error(monkeypatch):
    _hold_both_slots(monkeypatch)
    drive = FakeDrive.sample()
    with pytest.raises(DomainError) as caught:
        drive_read(drive, file_id="nested-doc")
    assert caught.value.error.category == ErrorCategory.RATE_LIMITED
    # A small text file has a known size and does not need a slot.
    assert drive_read(drive, file_id="text-file")["status"] == "COMPLETE"


def test_folder_grep_without_a_slot_is_partial_rate_limited(monkeypatch):
    _hold_both_slots(monkeypatch)
    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="kb", mime_type=FOLDER_MIME))
    drive.add(
        FakeFile(id="small", name="a.txt", mime_type="text/plain", parents=["root"], content="hit")
    )
    drive.add(FakeFile(id="doc", name="Doc", mime_type=DOC_MIME, parents=["root"], content="hit"))
    result = drive_grep(drive, pattern="hit", folder_id="root")
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert [m["file_id"] for m in result["matches"]] == ["small"]
    assert result["next_cursor"] == "small"


def test_download_never_touches_temporary_storage(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("no temp storage")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", refuse)
    monkeypatch.setattr(tempfile, "mkstemp", refuse)
    drive = FakeDrive.sample()
    assert drive_read(drive, file_id="nested-doc")["content"].startswith("alpha idempotency")


def test_download_timeout_is_drive_api_error():
    class _Stalled:
        def get_media(self, file_id: str) -> bytes:
            raise TimeoutError("timed out")

    with pytest.raises(DomainError) as caught:
        _fetch(_Stalled(), size=10)
    assert caught.value.error.category == ErrorCategory.DRIVE_API_ERROR


def test_cap_still_truncates_on_a_character_boundary():
    class _Blob:
        def get_media(self, file_id: str) -> bytes:
            return "漢字".encode() * 10

    result = fetch_text(_Blob(), "f", "text/plain", "text/plain", max_bytes=8, size=60)
    assert result.truncated is True
    assert result.text == "漢字"
    assert result.byte_length == 6
