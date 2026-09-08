"""drive_read contract tests."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_read_returns_body_and_provenance(runtime):
    result = handle_tool(
        runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token"
    )
    assert result["status"] == "COMPLETE"
    assert result["file_id"] == "nested-doc"
    assert "idempotency" in result["content"]
    assert result["modified_time"]
    assert result["source_url"]
    assert result["retrieved_at"]
    assert "matched_text" not in result
    assert result["representation"] == "text/plain"


def test_read_binary_is_unsupported_mime(runtime):
    result = handle_tool(
        runtime, "drive_read", {"file_id": "binary-file"}, "Bearer test-token"
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "UNSUPPORTED_MIME_TYPE"


def test_unknown_content_format_is_invalid_argument(runtime):
    result = handle_tool(
        runtime,
        "drive_read",
        {"file_id": "nested-doc", "content_format": "application/pdf"},
        "Bearer test-token",
    )
    assert result["category"] == "INVALID_ARGUMENT"
