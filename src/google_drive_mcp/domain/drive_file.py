"""DriveFile domain model. Wire view-link field is source_url."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    mime_type: str
    parents: list[str] = Field(default_factory=list)
    modified_time: str
    created_time: str | None = None
    web_view_link: str | None = None
    size: int | None = None
    owners: list[str] | None = None
    trashed: bool = False

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME

    @property
    def source_url(self) -> str:
        return self.web_view_link or f"https://drive.google.com/file/d/{self.id}/view"

    def child_wire(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "is_folder": self.is_folder,
            "modified_time": self.modified_time,
            "source_url": self.source_url,
        }

    def candidate_file_wire(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "modified_time": self.modified_time,
            "source_url": self.source_url,
            "is_folder": self.is_folder,
            "trashed": self.trashed,
        }

    @classmethod
    def from_metadata(cls, data: dict) -> DriveFile:
        link = data.get("web_view_link") or data.get("webViewLink") or data.get("source_url")
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            mime_type=data.get("mime_type") or data.get("mimeType") or "",
            parents=list(data.get("parents") or []),
            modified_time=data.get("modified_time") or data.get("modifiedTime") or "",
            created_time=data.get("created_time") or data.get("createdTime"),
            web_view_link=link,
            size=data.get("size"),
            owners=data.get("owners"),
            trashed=bool(data.get("trashed", False)),
        )
