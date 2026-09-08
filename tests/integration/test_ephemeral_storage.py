"""Exports must not leave temp dirs behind."""

from __future__ import annotations

from pathlib import Path

from google_drive_mcp.mcp.tools import handle_tool


def test_no_leftover_export_tempdirs(runtime):
    before = {p.name for p in Path("/tmp").glob("gdrive-mcp-*")}
    handle_tool(runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token")
    handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        "Bearer test-token",
    )
    after = {p.name for p in Path("/tmp").glob("gdrive-mcp-*")}
    leftover = after - before
    assert leftover == set()
