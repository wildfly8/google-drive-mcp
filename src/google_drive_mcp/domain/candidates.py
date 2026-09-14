"""SearchCandidate — metadata only, never evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from google_drive_mcp.domain.drive_file import DriveFile


class SearchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: DriveFile
    reason: str
    discovery_method: Literal["find"] = "find"

    def to_wire(self) -> dict:
        return {
            "file": self.file.candidate_file_wire(),
            "reason": self.reason,
            "discovery_method": self.discovery_method,
        }
