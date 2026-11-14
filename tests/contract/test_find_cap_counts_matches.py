"""drive_find's max_results counts files whose names match, not everything Drive lists.

Drive's `name contains` matches whole words by prefix, so it also returns near-misses
(chatgpt-2025-01-03-a.md for the stem chatgpt-2025-03). The server drops them, but they
must not use up the cap, or a small max_results returns fewer files than exist.
"""

from __future__ import annotations

from dataclasses import replace

from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
from google_drive_mcp.retrieval.find import drive_find

MD = "text/markdown"


class OverBroadDrive(FakeDrive):
    """A Drive whose name filter lets every file through, as word-prefix matching can."""

    def _accepts(self, item, filt, *, include_trashed):
        if filt is not None and filt.name_contains:
            filt = replace(filt, name_contains=None)
        return super()._accepts(item, filt, include_trashed=include_trashed)


def _kb() -> OverBroadDrive:
    """Eight near-misses that sort before four real March files."""
    drive = OverBroadDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="kb", name="kb", mime_type=FOLDER_MIME, parents=["root"]))
    for n in range(8):
        drive.add(
            FakeFile(id=f"near-{n}", name=f"log-2025-01-03-{n}.md", mime_type=MD, parents=["kb"])
        )
    for day in ("04", "08", "14", "20"):
        drive.add(
            FakeFile(id=f"mar-{day}", name=f"log-2025-03-{day}.md", mime_type=MD, parents=["kb"])
        )
    return drive


def _ids(result):
    return [c["file"]["id"] for c in result["candidates"]]


def test_near_misses_do_not_use_up_a_small_max_results():
    result = drive_find(_kb(), folder_id="kb", name_pattern="log-2025-03", max_results=3)
    assert _ids(result) == ["mar-04", "mar-08", "mar-14"]
    # A fourth real match exists, so the result is honestly partial.
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_files"


def test_near_misses_do_not_push_real_matches_past_a_larger_max_results():
    result = drive_find(_kb(), folder_id="kb", name_pattern="log-2025-03", max_results=10)
    assert _ids(result) == ["mar-04", "mar-08", "mar-14", "mar-20"]
    assert result["status"] == "COMPLETE"


def test_every_candidate_still_contains_the_stem():
    result = drive_find(_kb(), folder_id="kb", name_pattern="log-2025-03")
    assert result["status"] == "COMPLETE"
    assert all("log-2025-03" in c["file"]["name"] for c in result["candidates"])
    assert len(result["candidates"]) == 4
