"""Structured logging that redacts secrets and never logs document bodies."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_LOG = logging.getLogger("google_drive_mcp")
_HANDLER_NAME = "google_drive_mcp_json"
# Only these record fields are written; anything else passed in extra is dropped.
_FIELDS = (
    "request_id",
    "tool",
    "file_count",
    "bytes_processed",
    "duration_ms",
    "result_count",
    "status",
    "error_category",
    "step_failed",
    "category",
    "principal_id",
    "http_status",
    "event",
)

_BEARER_RE = re.compile(r"(?i)bearer\s+\S+")
_AUTH_HEADER_RE = re.compile(r"(?i)authorization:\s*\S+")


def redact(text: str, extra_secrets: list[str] | None = None) -> str:
    out = _BEARER_RE.sub("Bearer [REDACTED]", text)
    out = _AUTH_HEADER_RE.sub("Authorization: [REDACTED]", out)
    for secret in extra_secrets or []:
        if secret:
            out = out.replace(secret, "[REDACTED]")
    return out


class JsonFormatter(logging.Formatter):
    """One JSON object per line; Cloud Logging reads `severity` and the fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": record.levelname,
            "message": redact(record.getMessage()),
        }
        for key in _FIELDS:
            value = getattr(record, key, None)
            if value is None:
                continue
            entry[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info and record.exc_info[0] is not None:
            # The type only: exception text can carry document text or addresses.
            entry["exception"] = record.exc_info[0].__name__
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    """JSON lines on stdout for this app's logger, and httpx quiet. Safe to call twice.

    httpx logs every request URL at INFO, and those URLs can carry API keys and
    the email a subscriber typed.
    """
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False
    if any(handler.get_name() == _HANDLER_NAME for handler in _LOG.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    _LOG.addHandler(handler)


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
    level = logging.WARNING if status == "ERROR" else logging.INFO
    _LOG.log(level, "retrieval", extra=extra)
