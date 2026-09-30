"""Temporary write tools for files inside kb: drive_write, drive_replace, drive_trash.

Registered only when DRIVE_WRITE_ENABLED is set. The same kb allow-list chain
as the read tools runs before these bodies, so nothing outside kb is touched.
"""

from __future__ import annotations

import re

from google_drive_mcp.domain.budgets import MAX_EXPORT_SIZE
from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.infra.exact_search.regex import compile_pattern
from google_drive_mcp.infra.google_drive.export import (
    DOC_MIME,
    FileNotExportableError,
    is_text_blob,
    is_workspace,
)

WRITE_TOOLS = ("drive_write", "drive_replace", "drive_trash")

MAX_REPLACEMENTS_DEFAULT = 100
MAX_REPLACEMENTS_LIMIT = 100_000

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


def _full_text(drive: object, file: DriveFile, request_id: str | None) -> str:
    """The file's whole current text, or an error. Never a truncated prefix.

    Text files must be valid UTF-8, so writing them back changes nothing but
    the replaced text.
    """
    if file.size is not None and file.size > MAX_EXPORT_SIZE:
        raise DomainError.of(ErrorCategory.RESOURCE_LIMIT, request_id=request_id)
    try:
        if file.mime_type == DOC_MIME:
            text = drive.export(file.id, "text/plain")
        else:
            raw = drive.get_media(file.id)
            if len(raw) > MAX_EXPORT_SIZE:
                raise DomainError.of(ErrorCategory.RESOURCE_LIMIT, request_id=request_id)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DomainError.of(
                    ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id
                ) from exc
    except FileNotExportableError as exc:
        raise DomainError.of(ErrorCategory.FILE_NOT_EXPORTABLE, request_id=request_id) from exc
    except GoogleApiError as exc:
        raise DomainError(map_google_error(exc, request_id=request_id)) from exc
    if len(text.encode("utf-8")) > MAX_EXPORT_SIZE:
        raise DomainError.of(ErrorCategory.RESOURCE_LIMIT, request_id=request_id)
    return text


def drive_replace(
    drive: object,
    writer: object,
    *,
    file_id: str,
    pattern: str,
    replacement: str = "",
    regex: bool = False,
    case_sensitive: bool = True,
    max_replacements: int = MAX_REPLACEMENTS_DEFAULT,
    request_id: str | None = None,
) -> dict:
    """Replace every match of pattern in one kb file, on the server.

    Only the pattern crosses the wire, so large files are never round-tripped
    through the caller. Nothing is written when there is no match or when the
    match count exceeds max_replacements.
    """
    file = _target(drive, file_id, request_id)
    upload_mime = upload_mime_for(file)
    if upload_mime is None:
        raise DomainError.of(ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id)
    compiled = compile_pattern(pattern, regex=regex, case_sensitive=case_sensitive)
    if compiled.search("") is not None:
        raise DomainError.of(
            ErrorCategory.INVALID_ARGUMENT,
            message="The pattern can match empty text; use one that needs at least one character.",
            request_id=request_id,
        )
    text = _full_text(drive, file, request_id)
    try:
        new_text, count = compiled.subn(lambda _match: replacement, text)
    except (RecursionError, re.error) as exc:
        raise DomainError.of(ErrorCategory.SEARCH_ERROR, request_id=request_id) from exc
    result = {
        "status": "COMPLETE",
        "file_id": file.id,
        "file_name": file.name,
        "mime_type": file.mime_type,
        "replacements": count,
        "source_url": file.source_url,
    }
    if count == 0:
        return result
    if count > max_replacements:
        raise DomainError.of(
            ErrorCategory.INVALID_ARGUMENT,
            message=(
                f"{count} matches is more than max_replacements ({max_replacements}); "
                "nothing was changed. Raise max_replacements if every match should go."
            ),
            request_id=request_id,
        )
    try:
        updated = DriveFile.from_metadata(writer.replace_text(file_id, new_text, upload_mime))
    except GoogleApiError as exc:
        raise _write_failed(exc, request_id) from None
    result.update(
        modified_time=updated.modified_time,
        bytes_before=len(text.encode("utf-8")),
        bytes_after=len(new_text.encode("utf-8")),
    )
    return result


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


def validate_replace_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import require_file_id

    require_file_id(arguments.get("file_id"))
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern or len(pattern) > 1000:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    replacement = arguments.get("replacement")
    if replacement is not None and (not isinstance(replacement, str) or len(replacement) > 10_000):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    for key in ("regex", "case_sensitive"):
        value = arguments.get(key)
        if value is not None and not isinstance(value, bool):
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    limit = arguments.get("max_replacements")
    if limit is not None and (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_REPLACEMENTS_LIMIT
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)


def validate_trash_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import require_file_id

    require_file_id(arguments.get("file_id"))
