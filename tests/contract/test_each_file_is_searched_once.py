"""A file that Drive lists twice is searched once (Article IX: results do not depend on how
Drive happens to list).

A file with two parents inside kb shows up in both folders' listings; a host can also repeat
an id in file_ids. Either way each match appears once and the file counts once.
"""

from __future__ import annotations

from fakes.fake_drive import FOLDER_MIME, FakeFile
from google_drive_mcp.mcp.tools import handle_tool


def _matches_in(result: dict, file_id: str) -> list[dict]:
    return [m for m in result["matches"] if m["file_id"] == file_id]


def test_a_file_with_two_parents_in_kb_is_scanned_once(runtime, fake_drive, authz):
    fake_drive.add(FakeFile(id="sub-b", name="Sub", mime_type=FOLDER_MIME, parents=["folder-a"]))
    fake_drive.add(
        FakeFile(
            id="twin",
            name="twin.txt",
            mime_type="text/plain",
            parents=["folder-a", "sub-b"],
            content="zebra-unique appears here\n",
        )
    )
    result = handle_tool(
        runtime, "drive_grep", {"pattern": "zebra-unique", "folder_id": "folder-a"}, authz
    )
    assert len(_matches_in(result, "twin")) == 1
    once = result["files_scanned"]

    # The same count as when the file has a single parent: listing it twice adds nothing.
    fake_drive.files["twin"].parents = ["folder-a"]
    again = handle_tool(
        runtime, "drive_grep", {"pattern": "zebra-unique", "folder_id": "folder-a"}, authz
    )
    assert again["files_scanned"] == once
    assert len(_matches_in(again, "twin")) == 1


def test_a_repeated_file_id_is_scanned_once(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "alpha idempotency", "file_ids": ["nested-doc", "nested-doc", "nested-doc"]},
        authz,
    )
    assert result["status"] == "COMPLETE"
    assert result["files_scanned"] == 1
    assert len(_matches_in(result, "nested-doc")) == 1
