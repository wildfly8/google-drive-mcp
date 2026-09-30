"""Temporary Drive writer for files inside kb (DRIVE_WRITE_ENABLED only).

Separate from infra/google_drive, which stays read-only. Only the drive_write
and drive_trash tool bodies use it, after the kb allow-list chain has passed.
"""

from __future__ import annotations

import io

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from google_drive_mcp.infra.google_drive.client import _FIELDS, _meta, _reraise_google


class GoogleDriveWriter:
    def __init__(self, credentials: Credentials) -> None:
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def replace_text(self, file_id: str, text: str, upload_mime: str) -> dict:
        """Replace the whole body of one file with text.

        Resumable, because Drive refuses simple uploads over 5 MB and kb chat
        exports run up to 20 MB. execute() sends every chunk.
        """
        media = MediaIoBaseUpload(
            io.BytesIO(text.encode("utf-8")), mimetype=upload_mime, resumable=True
        )
        try:
            resource = (
                self._service.files()
                .update(fileId=file_id, media_body=media, fields=_FIELDS, supportsAllDrives=True)
                .execute()
            )
        except (HttpError, RefreshError) as exc:
            _reraise_google(exc)
            raise
        return _meta(resource)

    def trash(self, file_id: str) -> dict:
        """Move one file to Drive's trash (restorable for 30 days)."""
        try:
            resource = (
                self._service.files()
                .update(
                    fileId=file_id,
                    body={"trashed": True},
                    fields=_FIELDS,
                    supportsAllDrives=True,
                )
                .execute()
            )
        except (HttpError, RefreshError) as exc:
            _reraise_google(exc)
            raise
        return _meta(resource)
