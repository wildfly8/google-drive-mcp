"""RetrievalScope and the single descendant check used by auth and walks."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

ParentLookup = Callable[[str], list[str] | None]


class RetrievalScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder_id: str | None = None
    file_ids: list[str] | None = None
    default_whole_grant: bool = False

    @model_validator(mode="after")
    def _normalize(self) -> RetrievalScope:
        ids = [i for i in (self.file_ids or []) if i]
        object.__setattr__(self, "file_ids", ids or None)
        named = bool(self.folder_id) or bool(self.file_ids)
        if self.default_whole_grant and named:
            object.__setattr__(self, "default_whole_grant", False)
        if not named:
            object.__setattr__(self, "default_whole_grant", True)
        return self

    @classmethod
    def default_whole_grant_scope(cls) -> RetrievalScope:
        return cls(default_whole_grant=True)

    @classmethod
    def from_tool_args(
        cls,
        *,
        folder_id: str | None = None,
        file_ids: list[str] | None = None,
        file_id: str | None = None,
    ) -> RetrievalScope:
        ids = list(file_ids) if file_ids else []
        if file_id:
            ids = [file_id, *[i for i in ids if i != file_id]]
        return cls(
            folder_id=folder_id or None,
            file_ids=ids or None,
            default_whole_grant=not (folder_id or ids),
        )


def apply_allowed_folder(
    arguments: MutableMapping[str, Any], allowed_folder_id: str
) -> None:
    """Narrow an omitted folder/file list to the deployment allow-list folder.

    Named folder_id / file_id / file_ids are left unchanged; the chain refuses
    those that are not this folder or a descendant.
    """
    allowed = (allowed_folder_id or "").strip()
    if not allowed:
        return
    has_files = bool(arguments.get("file_id") or arguments.get("file_ids"))
    if not arguments.get("folder_id") and not has_files:
        arguments["folder_id"] = allowed


def is_within_scope(file_id: str, scope: RetrievalScope, parent_lookup: ParentLookup) -> bool:
    """Return True if file_id is allowed by this call's scope.

    parent_lookup returns parent ids, or None if the id is unknown.
    Production uses Drive metadata; tests inject a map.
    """
    if scope.file_ids is not None:
        if file_id not in scope.file_ids:
            return False
        if not scope.folder_id:
            return True
        return _is_self_or_descendant(file_id, scope.folder_id, parent_lookup)
    if scope.folder_id:
        return _is_self_or_descendant(file_id, scope.folder_id, parent_lookup)
    return True


def _is_self_or_descendant(file_id: str, folder_id: str, parent_lookup: ParentLookup) -> bool:
    if file_id == folder_id:
        return True
    seen: set[str] = set()
    stack = [file_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        parents = parent_lookup(current)
        if parents is None:
            continue
        for parent in parents:
            if parent == folder_id:
                return True
            stack.append(parent)
    return False
