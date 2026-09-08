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


def test_read_metadata_404_after_allow_is_file_not_found(runtime, fake_drive):
    from google_drive_mcp.domain.google_errors import GoogleApiError

    original = fake_drive.get_metadata
    seen = {"n": 0}

    def second_get_misses(file_id: str):
        seen["n"] += 1
        if seen["n"] > 1:
            raise GoogleApiError(404)
        return original(file_id)

    fake_drive.get_metadata = second_get_misses  # type: ignore[method-assign]
    result = handle_tool(
        runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token"
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "FILE_NOT_FOUND"


def test_read_metadata_429_after_allow_is_rate_limited(runtime, fake_drive):
    from google_drive_mcp.domain.google_errors import GoogleApiError

    original = fake_drive.get_metadata
    seen = {"n": 0}

    def second_get_limited(file_id: str):
        seen["n"] += 1
        if seen["n"] > 1:
            raise GoogleApiError(429)
        return original(file_id)

    fake_drive.get_metadata = second_get_limited  # type: ignore[method-assign]
    result = handle_tool(
        runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token"
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "RATE_LIMITED"
