"""Ephemeral document content. Not a cache key."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DocumentContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1)
    mime_type: str
    representation: str
    content: str
    retrieved_at: str
    byte_length: int
