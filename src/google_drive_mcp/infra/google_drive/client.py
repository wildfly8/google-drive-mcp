"""Production Drive v3 adapter (read-only: get / list / export / media)."""

from __future__ import annotations

import threading

import google_auth_httplib2
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import build_http

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.domain.list_filter import ListFilter
from google_drive_mcp.infra.google_drive.export import FileNotExportableError
from google_drive_mcp.infra.google_drive.query import (
    files_list_query,
    list_page_size,
    subfolders_query,
)

_FIELDS = "id,name,mimeType,parents,modifiedTime,createdTime,webViewLink,size,trashed"
_PARENTS_PER_QUERY = 40


def _reraise_google(exc: BaseException) -> None:
    if isinstance(exc, RefreshError):
        raise GoogleApiError(401, "refresh_failed") from exc
    if isinstance(exc, HttpError):
        raise GoogleApiError(_status(exc)) from exc
    raise exc


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
        self._credentials = credentials
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self._local = threading.local()
        self.metadata_get_count = 0
        self.content_export_count = 0
        self.content_media_count = 0
        self.list_time_exceeded = False

    def _http(self) -> google_auth_httplib2.AuthorizedHttp:
        """This thread's authorized connection.

        httplib2.Http is not thread-safe, and drive_grep downloads small files on
        worker threads, so every request runs on a connection owned by its thread.
        """
        http = getattr(self._local, "http", None)
        if http is None:
            http = google_auth_httplib2.AuthorizedHttp(self._credentials, http=build_http())
            self._local.http = http
        return http

    @property
    def content_count(self) -> int:
        return self.content_export_count + self.content_media_count

    def get_metadata(self, file_id: str) -> dict:
        self.metadata_get_count += 1
        try:
            resource = (
                self._service.files()
                .get(fileId=file_id, fields=_FIELDS, supportsAllDrives=True)
                .execute(http=self._http())
            )
        except (HttpError, RefreshError) as exc:
            _reraise_google(exc)
            raise
        return _meta(resource)

    def parent_lookup(self, file_id: str) -> list[str] | None:
        try:
            meta = self.get_metadata(file_id)
        except GoogleApiError as exc:
            if exc.status in (404, 403):
                return None
            raise
        return list(meta.get("parents") or [])

    def list_children(
        self,
        folder_id: str,
        budget: Budget | None = None,
        *,
        include_trashed: bool = False,
        list_filter: ListFilter | None = None,
    ) -> list[dict]:
        if not folder_id:
            # A files.list without a parent clause would list the whole grant.
            raise ValueError("list_children requires a folder_id")
        query = files_list_query(folder_id, list_filter, include_trashed=include_trashed)
        return self._list(query, budget=budget)

    def list_subfolders(self, parent_ids: list[str]) -> list[dict]:
        """Folders (trashed included) whose parents include any of parent_ids."""
        items: list[dict] = []
        ids = [pid for pid in parent_ids if pid]
        for start in range(0, len(ids), _PARENTS_PER_QUERY):
            chunk = ids[start : start + _PARENTS_PER_QUERY]
            items.extend(self._list(subfolders_query(chunk)))
        return items

    def _list(self, query: str, budget: Budget | None = None) -> list[dict]:
        items: list[dict] = []
        page_token = None
        self.list_time_exceeded = False
        try:
            while True:
                if budget is not None and budget.time_exceeded():
                    self.list_time_exceeded = True
                    break
                kwargs = {
                    "q": query,
                    "fields": f"nextPageToken, files({_FIELDS})",
                    "pageSize": list_page_size(),
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                response = self._service.files().list(**kwargs).execute(http=self._http())
                for resource in response.get("files", []):
                    items.append(_meta(resource))
                    if budget is not None and budget.time_exceeded():
                        self.list_time_exceeded = True
                        return items
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except (HttpError, RefreshError) as exc:
            _reraise_google(exc)
            raise
        return items

    def export(self, file_id: str, mime: str) -> str:
        self.content_export_count += 1
        try:
            data = (
                self._service.files()
                .export(fileId=file_id, mimeType=mime)
                .execute(http=self._http())
            )
        except RefreshError as exc:
            _reraise_google(exc)
            raise
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
            data = self._service.files().get_media(fileId=file_id).execute(http=self._http())
        except (HttpError, RefreshError) as exc:
            _reraise_google(exc)
            raise
        if isinstance(data, bytes):
            return data
        return str(data).encode("utf-8")
