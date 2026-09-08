"""Unauthenticated tools never hit content I/O; AUTH replay on drive_grep."""

from __future__ import annotations

from fakes.fake_drive import FakeDrive
from google_drive_mcp.mcp.tools import handle_tool


def test_unauthenticated_tools_do_not_hit_content(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    for name, args in (
        ("drive_ls", {"folder_id": "folder-a"}),
        ("drive_find", {"folder_id": "folder-a"}),
        ("drive_read", {"file_id": "nested-doc"}),
        ("drive_grep", {"pattern": "idempotency", "folder_id": "folder-a"}),
    ):
        fake_drive.reset_counters()
        result = handle_tool(runtime, name, args, None)
        assert result["category"] == "AUTHENTICATION_ERROR"
        assert fake_drive.content_count == 0
        assert fake_drive.metadata_get_count == 0


def test_drive_grep_folder_and_outside_file_is_authorization_error(
    runtime, fake_drive: FakeDrive
):
    fake_drive.reset_counters()
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "secret", "folder_id": "folder-a", "file_ids": ["outside-doc"]},
        "Bearer test-token",
    )
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count >= 1
