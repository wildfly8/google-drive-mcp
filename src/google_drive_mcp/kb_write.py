"""Temporary write tools for files inside kb: drive_write and drive_trash.

Registered only when DRIVE_WRITE_ENABLED is set. The same kb allow-list chain
as the read tools runs before these bodies, so nothing outside kb is touched.
"""

from __future__ import annotations

from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.infra.google_drive.export import DOC_MIME, is_text_blob, is_workspace

WRITE_TOOLS = ("drive_write", "drive_trash")

NO_WRITE_GRANT = (
    "Google refused the change: the server's Google login needs the drive scope "
    "and edit access to this file."
)


def _target(drive: object, file_id: str, request_id: str | None) -> DriveFile:
    try:
        return DriveFile.from_metadata(drive.get_metadata(file_id))
    except GoogleApiError as exc:
        raise DomainError(map_google_error(exc, request_id=request_id)) from exc


def _write_failed(exc: GoogleApiError, request_id: str | None) -> DomainError:
    if exc.status in (401, 403):
        return DomainError.of(
            ErrorCategory.AUTHORIZATION_ERROR, message=NO_WRITE_GRANT, request_id=request_id
        )
    return DomainError(map_google_error(exc, request_id=request_id))


def upload_mime_for(file: DriveFile) -> str | None:
    """The upload type that replaces this file's text, or None if it cannot be."""
    if file.is_folder:
        return None
    if file.mime_type == DOC_MIME:
        return "text/plain"
    if is_workspace(file.mime_type):
        return None
    if is_text_blob(file.mime_type, file.name):
        return file.mime_type or "application/octet-stream"
    return None


def drive_write(
    drive: object,
    writer: object,
    *,
    file_id: str,
    content: str,
    request_id: str | None = None,
) -> dict:
    file = _target(drive, file_id, request_id)
    upload_mime = upload_mime_for(file)
    if upload_mime is None:
        raise DomainError.of(ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id)
    try:
        updated = DriveFile.from_metadata(writer.replace_text(file_id, content, upload_mime))
    except GoogleApiError as exc:
        raise _write_failed(exc, request_id) from None
    return {
        "status": "COMPLETE",
        "file_id": updated.id,
        "file_name": updated.name,
        "mime_type": updated.mime_type,
        "modified_time": updated.modified_time,
        "source_url": updated.source_url,
        "bytes_written": len(content.encode("utf-8")),
    }


def drive_trash(
    drive: object,
    writer: object,
    *,
    file_id: str,
    request_id: str | None = None,
) -> dict:
    file = _target(drive, file_id, request_id)
    if file.is_folder:
        raise DomainError.of(
            ErrorCategory.INVALID_ARGUMENT,
            message="drive_trash moves one file to the trash, not a folder.",
            request_id=request_id,
        )
    if not file.trashed:
        try:
            file = DriveFile.from_metadata(writer.trash(file_id))
        except GoogleApiError as exc:
            raise _write_failed(exc, request_id) from None
    return {
        "status": "COMPLETE",
        "file_id": file.id,
        "file_name": file.name,
        "trashed": True,
        "source_url": file.source_url,
    }


def validate_write_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import MAX_BYTES_MAX, require_file_id

    require_file_id(arguments.get("file_id"))
    content = arguments.get("content")
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_BYTES_MAX:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)


def validate_trash_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import require_file_id

    require_file_id(arguments.get("file_id"))
