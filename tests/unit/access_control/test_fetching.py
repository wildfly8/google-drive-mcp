"""The access check looks up every named id, whatever the first lookup says (AC-FR-025).

`_Fetching` starts one lookup per named id and hands the results back in order. When the first
id is refused, the check leaves early. The lookups still waiting must not be cancelled: an id
outside the folder, a missing id and an ungranted id have to take the same Drive calls, and
which calls Drive sees must not depend on thread timing.
"""

from __future__ import annotations

import threading

from google_drive_mcp.access_control import chain


def test_leaving_early_does_not_cancel_the_lookups_still_waiting(monkeypatch):
    # One worker, so the later lookups are queued behind the first when the block is left.
    monkeypatch.setattr(chain, "FETCH_WORKERS", 1)
    release = threading.Event()
    all_done = threading.Event()
    calls: list[str] = []

    def fetch(fid: str) -> list[str]:
        calls.append(fid)
        if fid == "first":
            assert release.wait(timeout=5), "the test never released the first lookup"
        if len(calls) == 3:
            all_done.set()
        return []

    with chain._Fetching(["first", "second", "third"], fetch, concurrent=True):
        pass  # a refusal leaves the block while the first lookup is still running
    release.set()
    assert all_done.wait(timeout=5), f"lookups that never ran were cancelled; ran: {calls}"
    assert calls == ["first", "second", "third"]


def test_each_named_id_is_looked_up_once_however_often_it_is_named(monkeypatch):
    calls: list[str] = []
    lock = threading.Lock()

    def fetch(fid: str) -> list[str]:
        with lock:
            calls.append(fid)
        return [fid]

    with chain._Fetching(["a", "b", "a", "c", "b"], fetch, concurrent=True) as fetching:
        assert [fetching.result(fid) for fid in ("a", "b", "a", "c", "b")] == [
            ["a"],
            ["b"],
            ["a"],
            ["c"],
            ["b"],
        ]
    assert sorted(calls) == ["a", "b", "c"]
