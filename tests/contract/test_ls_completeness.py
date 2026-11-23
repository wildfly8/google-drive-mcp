"""drive_ls says when a listing is empty, cut, or complete (Article X).

An empty folder is EMPTY, a wide folder is PARTIAL with a token to continue, and a listing
cut by the clock is PARTIAL: the host must never read an incomplete listing as the whole.
"""

from __future__ import annotations

from fakes.fake_drive import FOLDER_MIME, FakeFile
from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.mcp.tools import handle_tool
from google_drive_mcp.retrieval.ls import drive_ls

MD = "text/markdown"


def _folder(drive, folder_id: str, parent: str = "folder-a") -> None:
    drive.add(FakeFile(id=folder_id, name=folder_id, mime_type=FOLDER_MIME, parents=[parent]))


def test_an_empty_folder_is_empty_not_complete(runtime, fake_drive, authz):
    _folder(fake_drive, "empty-dir")
    result = handle_tool(runtime, "drive_ls", {"folder_id": "empty-dir"}, authz)
    assert result["status"] == "EMPTY"
    assert result["children"] == []


def test_a_wide_folder_is_paged_and_the_pages_add_up(runtime, fake_drive, authz):
    _folder(fake_drive, "wide")
    for n in range(5):
        fake_drive.add(
            FakeFile(id=f"w{n}", name=f"doc{n}.md", mime_type=MD, parents=["wide"], content="x")
        )
    names: list[str] = []
    args: dict = {"folder_id": "wide", "max_results": 2}
    statuses = []
    for _ in range(5):
        page = handle_tool(runtime, "drive_ls", args, authz)
        statuses.append(page["status"])
        names += [child["name"] for child in page["children"]]
        if page["status"] == "COMPLETE":
            break
        assert page["status"] == "PARTIAL" and page["partial_reason"] == "pagination"
        args = {**args, "page_token": page["next_page_token"]}
    assert statuses == ["PARTIAL", "PARTIAL", "COMPLETE"]
    assert names == [f"doc{n}.md" for n in range(5)]


def test_a_listing_cut_by_the_clock_is_partial_not_complete(fake_drive):
    now = [0.0]
    listed = fake_drive.list_children

    def slow(*args, **kwargs):
        result = listed(*args, **kwargs)
        now[0] = 100.0  # the listing used up more than the whole time budget
        return result

    fake_drive.list_children = slow  # type: ignore[method-assign]
    budget = Budget(max_execution_time=25.0, clock=lambda: now[0])
    result = drive_ls(fake_drive, folder_id="folder-a", budget=budget)
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_execution_time"
    assert result["children"], "what was listed before the cut still comes back"
