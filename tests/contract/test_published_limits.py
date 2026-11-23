"""The per-call ceilings are the documented ones, and a caller cannot raise them.

The tool schemas publish a ceiling for max_results (40), max_matches (50) and max_bytes
(20 MB), and the instructions promise at most 20 MB per call; the 200-file and 25 s caps are
the server's own. Together they stand between a subscriber and a bulk copy of kb, so each is
pinned by value here, and by behaviour: the cap stops the call, and asking for more is
refused or clamped.
"""

from __future__ import annotations

import pytest

from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
from google_drive_mcp.domain import budgets
from google_drive_mcp.mcp import validation
from google_drive_mcp.mcp.tools import handle_tool
from google_drive_mcp.retrieval.find import drive_find
from google_drive_mcp.retrieval.grep import drive_grep

MD = "text/markdown"


def test_the_limits_are_the_published_numbers():
    assert budgets.MAX_FILES == 40  # ls and find
    assert budgets.GREP_MAX_FILES == 200
    assert budgets.MAX_MATCHES == 50
    assert budgets.MAX_BYTES_PER_OPERATION == 20_000_000
    assert budgets.MAX_BYTES_PER_FILE == 20_000_000
    assert budgets.MAX_EXPORT_SIZE == 20_000_000
    assert budgets.MAX_EXECUTION_TIME == 25.0


def test_the_argument_ceilings_are_the_published_numbers():
    assert validation.MAX_RESULTS_MAX == 40
    assert validation.MAX_MATCHES_MAX == 50
    assert validation.MAX_BYTES_MAX == 20_000_000


def _many(drive: FakeDrive, count: int, *, folder: str = "wide", content: str = "needle") -> None:
    drive.add(FakeFile(id=folder, name=folder, mime_type=FOLDER_MIME, parents=["folder-a"]))
    for n in range(count):
        drive.add(
            FakeFile(
                id=f"{folder}-{n:03d}",
                name=f"needle-{n:03d}.md",
                mime_type=MD,
                parents=[folder],
                content=content,
            )
        )


def test_ls_and_find_stop_at_forty_without_being_asked(runtime, fake_drive, authz):
    _many(fake_drive, 45)
    ls = handle_tool(runtime, "drive_ls", {"folder_id": "wide"}, authz)
    assert len(ls["children"]) == 40 and ls["status"] == "PARTIAL"
    find = handle_tool(
        runtime, "drive_find", {"folder_id": "wide", "name_pattern": "needle"}, authz
    )
    assert len(find["candidates"]) == 40 and find["status"] == "PARTIAL"


def test_grep_stops_at_fifty_matches_without_being_asked(runtime, fake_drive, authz):
    fake_drive.add(
        FakeFile(
            id="many-hits",
            name="hits.md",
            mime_type=MD,
            parents=["folder-a"],
            content="\n".join(f"needle line {n}" for n in range(60)),
        )
    )
    result = handle_tool(
        runtime, "drive_grep", {"pattern": "needle", "file_ids": ["many-hits"]}, authz
    )
    assert len(result["matches"]) == 50
    assert result["status"] == "PARTIAL" and result["partial_reason"] == "max_matches"
    assert result["next_cursor"] == "many-hits:50"


def test_a_caller_cannot_raise_the_match_cap_past_fifty(fake_drive):
    fake_drive.add(
        FakeFile(
            id="many-hits",
            name="hits.md",
            mime_type=MD,
            parents=["folder-a"],
            content="\n".join(f"needle line {n}" for n in range(200)),
        )
    )
    result = drive_grep(fake_drive, pattern="needle", file_ids=["many-hits"], max_matches=10_000)
    assert len(result["matches"]) == 50


def test_a_caller_cannot_raise_the_find_cap_past_forty(fake_drive):
    _many(fake_drive, 60)
    result = drive_find(fake_drive, folder_id="wide", name_pattern="needle", max_results=10_000)
    assert len(result["candidates"]) == 40


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("drive_grep", {"pattern": "x", "max_matches": 51}),
        ("drive_ls", {"max_results": 41}),
        ("drive_find", {"name_pattern": "x", "max_results": 41}),
        ("drive_read", {"file_id": "nested-doc", "max_bytes": 20_000_001}),
    ],
)
def test_a_request_above_a_ceiling_is_invalid(runtime, authz, tool: str, arguments: dict):
    result = handle_tool(runtime, tool, arguments, authz)
    assert result["status"] == "ERROR" and result["category"] == "INVALID_ARGUMENT"
