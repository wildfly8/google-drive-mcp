"""A call asks Drive about each named file once, and about all of them at the same time.

The access check and the tool both need a named file's metadata. A per-call memo answers
the second ask, and the check looks the ids up side by side. Both used to cost one Drive
round trip (about 0.2 s) per id and per ask, one after another.
"""

from __future__ import annotations

import threading
import time

import pytest

from fakes.fake_drive import FakeDrive, FakeFile
from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.infra.google_drive.memo import MemoDrive
from google_drive_mcp.mcp.middleware import Runtime, _request_drive, authorize
from google_drive_mcp.mcp.tools import handle_tool

MD = "text/markdown"


def _many(drive: FakeDrive, count: int) -> list[str]:
    ids = []
    for n in range(count):
        fid = f"extra-{n}"
        drive.add(
            FakeFile(id=fid, name=f"n{n}.md", mime_type=MD, parents=["folder-a"], content="x")
        )
        ids.append(fid)
    return ids


# ---- the call asks once ---------------------------------------------------------------


def test_drive_read_asks_drive_for_the_file_once(runtime, fake_drive, authz):
    handle_tool(runtime, "drive_read", {"file_id": "nested-doc"}, authz)
    assert fake_drive.metadata_get_count == 1


def test_grep_on_ids_asks_drive_for_each_id_once(runtime, fake_drive, authz):
    ids = _many(fake_drive, 5)
    result = handle_tool(runtime, "drive_grep", {"pattern": "x", "file_ids": ids}, authz)
    assert result["status"] == "COMPLETE"
    assert result["files_scanned"] == 5
    assert fake_drive.metadata_get_count == 5


def test_the_memo_lasts_one_call(runtime, fake_drive, authz):
    handle_tool(runtime, "drive_read", {"file_id": "nested-doc"}, authz)
    handle_tool(runtime, "drive_read", {"file_id": "nested-doc"}, authz)
    # A later call asks Drive again, so an edit or a move is seen (Article III).
    assert fake_drive.metadata_get_count == 2


# ---- side by side ---------------------------------------------------------------------


class SlowMeta(FakeDrive):
    """A fake Drive whose metadata get takes a moment and counts how many run at once."""

    def __init__(self, source: FakeDrive, *, delay: float = 0.05) -> None:
        super().__init__()
        self.files = dict(source.files)
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def get_metadata(self, file_id):
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            time.sleep(self.delay)
            return super().get_metadata(file_id)
        finally:
            with self._lock:
                self.in_flight -= 1


def test_the_access_check_looks_the_ids_up_side_by_side(settings, authz):
    base = FakeDrive.sample()
    ids = _many(base, 8)
    slow = SlowMeta(base, delay=0.05)
    runtime = Runtime(settings=settings, drive=slow)
    started = time.monotonic()
    result = handle_tool(runtime, "drive_grep", {"pattern": "x", "file_ids": ids}, authz)
    elapsed = time.monotonic() - started
    assert result["status"] == "COMPLETE" and result["files_scanned"] == 8
    assert slow.max_in_flight > 1
    # Eight gets of 0.05 s one after another is 0.4 s, and used to be asked twice.
    assert elapsed < 0.3


def test_a_refused_call_still_looks_up_every_named_id(settings, authz):
    base = FakeDrive.sample()
    inside = _many(base, 2)
    runtime = Runtime(settings=settings, drive=base)
    result = handle_tool(
        runtime, "drive_grep", {"pattern": "x", "file_ids": ["no-such-file", *inside]}, authz
    )
    assert result["category"] == "AUTHORIZATION_ERROR"
    # An id Drive does not know and one it does take the same calls, in either order.
    assert base.metadata_get_count == 3


def test_a_failed_lookup_raises_its_own_error_at_its_place(settings, authz):
    base = FakeDrive.sample()
    ids = _many(base, 3)
    original = base.get_metadata

    def get(file_id):
        if file_id == ids[1]:
            raise GoogleApiError(429)
        return original(file_id)

    base.get_metadata = get  # type: ignore[method-assign]
    runtime = Runtime(settings=settings, drive=base)
    result = handle_tool(runtime, "drive_grep", {"pattern": "x", "file_ids": ids}, authz)
    assert result["status"] == "ERROR"
    assert result["category"] == "RATE_LIMITED"


def test_worker_threads_see_the_requests_own_drive(settings, authz):
    """In production no drive is injected: each call binds one, and workers must find it."""
    base = FakeDrive.sample()
    ids = _many(base, 4)

    class Bound(Runtime):
        def mint_and_bind(self):
            _request_drive.set(MemoDrive(base))
            return object()

    runtime = Bound(settings=settings, drive=None)
    assert runtime.drive is None
    decision = authorize(runtime, {"file_ids": ids}, authorization=authz)
    assert decision.allowed, decision
    assert base.metadata_get_count == 4


# ---- the memo itself ------------------------------------------------------------------


def test_the_memo_asks_the_wrapped_drive_once_and_hands_out_copies():
    base = FakeDrive.sample()
    memo = MemoDrive(base)
    first = memo.get_metadata("nested-doc")
    first["name"] = "changed"
    second = memo.get_metadata("nested-doc")
    assert base.metadata_get_count == 1
    assert second["name"] == "Notes"


def test_the_memo_does_not_remember_an_error():
    base = FakeDrive.sample()
    memo = MemoDrive(base)
    with pytest.raises(GoogleApiError):
        memo.get_metadata("missing")
    with pytest.raises(GoogleApiError):
        memo.get_metadata("missing")
    assert base.metadata_get_count == 2


def test_the_memo_looks_up_parents_like_the_client_does():
    base = FakeDrive.sample()
    memo = MemoDrive(base)
    assert memo.parent_lookup("nested-doc") == ["folder-a"]
    assert memo.parent_lookup("missing") is None
    assert memo.parent_lookup("nested-doc") == ["folder-a"]
    assert base.metadata_get_count == 2  # one for nested-doc, one for the miss


def test_the_memo_passes_everything_else_through():
    base = FakeDrive.sample()
    memo = MemoDrive(base)
    assert [c.id for c in memo.list_children("folder-a")] == [
        c.id for c in base.list_children("folder-a")
    ]
    assert memo.content_media_count == base.content_media_count
