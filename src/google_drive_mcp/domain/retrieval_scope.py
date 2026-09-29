"""RetrievalScope and the single descendant check used by auth and walks."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

ParentLookup = Callable[[str], list[str] | None]
SubfolderLister = Callable[[list[str]], list[Any]]


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
    those that are not this folder or a descendant. Blank ids do not count as
    named, so ``file_ids=[""]`` cannot skip the rewrite.
    """
    allowed = (allowed_folder_id or "").strip()
    if not allowed:
        return
    if not _named(arguments.get("folder_id")) and not _names_files(arguments):
        arguments["folder_id"] = allowed


def _named(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _names_files(arguments: MutableMapping[str, Any]) -> bool:
    if _named(arguments.get("file_id")):
        return True
    ids = arguments.get("file_ids")
    return isinstance(ids, list) and any(_named(i) for i in ids)


def folder_tree(root_id: str, list_subfolders: SubfolderLister) -> dict[str, list[str]]:
    """Map every folder under root_id to its parents, listed top down.

    The cost depends only on the tree under root_id, never on an id a caller
    names, so a check built on it takes the same Drive calls for an id outside
    the tree, a missing id, and an id Google does not grant.
    """
    tree: dict[str, list[str]] = {}
    known = {root_id}
    frontier = [root_id]
    while frontier:
        level = set(frontier)
        found: list[str] = []
        for item in list_subfolders(frontier):
            fid = item.get("id") if isinstance(item, Mapping) else None
            parents = list(item.get("parents") or []) if isinstance(item, Mapping) else []
            if not fid or fid in known or not level.intersection(parents):
                continue
            known.add(fid)
            tree[fid] = parents
            found.append(fid)
        frontier = found
    return tree


def is_inside_tree(
    item_id: str,
    parents: list[str],
    folder_id: str,
    tree: Mapping[str, list[str]],
) -> bool:
    """True if item_id is folder_id or lies under it.

    The ancestor walk only follows folders in ``tree`` (from folder_tree), so it
    never looks up anything outside that tree.
    """
    if item_id == folder_id:
        return True
    seen: set[str] = set()
    stack = list(parents)
    while stack:
        current = stack.pop()
        if current == folder_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(tree.get(current, ()))
    return False


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
