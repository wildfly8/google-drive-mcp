"""Drive files.list `q` text. Strings are escaped; values are not logged."""

from __future__ import annotations

from google_drive_mcp.domain.drive_file import FOLDER_MIME
from google_drive_mcp.domain.list_filter import ListFilter

_PAGE_SIZE = 1000


def list_page_size() -> int:
    return _PAGE_SIZE


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def files_list_query(
    folder_id: str | None,
    filt: ListFilter | None,
    *,
    include_trashed: bool,
) -> str | None:
    parts: list[str] = []
    if folder_id:
        parts.append(f"'{_escape(folder_id)}' in parents")
    trashed = filt.include_trashed if filt is not None else include_trashed
    if not trashed:
        parts.append("trashed = false")
    if filt is not None:
        file_clauses: list[str] = []
        if filt.name_contains:
            file_clauses.append(f"name contains '{_escape(filt.name_contains)}'")
        if filt.mime_type:
            file_clauses.append(f"mimeType = '{_escape(filt.mime_type)}'")
        if filt.modified_after:
            file_clauses.append(f"modifiedTime >= '{_escape(filt.modified_after)}'")
        if filt.modified_before:
            file_clauses.append(f"modifiedTime <= '{_escape(filt.modified_before)}'")
        if file_clauses and filt.include_subfolders:
            folder = f"mimeType = '{FOLDER_MIME}'"
            parts.append(f"({folder} or ({' and '.join(file_clauses)}))")
        else:
            parts.extend(file_clauses)
    if not parts:
        return None
    return " and ".join(parts)
