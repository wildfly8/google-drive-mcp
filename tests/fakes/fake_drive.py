"""In-memory Drive port with separate metadata vs content invocation counters.

Retrieval Core populates the store; Access Control spies on the same object.
Do not add a second fake module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.infra.google_drive.export import FileNotExportableError

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SLIDE_MIME = "application/vnd.google-apps.presentation"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class FakeFile:
    id: str
    name: str
    mime_type: str
    parents: list[str] = field(default_factory=list)
    modified_time: str = field(default_factory=_now)
    created_time: str | None = None
    content: str | bytes = ""
    web_view_link: str | None = None
    trashed: bool = False
    exportable: bool = True

    def __post_init__(self) -> None:
        if not self.web_view_link:
            self.web_view_link = f"https://drive.google.com/file/d/{self.id}/view"

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME

    def metadata_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "parents": list(self.parents),
            "modified_time": self.modified_time,
            "created_time": self.created_time,
            "web_view_link": self.web_view_link,
            "source_url": self.web_view_link,
            "trashed": self.trashed,
            "is_folder": self.is_folder,
            "size": len(self.content) if isinstance(self.content, (str, bytes)) else None,
        }


class FakeDrive:
    """Single fake Drive port. Metadata gets ≠ content export/get_media."""

    def __init__(self) -> None:
        self.files: dict[str, FakeFile] = {}
        self.metadata_get_count = 0
        self.content_export_count = 0
        self.content_media_count = 0
        self.list_count = 0
        self.rate_limit_lists_after: int | None = None
        self.rate_limit_export: bool = False
        self.fail_tempfile: bool = False
        self.list_time_exceeded: bool = False

    @property
    def content_count(self) -> int:
        return self.content_export_count + self.content_media_count

    def reset_counters(self) -> None:
        self.metadata_get_count = 0
        self.content_export_count = 0
        self.content_media_count = 0
        self.list_count = 0

    def add(self, file: FakeFile) -> FakeFile:
        self.files[file.id] = file
        return file

    def parent_lookup(self, file_id: str) -> list[str] | None:
        item = self.files.get(file_id)
        if item is None:
            return None
        return list(item.parents)

    def get_metadata(self, file_id: str) -> dict:
        self.metadata_get_count += 1
        item = self.files.get(file_id)
        if item is None:
            raise GoogleApiError(404)
        return item.metadata_dict()

    def list_children(self, folder_id: str, budget=None) -> list[FakeFile]:
        self.list_count += 1
        if self.rate_limit_lists_after is not None and self.list_count > self.rate_limit_lists_after:
            raise GoogleApiError(429)
        if folder_id not in self.files and folder_id != "root":
            raise GoogleApiError(404)
        return [
            f
            for f in self.files.values()
            if folder_id in f.parents and not f.trashed
        ]

    def list_all(self, *, include_trashed: bool = False, budget=None) -> list[FakeFile]:
        self.list_count += 1
        if self.rate_limit_lists_after is not None and self.list_count > self.rate_limit_lists_after:
            raise GoogleApiError(429)
        return [
            f
            for f in self.files.values()
            if f.id != "root" and (include_trashed or not f.trashed)
        ]

    def export(self, file_id: str, mime: str) -> str:
        self.content_export_count += 1
        if self.rate_limit_export:
            raise GoogleApiError(429)
        item = self.files.get(file_id)
        if item is None:
            raise GoogleApiError(404)
        if not item.exportable:
            raise FileNotExportableError(file_id)
        if isinstance(item.content, bytes):
            return item.content.decode("utf-8", errors="replace")
        return str(item.content)

    def get_media(self, file_id: str) -> bytes:
        self.content_media_count += 1
        if self.rate_limit_export:
            raise GoogleApiError(429)
        item = self.files.get(file_id)
        if item is None:
            raise GoogleApiError(404)
        if isinstance(item.content, bytes):
            return item.content
        return str(item.content).encode("utf-8")

    def update_content(self, file_id: str, content: str, *, modified_time: str | None = None) -> None:
        item = self.files[file_id]
        item.content = content
        item.modified_time = modified_time or _now()

    @classmethod
    def sample(cls) -> FakeDrive:
        """Fixture used by retrieval contract tests and the AC AUTH graph."""
        drive = cls()
        drive.add(
            FakeFile(
                id="root",
                name="My Drive",
                mime_type=FOLDER_MIME,
                parents=[],
            )
        )
        drive.add(
            FakeFile(
                id="folder-a",
                name="Project",
                mime_type=FOLDER_MIME,
                parents=["root"],
            )
        )
        drive.add(
            FakeFile(
                id="nested-doc",
                name="Notes",
                mime_type=DOC_MIME,
                parents=["folder-a"],
                content="alpha idempotency\nbeta idempotency extra",
            )
        )
        drive.add(
            FakeFile(
                id="nested-sheet",
                name="Budget",
                mime_type=SHEET_MIME,
                parents=["folder-a"],
                content="item,amount\nwidgets,10",
            )
        )
        drive.add(
            FakeFile(
                id="nested-slide",
                name="Deck",
                mime_type=SLIDE_MIME,
                parents=["folder-a"],
                content="Quarterly update idempotency",
            )
        )
        drive.add(
            FakeFile(
                id="text-file",
                name="readme.txt",
                mime_type="text/plain",
                parents=["folder-a"],
                content="plain text notes\n",
            )
        )
        drive.add(
            FakeFile(
                id="binary-file",
                name="photo.bin",
                mime_type="application/octet-stream",
                parents=["folder-a"],
                content=b"\x00\x01\x02\xff",
            )
        )
        drive.add(
            FakeFile(
                id="outside-doc",
                name="Other",
                mime_type=DOC_MIME,
                parents=["root"],
                content="secret other folder text",
            )
        )
        return drive
