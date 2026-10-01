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


def _http_error(status: int, reason: str):
    import json

    from googleapiclient.errors import HttpError
    from httplib2 import Response

    body = {"error": {"code": status, "errors": [{"reason": reason}], "message": reason}}
    return HttpError(Response({"status": str(status)}), json.dumps(body).encode())


def test_drive_403_rate_limits_are_rate_limits_not_missing_files():
    from google_drive_mcp.infra.google_drive.client import _status

    assert _status(_http_error(403, "userRateLimitExceeded")) == 429
    assert _status(_http_error(403, "rateLimitExceeded")) == 429
    assert _status(_http_error(403, "insufficientFilePermissions")) == 403
    assert _status(_http_error(404, "notFound")) == 404
