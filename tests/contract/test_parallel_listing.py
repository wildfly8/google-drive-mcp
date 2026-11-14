"""A walk lists the folders it discovers side by side without changing what it returns.

The Drive client opts in with ``parallel_listing``. The walk still takes folders in
queue order, so the files, their depths and the completeness flags match a one-at-a-time
walk, whichever listing finishes first.
"""

from __future__ import annotations

import threading
import time

from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.domain.retrieval_scope import RetrievalScope
from google_drive_mcp.infra.google_drive.list import walk_files
from google_drive_mcp.retrieval.find import drive_find
from google_drive_mcp.retrieval.grep import drive_grep
from contract.test_shallow_first_order import EXPECTED, _kb



class ThreadedDrive(FakeDrive):
    """A fake Drive that allows side-by-side listings and takes a moment to list."""

    parallel_listing = True

    def __init__(self, source: FakeDrive | None = None, *, delay: float = 0.0) -> None:
        super().__init__()
        if source is not None:
            self.files = dict(source.files)
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.slow_threads: set[str] = set()
        self._lock = threading.Lock()

    def list_children(self, folder_id, budget=None, **kwargs):
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.slow_threads.add(threading.current_thread().name)
        try:
            time.sleep(self.delay)
            return super().list_children(folder_id, budget, **kwargs)
        finally:
            with self._lock:
                self.in_flight -= 1


def _tree() -> FakeDrive:
    """kb with four folders, one of them holding five more, and a file in each."""
    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="kb", name="kb", mime_type=FOLDER_MIME, parents=["root"]))
    for name in ("chatgpt", "gemini", "pre", "se"):
        drive.add(FakeFile(id=name, name=name, mime_type=FOLDER_MIME, parents=["kb"]))
        drive.add(
            FakeFile(id=f"{name}-f", name=f"{name}.md", mime_type="text/markdown", parents=[name])
        )
    for year in range(2022, 2027):
        drive.add(
            FakeFile(id=f"y{year}", name=str(year), mime_type=FOLDER_MIME, parents=["chatgpt"])
        )
        drive.add(
            FakeFile(
                id=f"y{year}-f", name=f"chatgpt-{year}.md", mime_type="text/markdown",
                parents=[f"y{year}"],
            )
        )
    drive.add(FakeFile(id="top", name="essay.md", mime_type="text/markdown", parents=["kb"]))
    return drive


def _walk(drive):
    return walk_files(
        drive, RetrievalScope.from_tool_args(folder_id="kb"), Budget(max_files=500),
        honor_file_cap=False,
    )


def _shape(result):
    return (
        [f.id for f in result.files],
        dict(result.depths),
        result.truncated,
        result.time_exceeded,
        result.rate_limited,
    )


def test_a_parallel_walk_returns_what_a_one_at_a_time_walk_returns():
    plain = _tree()
    threaded = ThreadedDrive(plain, delay=0.01)
    assert _shape(_walk(threaded)) == _shape(_walk(plain))


def test_folders_of_one_level_are_listed_at_the_same_time():
    threaded = ThreadedDrive(_tree(), delay=0.05)
    started = time.monotonic()
    _walk(threaded)
    elapsed = time.monotonic() - started
    assert threaded.max_in_flight >= 4
    assert any(name.startswith("list-walk") for name in threaded.slow_threads)
    # 12 listings of 0.05 s: one at a time is 0.6 s; three levels side by side is ~0.15 s.
    assert elapsed < 0.45


def test_a_port_that_does_not_opt_in_is_listed_one_folder_at_a_time():
    class OneAtATime(ThreadedDrive):
        parallel_listing = False

    plain = OneAtATime(_tree(), delay=0.005)
    _walk(plain)
    assert plain.max_in_flight == 1
    assert plain.slow_threads == {"MainThread"}


def test_the_shallow_first_find_and_grep_results_are_unchanged():
    kb = _kb()
    threaded = ThreadedDrive(kb, delay=0.005)
    found = drive_find(threaded, folder_id="kb", max_results=3)
    reference = drive_find(kb, folder_id="kb", max_results=3)
    assert [c["file"]["id"] for c in found["candidates"]] == [
        c["file"]["id"] for c in reference["candidates"]
    ]
    assert found["status"] == reference["status"] == "PARTIAL"
    grep = drive_grep(threaded, pattern="sheaf", folder_id="kb")
    assert [m["file_id"] for m in grep["matches"]] == EXPECTED


def test_a_listing_that_hits_the_rate_limit_is_partial_and_keeps_earlier_files():
    class Limited(ThreadedDrive):
        def list_children(self, folder_id, budget=None, **kwargs):
            if folder_id == "gemini":
                raise GoogleApiError(429)
            return super().list_children(folder_id, budget, **kwargs)

    result = _walk(Limited(_tree(), delay=0.01))
    assert result.rate_limited is True
    # Folders are taken in queue order, so everything listed before gemini is kept.
    assert "top" in [f.id for f in result.files]
    assert "chatgpt-f" in [f.id for f in result.files]


def test_the_time_cap_flag_is_read_from_each_listing_not_from_a_shared_attribute():
    class Marked(list):
        time_exceeded = True

    class CutOne(ThreadedDrive):
        def list_children(self, folder_id, budget=None, **kwargs):
            items = super().list_children(folder_id, budget, **kwargs)
            return Marked(items) if folder_id == "kb" else items

    cut = _walk(CutOne(_tree()))
    assert cut.time_exceeded is True

    class Clean(list):
        time_exceeded = False

    class ClaimsCutElsewhere(ThreadedDrive):
        def list_children(self, folder_id, budget=None, **kwargs):
            self.list_time_exceeded = True  # another listing's flag, left behind
            return Clean(super().list_children(folder_id, budget, **kwargs))

    assert _walk(ClaimsCutElsewhere(_tree())).time_exceeded is False


def test_a_walk_that_stops_early_leaves_no_listing_threads_running():
    threaded = ThreadedDrive(_tree(), delay=0.02)
    walk_files(
        threaded, RetrievalScope.from_tool_args(folder_id="kb"), Budget(max_files=2),
        honor_file_cap=True,
    )
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not [t for t in threading.enumerate() if t.name.startswith("list-walk")]:
            break
        time.sleep(0.02)
    assert not [t for t in threading.enumerate() if t.name.startswith("list-walk")]
