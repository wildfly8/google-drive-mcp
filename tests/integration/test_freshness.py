"""Second read sees fixture updates."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_reread_sees_updated_fixture(runtime, fake_drive):
    first = handle_tool(runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token")
    fake_drive.update_content("nested-doc", "brand-new unique phrase")
    second = handle_tool(runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token")
    assert first["content"] != second["content"]
    assert "brand-new unique phrase" in second["content"]
    assert "idempotency" not in second["content"]
