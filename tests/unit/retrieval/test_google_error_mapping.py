"""404/403-as-404 and single-file 429 use map_google_error; walk 429 does not."""

from __future__ import annotations

from google_drive_mcp.domain.errors import ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.mcp.tools import handle_tool


def test_map_google_error_404_and_403():
    assert map_google_error(GoogleApiError(404)).category == ErrorCategory.FILE_NOT_FOUND
    assert map_google_error(GoogleApiError(403)).category == ErrorCategory.FILE_NOT_FOUND
    assert map_google_error(GoogleApiError(429)).category == ErrorCategory.RATE_LIMITED
    assert map_google_error(GoogleApiError(500)).category == ErrorCategory.DRIVE_API_ERROR


def test_walk_429_is_partial_not_mapped_rate_limited_envelope(runtime, fake_drive, authz):
    fake_drive.rate_limit_lists_after = 0
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "folder-a"}, authz
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert "category" not in result
