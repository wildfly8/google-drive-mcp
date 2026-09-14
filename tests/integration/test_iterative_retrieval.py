"""find → read → grep iteration against the fake Drive."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_iterative_find_read_grep_read_grep(runtime, authz):
    found = handle_tool(
        runtime, "drive_find", {"folder_id": "folder-a", "name_pattern": "Notes"},
        authz,
    )
    assert found["candidates"]
    file_id = next(c["file"]["id"] for c in found["candidates"] if c["file"]["id"] == "nested-doc")
    read1 = handle_tool(runtime, "drive_read", {"file_id": file_id}, authz)
    assert "idempotency" in read1["content"]
    grep1 = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": [file_id]},
        authz,
    )
    assert grep1["matches"]
    read2 = handle_tool(runtime, "drive_read", {"file_id": file_id}, authz)
    assert read2["content"] == read1["content"]
    grep2 = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": [file_id]},
        authz,
    )
    assert grep2["matches"] == grep1["matches"]
