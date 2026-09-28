"""Metadata filters pushed into Drive files.list. Not a content index."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListFilter:
    name_contains: str | None = None
    mime_type: str | None = None
    modified_after: str | None = None
    modified_before: str | None = None
    include_trashed: bool = False
    include_subfolders: bool = False
