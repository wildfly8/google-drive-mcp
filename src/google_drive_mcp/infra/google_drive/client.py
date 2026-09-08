"""Production Drive v3 adapter (read-only: get / list / export / media)."""

from __future__ import annotations

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.infra.google_drive.export import FileNotExportableError

_FIELDS = "id,name,mimeType,parents,modifiedTime,createdTime,webViewLink,size,trashed"


def _status(exc: HttpError) -> int:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status:
        return status
    resp = getattr(exc, "resp", None)
    if resp is not None:
        return int(getattr(resp, "status", 500) or 500)
    return 500


def _meta(resource: dict) -> dict:
    return {
        "id": resource["id"],
        "name": resource.get("name", ""),
        "mime_type": resource.get("mimeType", ""),
        "parents": list(resource.get("parents") or []),
        "modified_time": resource.get("modifiedTime", ""),
        "created_time": resource.get("createdTime"),
        "web_view_link": resource.get("webViewLink"),
        "size": int(resource["size"]) if resource.get("size") else None,
        "trashed": bool(resource.get("trashed", False)),
    }


class GoogleDriveClient:
    """Read-only Drive client. No mutating files() methods."""

    def __init__(self, credentials: Credentials) -> None:
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.metadata_get_count = 0
        self.content_export_count = 0
        self.content_media_count = 0

    @property
    def content_count(self) -> int:
        return self.content_export_count + self.content_media_count

    def get_metadata(self, file_id: str) -> dict:
        self.metadata_get_count += 1
        try:
            resource = (
                self._service.files()
                .get(fileId=file_id, fields=_FIELDS, supportsAllDrives=True)
                .execute()
            )
        except HttpError as exc:
            raise GoogleApiError(_status(exc)) from exc
        return _meta(resource)

    def parent_lookup(self, file_id: str) -> list[str] | None:
        try:
            meta = self.get_metadata(file_id)
        except GoogleApiError as exc:
            if exc.status in (404, 403):
                return None
            raise
        return list(meta.get("parents") or [])

    def list_children(self, folder_id: str) -> list[dict]:
        query = f"'{folder_id}' in parents and trashed = false"
        return self._list(query)

    def list_all(self, *, include_trashed: bool = False) -> list[dict]:
        query = "trashed = false" if not include_trashed else None
        return self._list(query)

    def _list(self, query: str | None) -> list[dict]:
        items: list[dict] = []
        page_token = None
        try:
            while True:
                kwargs = {
                    "q": query,
                    "fields": f"nextPageToken, files({_FIELDS})",
                    "pageSize": 100,
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                if query is None:
                    kwargs.pop("q")
                response = self._service.files().list(**kwargs).execute()
                for resource in response.get("files", []):
                    items.append(_meta(resource))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as exc:
            raise GoogleApiError(_status(exc)) from exc
        return items

    def export(self, file_id: str, mime: str) -> str:
        self.content_export_count += 1
        try:
            data = (
                self._service.files()
                .export(fileId=file_id, mimeType=mime)
                .execute()
            )
        except HttpError as exc:
            status = _status(exc)
            body = str(exc).lower()
            if status == 403 and "export" in body:
                raise FileNotExportableError(file_id) from exc
            raise GoogleApiError(status) from exc
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    def get_media(self, file_id: str) -> bytes:
        self.content_media_count += 1
        try:
            data = self._service.files().get_media(fileId=file_id).execute()
        except HttpError as exc:
            raise GoogleApiError(_status(exc)) from exc
        if isinstance(data, bytes):
            return data
        return str(data).encode("utf-8")
