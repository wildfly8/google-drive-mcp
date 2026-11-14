"""One tool call's view of the Drive client: a repeated metadata get is answered from memory."""

from __future__ import annotations

import threading
from typing import Any

from google_drive_mcp.domain.google_errors import GoogleApiError


class MemoDrive:
    """Wraps a Drive port for the length of one tool call.

    The access check and the tool both need a named file's metadata, and without this
    each asks Drive for it: two round trips of about 0.2 s per file id. The memo is
    built by ``Runtime.bind_request_drive`` for every call and dropped with it, so
    nothing is kept between requests (Article III). Only a successful get is
    remembered, so an error is raised again for every caller that hits it. Everything
    else passes straight through to the wrapped client.
    """

    def __init__(self, drive: Any) -> None:
        self._drive = drive
        self._metadata: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get_metadata(self, file_id: str) -> dict:
        with self._lock:
            hit = self._metadata.get(file_id)
        if hit is None:
            hit = self._drive.get_metadata(file_id)
            with self._lock:
                self._metadata[file_id] = hit
        return dict(hit)

    def parent_lookup(self, file_id: str) -> list[str] | None:
        """Parent ids, or None for an id Drive does not know or does not grant."""
        try:
            meta = self.get_metadata(file_id)
        except GoogleApiError as exc:
            if exc.status in (404, 403):
                return None
            raise
        return list(meta.get("parents") or [])

    def __getattr__(self, name: str) -> Any:
        # Only reached for names this class does not define.
        if name in ("_drive", "_metadata", "_lock"):  # not built yet: do not recurse
            raise AttributeError(name)
        return getattr(self._drive, name)
