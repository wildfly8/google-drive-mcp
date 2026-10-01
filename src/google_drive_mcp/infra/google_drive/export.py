"""Export / download adapter. Workspace export map + text blob download.

404 / permission-as-404 and single-file 429 use map_google_error.
Walk 429 is not handled here.
"""

from __future__ import annotations

import threading
from pathlib import Path

from google_drive_mcp.domain.budgets import GREP_PREFETCH_MAX_FILE_BYTES, MAX_EXPORT_SIZE
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.retrieval.ports import ExportResult

# A download over LARGE_DOWNLOAD_BYTES, or of unknown size, holds one of
# LARGE_DOWNLOAD_SLOTS process-wide slots, so a few 20 MB reads at once cannot
# run the instance out of memory. drive_grep fetches ahead only smaller files,
# so those never wait. A download that gets no slot in time is RATE_LIMITED.
LARGE_DOWNLOAD_BYTES = GREP_PREFETCH_MAX_FILE_BYTES
LARGE_DOWNLOAD_SLOTS = 2
LARGE_DOWNLOAD_WAIT_SECONDS = 10.0
_large_downloads = threading.BoundedSemaphore(LARGE_DOWNLOAD_SLOTS)

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
    # Text files are returned as stored, never converted, so only their own type
    # (or plain text) describes the bytes truthfully.
    if is_text_blob(mime, name) and content_format in {mime, default, "text/plain"}:
        return content_format
    raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)


def _download(
    drive: object, file_id: str, mime_type: str, representation: str, request_id: str | None
) -> str:
    try:
        if is_workspace(mime_type):
            return drive.export(file_id, representation)
        # Decode at once so the raw bytes are freed.
        return drive.get_media(file_id).decode("utf-8", errors="replace")
    except FileNotExportableError as exc:
        raise DomainError.of(ErrorCategory.FILE_NOT_EXPORTABLE, request_id=request_id) from exc
    except GoogleApiError as exc:
        raise DomainError(map_google_error(exc, request_id=request_id)) from exc
    except OSError as exc:
        # A socket timeout or reset: the Drive client gives up after 20 s.
        raise DomainError.of(ErrorCategory.DRIVE_API_ERROR, request_id=request_id) from exc


def fetch_text(
    drive: object,
    file_id: str,
    mime_type: str,
    representation: str,
    *,
    max_bytes: int,
    request_id: str | None = None,
    name: str = "",
    size: int | None = None,
) -> ExportResult:
    """Text of one file, at most min(max_bytes, MAX_EXPORT_SIZE) UTF-8 bytes.

    size is Drive's size for the file when known. It decides whether the
    download needs a large-download slot; a Workspace export is always large.
    """
    cap = min(max_bytes, MAX_EXPORT_SIZE)
    if not is_workspace(mime_type) and not is_text_blob(mime_type, name):
        raise DomainError.of(ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id)
    # Drive's size for a Doc, Sheet or Slides file is not the length of its export.
    large = is_workspace(mime_type) or size is None or size > LARGE_DOWNLOAD_BYTES
    if large and not _large_downloads.acquire(timeout=LARGE_DOWNLOAD_WAIT_SECONDS):
        raise DomainError.of(ErrorCategory.RATE_LIMITED, request_id=request_id)
    try:
        # In memory only: Cloud Run's /tmp is RAM too, so a temp file would be one more copy.
        text = _download(drive, file_id, mime_type, representation, request_id)
        data = text.encode("utf-8")
        if len(data) <= cap:
            return ExportResult(
                text=text, representation=representation, truncated=False, byte_length=len(data)
            )
        # Free the whole text before decoding the prefix.
        del text
        if cap <= 0:
            raise DomainError.of(ErrorCategory.RESOURCE_LIMIT, request_id=request_id)
        text = data[:cap].decode("utf-8", errors="ignore")
        del data
        if not text:
            raise DomainError.of(ErrorCategory.RESOURCE_LIMIT, request_id=request_id)
        return ExportResult(
            text=text,
            representation=representation,
            truncated=True,
            byte_length=len(text.encode("utf-8")),
        )
    finally:
        if large:
            _large_downloads.release()
