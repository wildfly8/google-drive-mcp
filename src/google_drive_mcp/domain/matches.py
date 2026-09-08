"""SearchMatch — evidence role when provenance is present."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SearchMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_id: str = Field(min_length=1)
    file_name: str
    mime_type: str
    modified_time: str
    source_url: str
    retrieved_at: str
    pattern: str
    matched_text: str
    location: dict
    context: str | None = None

    def to_wire(self) -> dict:
        data = {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "modified_time": self.modified_time,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "pattern": self.pattern,
            "matched_text": self.matched_text,
            "location": self.location,
        }
        if self.context is not None:
            data["context"] = self.context
        return data
