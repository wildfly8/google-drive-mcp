"""Drive list adapter: immediate children and descendant walks via is_within_scope.

Every listing is bounded to one named folder. There is no whole-grant listing,
and a listed child whose parents do not include the listed folder is dropped.
Walk HTTP 429 is completeness (PARTIAL), not map_google_error RATE_LIMITED.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.domain.list_filter import ListFilter
from google_drive_mcp.domain.retrieval_scope import RetrievalScope, is_within_scope


@dataclass
class WalkResult:
    files: list[DriveFile] = field(default_factory=list)
    next_page_token: str | None = None
    rate_limited: bool = False
    truncated: bool = False
    more: bool = False
    time_exceeded: bool = False


def _as_file(item: object) -> DriveFile:
    if isinstance(item, DriveFile):
        return item
    if hasattr(item, "metadata_dict"):
        return DriveFile.from_metadata(item.metadata_dict())
    if isinstance(item, dict):
        return DriveFile.from_metadata(item)
    raise TypeError(f"unsupported list item {type(item)}")


def _parent_lookup(drive: object) -> object:
    return drive.parent_lookup


def _children_of(folder_id: str, items: list) -> list[DriveFile]:
    """Keep listed items that really are children of folder_id.

    files.list is answered from Drive's search index; checking the parents it
    returned keeps a stale or over-broad entry out of the result.
    """
    files = [_as_file(item) for item in items]
    return [f for f in files if folder_id in f.parents]


def immediate_children(
    drive: object,
    folder_id: str,
    *,
    page_token: str | None = None,
    page_size: int = 40,
    request_id: str | None = None,
) -> WalkResult:
    try:
        raw = drive.list_children(folder_id)
    except GoogleApiError as exc:
        if exc.status == 429:
            return WalkResult(rate_limited=True)
        raise DomainError(map_google_error(exc, request_id=request_id)) from exc
    files = _children_of(folder_id, raw)
    start = 0
    if page_token:
        try:
            start = int(page_token)
        except (TypeError, ValueError) as exc:
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT, request_id=request_id) from exc
    if start < 0:
        start = 0
    page = files[start : start + page_size]
    end = start + len(page)
    more = end < len(files)
    return WalkResult(
        files=page,
        next_page_token=str(end) if more else None,
        more=more,
        truncated=more,
    )


def walk_files(
    drive: object,
    scope: RetrievalScope,
    budget: Budget,
    *,
    include_trashed: bool = False,
    include_folders: bool = True,
    list_filter: ListFilter | None = None,
    honor_file_cap: bool = True,
    count_folders: bool = True,
    count_listed: bool = True,
    request_id: str | None = None,
) -> WalkResult:
    """BFS descendants (folder scope) or the named files. Never the whole grant.

    Children returned by listing a folder are already inside that folder, so
    the walk does not fetch each child's parents. ``honor_file_cap`` false
    keeps listing until time runs out so a later pass can order by size.
    Folder nodes do not consume ``max_files`` when ``count_folders`` is false.
    ``count_listed`` false leaves the file budget for the caller (grep scans
    a size-ordered subset of a finished listing).
    """
    result = WalkResult()
    lookup = _parent_lookup(drive)

    def consider(file: DriveFile, *, trust: bool) -> None:
        if file.trashed and not include_trashed:
            return
        if not trust and not is_within_scope(file.id, scope, lookup):
            return
        if file.is_folder and not include_folders:
            return
        counts = count_folders or not file.is_folder
        if budget.time_exceeded():
            # An in-scope file left out for time is a cut listing, even when it
            # is the last one (the loops only check time before the next item).
            result.time_exceeded = True
            return
        if honor_file_cap and counts and budget.files_exhausted():
            return
        result.files.append(file)
        if count_listed and counts:
            budget.note_file()

    try:
        if scope.file_ids:
            for fid in scope.file_ids:
                if budget.time_exceeded():
                    result.time_exceeded = True
                    break
                if honor_file_cap and budget.files_exhausted():
                    result.truncated = True
                    break
                meta = drive.get_metadata(fid)
                consider(_as_file(meta), trust=False)
            return result

        if scope.folder_id:
            queue: deque[str] = deque([scope.folder_id])
            seen: set[str] = set()
            while queue:
                if budget.time_exceeded():
                    result.time_exceeded = True
                    break
                if honor_file_cap and budget.files_exhausted():
                    result.truncated = True
                    break
                folder = queue.popleft()
                if folder in seen:
                    continue
                seen.add(folder)
                children = _children_of(
                    folder,
                    drive.list_children(
                        folder_id=folder,
                        budget=budget,
                        include_trashed=include_trashed,
                        list_filter=list_filter,
                    ),
                )
                if getattr(drive, "list_time_exceeded", False):
                    result.time_exceeded = True
                for index, child in enumerate(children):
                    if child.is_folder:
                        queue.append(child.id)
                    consider(child, trust=True)
                    if honor_file_cap and budget.files_exhausted():
                        if index + 1 < len(children) or queue:
                            result.truncated = True
                        break
                    if budget.time_exceeded():
                        result.time_exceeded = True
                        break
                if result.time_exceeded:
                    break
            return result

        # Unscoped: the whole Google grant is never listed.
        raise DomainError.of(ErrorCategory.AUTHORIZATION_ERROR, request_id=request_id)
    except GoogleApiError as exc:
        if exc.status == 429:
            result.rate_limited = True
            return result
        raise DomainError(map_google_error(exc, request_id=request_id)) from exc
