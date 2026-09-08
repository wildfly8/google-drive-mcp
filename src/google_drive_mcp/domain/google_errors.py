"""Map Google HTTP failures to the shared error envelope.

Walk (list/find/grep) HTTP 429 MUST NOT go through this mapper. Those are
completeness: status PARTIAL, partial_reason RATE_LIMITED.
"""

from __future__ import annotations

from typing import Any

from google_drive_mcp.domain.errors import ErrorCategory, ErrorEnvelope, envelope


class GoogleApiError(Exception):
    """Adapter-level Google HTTP failure (used by fake and production adapters)."""

    def __init__(self, status: int, reason: str = "") -> None:
        self.status = int(status)
        self.reason = reason
        super().__init__(f"Google API {self.status}")


def http_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status", None)
    if isinstance(status, int) and status > 0:
        return status
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code > 0:
        return status_code
    resp: Any = getattr(exc, "resp", None)
    if resp is not None:
        raw = getattr(resp, "status", None) or getattr(resp, "status_code", None)
        if raw is not None:
            return int(raw)
    return None


def map_google_error(exc: BaseException, *, request_id: str | None = None) -> ErrorEnvelope:
    """Map 404 / permission-as-404 and single-file 429.

    Do not call this for list/find/grep walk 429.
    """
    status = http_status(exc)
    if status in (404, 403):
        return envelope(ErrorCategory.FILE_NOT_FOUND, request_id=request_id)
    if status == 429:
        return envelope(ErrorCategory.RATE_LIMITED, request_id=request_id)
    return envelope(ErrorCategory.DRIVE_API_ERROR, request_id=request_id)
