"""Drive list adapter: immediate children and descendant walks via is_within_scope.

Walk HTTP 429 is completeness (PARTIAL), not map_google_error RATE_LIMITED.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
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
    files = [_as_file(item) for item in raw]
    start = int(page_token) if page_token else 0
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
    request_id: str | None = None,
) -> WalkResult:
    """BFS descendants (folder scope) or whole-grant listing. Uses is_within_scope."""
    result = WalkResult()
    lookup = _parent_lookup(drive)

    def consider(file: DriveFile) -> None:
        if file.trashed and not include_trashed:
            return
        if not is_within_scope(file.id, scope, lookup):
            return
        if budget.files_exhausted() or budget.time_exceeded():
            return
        result.files.append(file)
        budget.note_file()

    try:
        if scope.file_ids:
            for fid in scope.file_ids:
                if budget.time_exceeded():
                    result.time_exceeded = True
                    break
                if budget.files_exhausted():
                    result.truncated = True
                    break
                meta = drive.get_metadata(fid)
                consider(_as_file(meta))
            return result

        if scope.folder_id:
            queue: deque[str] = deque([scope.folder_id])
            seen: set[str] = set()
            while queue:
                if budget.time_exceeded():
                    result.time_exceeded = True
                    break
                if budget.files_exhausted():
                    result.truncated = True
                    break
                folder = queue.popleft()
                if folder in seen:
                    continue
                seen.add(folder)
                children = [_as_file(i) for i in drive.list_children(folder_id=folder)]
                for child in children:
                    if child.is_folder:
                        queue.append(child.id)
                    consider(child)
                    if budget.files_exhausted():
                        result.truncated = True
                        break
                    if budget.time_exceeded():
                        result.time_exceeded = True
                        break
            return result

        raw = drive.list_all(include_trashed=include_trashed)
        for item in raw:
            if budget.time_exceeded():
                result.time_exceeded = True
                break
            if budget.files_exhausted():
                result.truncated = True
                break
            consider(_as_file(item))
        if budget.files_exhausted() and len(result.files) < len(raw):
            result.truncated = True
        return result
    except GoogleApiError as exc:
        if exc.status == 429:
            result.rate_limited = True
            return result
        raise DomainError(map_google_error(exc, request_id=request_id)) from exc
