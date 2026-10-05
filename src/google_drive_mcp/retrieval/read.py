"""drive_read: live text + provenance. No module-level content cache."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from google_drive_mcp.domain.budgets import MAX_BYTES_PER_FILE, Budget
from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.domain.operation import OperationStatus, PartialReason
from google_drive_mcp.infra.google_drive.export import fetch_text, representation_for

# Cloud Run rejects HTTP/1 responses over 32 MiB. The content travels JSON-escaped
# twice (in the tool's JSON text, then in the JSON-RPC envelope), so a quote or
# backslash costs 4 bytes and a newline 3. Keep the escaped size under this.
MAX_WIRE_BYTES = 30 * 1024 * 1024
_OTHER_CONTROL = re.compile("[\x00-\x07\x0b\x0e-\x1f]")


def wire_bytes(text: str) -> int:
    """Bytes `text` takes once escaped twice as JSON (non-ASCII stays as UTF-8)."""
    size = len(text.encode("utf-8"))
    size += 3 * (text.count('"') + text.count("\\"))
    size += 2 * sum(text.count(c) for c in "\n\r\t\b\f")
    size += 6 * len(_OTHER_CONTROL.findall(text))
    return size


def _fit_wire(text: str) -> str:
    """The longest prefix whose escaped size fits MAX_WIRE_BYTES."""
    cut = int(len(text) * MAX_WIRE_BYTES / wire_bytes(text))
    while cut > 0 and wire_bytes(text[:cut]) > MAX_WIRE_BYTES:
        cut = int(cut * 0.95)
    return text[:cut]


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def drive_read(
    drive: object,
    *,
    file_id: str,
    content_format: str | None = None,
    max_bytes: int | None = None,
    budget: Budget | None = None,
    request_id: str | None = None,
) -> dict:
    budget = budget or Budget()
    cap = max_bytes if max_bytes is not None else min(
        budget.max_bytes_per_file, MAX_BYTES_PER_FILE
    )
    try:
        meta = DriveFile.from_metadata(drive.get_metadata(file_id))
    except GoogleApiError as exc:
        raise DomainError(map_google_error(exc, request_id=request_id)) from exc
    representation = representation_for(meta.mime_type, content_format, name=meta.name)
    exported = fetch_text(
        drive,
        file_id,
        meta.mime_type,
        representation,
        max_bytes=cap,
        request_id=request_id,
        name=meta.name,
        size=meta.size,
    )
    text, truncated = exported.text, exported.truncated
    if wire_bytes(text) > MAX_WIRE_BYTES:
        # Quote- or newline-heavy text (CSV, JSON) can pass the 20 MB content cap
        # and still not fit Cloud Run's response limit once escaped.
        text, truncated = _fit_wire(text), True
    budget.note_bytes(len(text.encode("utf-8")))
    retrieved_at = _now()
    result = {
        "status": (
            OperationStatus.PARTIAL.value if truncated else OperationStatus.COMPLETE.value
        ),
        "file_id": meta.id,
        "file_name": meta.name,
        "mime_type": meta.mime_type,
        "modified_time": meta.modified_time,
        "retrieved_at": retrieved_at,
        "representation": exported.representation,
        "content": text,
    }
    if truncated:
        result["partial_reason"] = PartialReason.max_bytes.value
    return result


def validate_read_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import MAX_BYTES_MAX, MAX_BYTES_MIN, require_file_id

    file_id = arguments.get("file_id")
    if not isinstance(file_id, str):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    require_file_id(file_id)

    max_bytes = arguments.get("max_bytes")
    if max_bytes is not None and (
        not isinstance(max_bytes, int)
        or max_bytes < MAX_BYTES_MIN
        or max_bytes > MAX_BYTES_MAX
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
