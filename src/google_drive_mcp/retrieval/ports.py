"""Drive ports — no Google client types."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ExportResult:
    __slots__ = ("text", "representation", "truncated", "byte_length")

    def __init__(
        self,
        text: str,
        representation: str,
        truncated: bool,
        byte_length: int,
    ) -> None:
        self.text = text
        self.representation = representation
        self.truncated = truncated
        self.byte_length = byte_length


@runtime_checkable
class DrivePort(Protocol):
    metadata_get_count: int
    content_count: int

    def get_metadata(self, file_id: str) -> dict: ...

    def parent_lookup(self, file_id: str) -> list[str] | None: ...

    def list_children(self, folder_id: str) -> list: ...

    def list_all(self, *, include_trashed: bool = False) -> list: ...

    def export(self, file_id: str, mime: str) -> str: ...

    def get_media(self, file_id: str) -> bytes: ...
