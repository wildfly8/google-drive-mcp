"""drive_read: live text + provenance. No module-level content cache."""

from __future__ import annotations

from datetime import UTC, datetime

from google_drive_mcp.domain.budgets import MAX_BYTES_PER_FILE, Budget
from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.operation import OperationStatus, PartialReason
from google_drive_mcp.infra.google_drive.export import fetch_text, representation_for


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
    meta = DriveFile.from_metadata(drive.get_metadata(file_id))
    representation = representation_for(meta.mime_type, content_format)
    exported = fetch_text(
        drive,
        file_id,
        meta.mime_type,
        representation,
        max_bytes=cap,
        request_id=request_id,
    )
    budget.note_bytes(exported.byte_length)
    retrieved_at = _now()
    result = {
        "status": (
            OperationStatus.PARTIAL.value if exported.truncated else OperationStatus.COMPLETE.value
        ),
        "file_id": meta.id,
        "file_name": meta.name,
        "mime_type": meta.mime_type,
        "modified_time": meta.modified_time,
        "source_url": meta.source_url,
        "retrieved_at": retrieved_at,
        "representation": exported.representation,
        "content": exported.text,
    }
    if exported.truncated:
        result["partial_reason"] = PartialReason.max_bytes.value
    return result


def validate_read_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import require_file_id

    file_id = arguments.get("file_id")
    if not isinstance(file_id, str):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    require_file_id(file_id)
    max_bytes = arguments.get("max_bytes")
    if max_bytes is not None and (
        not isinstance(max_bytes, int) or max_bytes < 1 or max_bytes > 5_000_000
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
