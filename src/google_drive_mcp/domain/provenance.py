"""Provenance required on content-derived results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_id: str = Field(min_length=1)
    file_name: str
    mime_type: str
    modified_time: str
    source_url: str
    retrieved_at: str
    matched_text: str | None = None
    location: dict | None = None

    def read_fields(self) -> dict:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "modified_time": self.modified_time,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
        }
