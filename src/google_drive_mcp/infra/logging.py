"""Structured logging that redacts secrets and never logs document bodies."""

from __future__ import annotations

import logging
import re
from typing import Any

_LOG = logging.getLogger("google_drive_mcp")

_BEARER_RE = re.compile(r"(?i)bearer\s+\S+")
_AUTH_HEADER_RE = re.compile(r"(?i)authorization:\s*\S+")


def redact(text: str, extra_secrets: list[str] | None = None) -> str:
    out = _BEARER_RE.sub("Bearer [REDACTED]", text)
    out = _AUTH_HEADER_RE.sub("Authorization: [REDACTED]", out)
    for secret in extra_secrets or []:
        if secret:
            out = out.replace(secret, "[REDACTED]")
    return out


def get_logger() -> logging.Logger:
    return _LOG


def log_chain_event(
    *,
    request_id: str,
    principal_id: str,
    step_failed: str | None,
    category: str,
) -> None:
    _LOG.info(
        "chain",
        extra={
            "request_id": request_id,
            "principal_id": principal_id,
            "step_failed": step_failed,
            "category": category,
        },
    )


def log_retrieval(
    *,
    request_id: str,
    tool: str,
    file_count: int,
    bytes_processed: int,
    duration_ms: float,
    result_count: int,
    status: str,
    error_category: str | None = None,
) -> None:
    extra: dict[str, Any] = {
        "request_id": request_id,
        "tool": tool,
        "file_count": file_count,
        "bytes_processed": bytes_processed,
        "duration_ms": round(duration_ms, 2),
        "result_count": result_count,
        "status": status,
    }
    if error_category:
        extra["error_category"] = error_category
    _LOG.info("retrieval", extra=extra)
