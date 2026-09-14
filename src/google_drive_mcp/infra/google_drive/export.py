"""Export / download adapter. Workspace export map + text blob download.

404 / permission-as-404 and single-file 429 use map_google_error.
Walk 429 is not handled here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from google_drive_mcp.domain.budgets import MAX_EXPORT_SIZE
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.retrieval.ports import ExportResult

DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SLIDE_MIME = "application/vnd.google-apps.presentation"

DEFAULT_EXPORT_MIME = {
    DOC_MIME: "text/plain",
    SHEET_MIME: "text/csv",
    SLIDE_MIME: "text/plain",
}

DOWNLOADABLE_EXACT = frozenset(
    {
        "application/json",
        "application/csv",
        "text/markdown",
        "text/csv",
    }
)

# Drive often stores Markdown/MDX as application/octet-stream. Filename
# extension is the signal that the blob is usable text (FR-021).
TEXT_EXTENSION_REPRESENTATION = {
    ".md": "text/markdown",
    ".mdx": "text/markdown",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".rst": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".yml": "text/plain",
    ".yaml": "text/plain",
}

_GENERIC_BLOB_MIMES = frozenset(
    {
        "",
        "application/octet-stream",
        "application/x-octet-stream",
        "binary/octet-stream",
    }
)


class FileNotExportableError(Exception):
    """Workspace export refused with no usable prefix."""


def is_workspace(mime: str) -> bool:
    return mime in DEFAULT_EXPORT_MIME


def _extension_representation(name: str) -> str | None:
    suffix = Path(name or "").suffix.lower()
    return TEXT_EXTENSION_REPRESENTATION.get(suffix)


def is_text_blob(mime: str, name: str = "") -> bool:
    if mime.startswith("text/") or mime in DOWNLOADABLE_EXACT:
        return True
    return mime in _GENERIC_BLOB_MIMES and _extension_representation(name) is not None


def default_representation(mime: str, name: str = "") -> str | None:
    if mime in DEFAULT_EXPORT_MIME:
        return DEFAULT_EXPORT_MIME[mime]
    if mime.startswith("text/") or mime in DOWNLOADABLE_EXACT:
        return mime
    mapped = _extension_representation(name)
    if mapped and mime in _GENERIC_BLOB_MIMES:
        return mapped
    return None


def representation_for(mime: str, content_format: str | None, name: str = "") -> str:
    default = default_representation(mime, name)
    if content_format is None:
        if default is None:
            raise DomainError.of(ErrorCategory.UNSUPPORTED_MIME_TYPE)
        return default
    if default is None:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    if is_workspace(mime):
        if content_format != default:
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
        return content_format
    if is_text_blob(mime, name) and (
        content_format == mime or content_format.startswith("text/")
    ):
        return content_format
    raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)


def fetch_text(
    drive: object,
    file_id: str,
    mime_type: str,
    representation: str,
    *,
    max_bytes: int,
    request_id: str | None = None,
    name: str = "",
) -> ExportResult:
    cap = min(max_bytes, MAX_EXPORT_SIZE)
    if getattr(drive, "fail_tempfile", False):
        raise DomainError.of(ErrorCategory.TEMPORARY_STORAGE_ERROR, request_id=request_id)
    try:
        with tempfile.TemporaryDirectory(prefix="gdrive-mcp-") as tmp:
            dest = Path(tmp) / "payload"
            try:
                if is_workspace(mime_type):
                    text = drive.export(file_id, representation)
                elif is_text_blob(mime_type, name):
                    raw = drive.get_media(file_id)
                    text = raw.decode("utf-8", errors="replace")
                else:
                    raise DomainError.of(
                        ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id
                    )
            except FileNotExportableError as exc:
                raise DomainError.of(
                    ErrorCategory.FILE_NOT_EXPORTABLE, request_id=request_id
                ) from exc
            except GoogleApiError as exc:
                raise DomainError(map_google_error(exc, request_id=request_id)) from exc
            dest.write_text(text, encoding="utf-8")
            data = dest.read_bytes()
    except DomainError:
        raise
    except OSError as exc:
        raise DomainError.of(
            ErrorCategory.TEMPORARY_STORAGE_ERROR, request_id=request_id
        ) from exc

    truncated = False
    if len(data) > cap:
        if cap <= 0:
            raise DomainError.of(ErrorCategory.RESOURCE_LIMIT, request_id=request_id)
        text = data[:cap].decode("utf-8", errors="ignore")
        truncated = True
        byte_length = len(text.encode("utf-8"))
    else:
        text = data.decode("utf-8", errors="replace")
        byte_length = len(data)
    if not text and len(data) > cap:
        raise DomainError.of(ErrorCategory.RESOURCE_LIMIT, request_id=request_id)
    return ExportResult(
        text=text,
        representation=representation,
        truncated=truncated,
        byte_length=byte_length if not truncated else len(text.encode("utf-8")),
    )
