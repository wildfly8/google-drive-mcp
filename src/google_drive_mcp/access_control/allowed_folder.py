"""Startup check that the allow-list names one ordinary Drive folder."""

from __future__ import annotations

from google_drive_mcp.domain.drive_file import FOLDER_MIME
from google_drive_mcp.domain.google_errors import GoogleApiError


def check_allowed_folder(drive: object, folder_id: str) -> None:
    """Raise ValueError unless folder_id is a folder below a Drive root.

    My Drive root and shared-drive roots have no parent, so this refuses them
    even when they are named by their real id rather than by an alias.
    """
    try:
        meta = drive.get_metadata(folder_id)
        root_id = drive.get_metadata("root").get("id")
    except GoogleApiError as exc:
        raise ValueError(
            f"DRIVE_ALLOWED_FOLDER_ID could not be read from Drive (HTTP {exc.status})."
        ) from None
    if meta.get("mime_type") != FOLDER_MIME:
        raise ValueError("DRIVE_ALLOWED_FOLDER_ID is not a folder.")
    if not meta.get("parents") or root_id in {folder_id, meta.get("id")}:
        raise ValueError("DRIVE_ALLOWED_FOLDER_ID is a Drive root, not one folder under it.")
    if meta.get("trashed"):
        raise ValueError("DRIVE_ALLOWED_FOLDER_ID is in the trash.")
