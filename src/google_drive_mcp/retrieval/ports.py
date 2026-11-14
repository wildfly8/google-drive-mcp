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
    """What the retrieval code needs from Drive.

    A port may also set ``parallel_listing`` (a walk then lists folders side by side,
    so its calls must be safe to run on several threads at once), and may return a
    listing with a ``time_exceeded`` attribute that says whether the time cap cut that
    listing short; without one the shared ``list_time_exceeded`` flag is read.
    """

    metadata_get_count: int
    content_count: int

    def get_metadata(self, file_id: str) -> dict: ...

    def parent_lookup(self, file_id: str) -> list[str] | None: ...

    def list_children(
        self,
        folder_id: str,
        budget: object | None = None,
        *,
        include_trashed: bool = False,
        list_filter: object | None = None,
    ) -> list: ...

    def list_subfolders(self, parent_ids: list[str]) -> list: ...

    def export(self, file_id: str, mime: str) -> str: ...

    def get_media(self, file_id: str) -> bytes: ...
