"""Files directly in a folder are listed and scanned before its subfolders' files.

The kb keeps its examined essays in the root and its archives in subfolders,
so a search of kb reaches the essays first even when archive files are smaller.
"""

from __future__ import annotations

from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.retrieval.find import drive_find
from google_drive_mcp.retrieval.grep import drive_grep
from google_drive_mcp.retrieval.ls import drive_ls

MD = "application/octet-stream"


def _kb() -> FakeDrive:
    """kb root: two essays and a README; archives one and two levels down.

    The archive files are smaller than the essays, so size alone would scan
    them first.
    """
    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="kb", name="kb", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(FakeFile(id="chatgpt", name="chatgpt", mime_type=FOLDER_MIME, parents=["kb"]))
    drive.add(FakeFile(id="y2025", name="2025", mime_type=FOLDER_MIME, parents=["chatgpt"]))
    drive.add(FakeFile(id="se", name="stackexchange", mime_type=FOLDER_MIME, parents=["kb"]))
    drive.add(
        FakeFile(
            id="essay-big",
            name="topos-truth-is-local.md",
            mime_type=MD,
            parents=["kb"],
            content="sheaf here\n" + "x" * 3000,
        )
    )
    drive.add(
        FakeFile(
            id="essay-small",
            name="site-before-sheaf.md",
            mime_type=MD,
            parents=["kb"],
            content="sheaf here\n" + "x" * 1000,
        )
    )
    drive.add(FakeFile(id="readme", name="README.md", mime_type=MD, parents=["kb"], content="layout"))
    drive.add(
        FakeFile(
            id="se-1", name="activity-2025-01-05.md", mime_type=MD, parents=["se"], content="sheaf a\n"
        )
    )
    drive.add(
        FakeFile(
            id="cg-1",
            name="chatgpt-2025-03-14.md",
            mime_type=MD,
            parents=["y2025"],
            content="sheaf\n",
        )
    )
    drive.add(
        FakeFile(
            id="cg-2",
            name="chatgpt-2025-04-01.md",
            mime_type=MD,
            parents=["y2025"],
            content="sheaf bb\n",
        )
    )
    return drive


EXPECTED = ["essay-small", "essay-big", "se-1", "cg-1", "cg-2"]


def test_folder_grep_scans_the_folders_own_files_before_smaller_files_below():
    result = drive_grep(_kb(), pattern="sheaf", folder_id="kb")
    assert result["status"] == "COMPLETE"
    assert [m["file_id"] for m in result["matches"]] == EXPECTED


def test_grep_continuations_keep_the_shallow_first_order():
    drive = _kb()
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        result = drive_grep(
            drive, pattern="sheaf", folder_id="kb", max_matches=1, cursor=cursor
        )
        seen += [m["file_id"] for m in result["matches"]]
        cursor = result.get("next_cursor")
        if not cursor:
            break
    assert seen == EXPECTED


def test_grep_file_cap_stops_after_the_folders_own_files():
    result = drive_grep(_kb(), pattern="sheaf", folder_id="kb", budget=Budget(max_files=3))
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_files"
    # README (6 bytes) and the two essays fill the three slots; no archive yet.
    assert [m["file_id"] for m in result["matches"]] == ["essay-small", "essay-big"]
    rest = drive_grep(
        _kb(),
        pattern="sheaf",
        folder_id="kb",
        cursor=result["next_cursor"],
        budget=Budget(max_files=3),
    )
    assert [m["file_id"] for m in rest["matches"]] == ["se-1", "cg-1", "cg-2"]


def test_grep_defers_a_shallow_file_too_large_for_the_bytes_left_and_scans_on():
    drive = _kb()
    budget = Budget(max_bytes_per_operation=2000)
    result = drive_grep(drive, pattern="sheaf", folder_id="kb", budget=budget)
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_bytes"
    assert result["deferred_file_ids"] == ["essay-big"]
    assert [m["file_id"] for m in result["matches"]] == ["essay-small", "se-1", "cg-1", "cg-2"]
    # The deferred essay is never downloaded, not even ahead of the scan.
    assert drive.content_media_count == 5


def test_find_returns_the_folders_own_files_first_under_max_results():
    drive = _kb()
    for i in range(45):
        drive.add(
            FakeFile(
                id=f"deep-{i}", name=f"a-{i:02}.md", mime_type=MD, parents=["y2025"], content="z"
            )
        )
    result = drive_find(drive, folder_id="kb", max_results=3)
    assert result["status"] == "PARTIAL"
    ids = [c["file"]["id"] for c in result["candidates"] if not c["file"]["is_folder"]]
    assert ids == ["readme", "essay-small", "essay-big"]


def test_ls_lists_files_by_name_before_folders():
    result = drive_ls(_kb(), folder_id="kb")
    names = [c["name"] for c in result["children"]]
    assert names == [
        "README.md",
        "site-before-sheaf.md",
        "topos-truth-is-local.md",
        "chatgpt",
        "stackexchange",
    ]


def test_ls_pages_follow_the_same_order():
    drive = _kb()
    first = drive_ls(drive, folder_id="kb", max_results=2)
    second = drive_ls(drive, folder_id="kb", max_results=2, page_token=first["next_page_token"])
    third = drive_ls(drive, folder_id="kb", max_results=2, page_token=second["next_page_token"])
    names = [c["name"] for page in (first, second, third) for c in page["children"]]
    assert names == [
        "README.md",
        "site-before-sheaf.md",
        "topos-truth-is-local.md",
        "chatgpt",
        "stackexchange",
    ]
