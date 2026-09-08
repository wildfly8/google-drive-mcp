"""drive_find: recursive candidate discovery (not evidence)."""

from __future__ import annotations

from datetime import datetime

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.candidates import SearchCandidate
from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.operation import OperationStatus, PartialReason
from google_drive_mcp.domain.retrieval_scope import RetrievalScope
from google_drive_mcp.infra.google_drive.list import walk_files


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT) from exc


def _matches(
    file: DriveFile,
    *,
    name_pattern: str | None,
    mime_type: str | None,
    modified_after: datetime | None,
    modified_before: datetime | None,
    include_trashed: bool,
) -> str | None:
    if file.trashed and not include_trashed:
        return None
    if name_pattern and name_pattern.lower() not in file.name.lower():
        return None
    if mime_type and file.mime_type != mime_type:
        return None
    if modified_after or modified_before:
        try:
            mt = datetime.fromisoformat(file.modified_time.replace("Z", "+00:00"))
        except ValueError:
            return None
        if modified_after and mt < modified_after:
            return None
        if modified_before and mt > modified_before:
            return None
    if name_pattern:
        return "name match"
    if mime_type:
        return "mime filter"
    return "folder descendant" if file.parents else "grant listing"


def drive_find(
    drive: object,
    *,
    name_pattern: str | None = None,
    mime_type: str | None = None,
    folder_id: str | None = None,
    modified_after: str | None = None,
    modified_before: str | None = None,
    trashed: bool = False,
    max_results: int | None = None,
    budget: Budget | None = None,
    request_id: str | None = None,
) -> dict:
    budget = budget or Budget()
    if max_results is not None:
        budget.max_files = min(budget.max_files, max_results)
    after = _parse_dt(modified_after)
    before = _parse_dt(modified_before)
    scope = RetrievalScope.from_tool_args(folder_id=folder_id)
    walk = walk_files(
        drive, scope, budget, include_trashed=trashed, request_id=request_id
    )
    candidates: list[SearchCandidate] = []
    for file in walk.files:
        reason = _matches(
            file,
            name_pattern=name_pattern,
            mime_type=mime_type,
            modified_after=after,
            modified_before=before,
            include_trashed=trashed,
        )
        if reason is None:
            continue
        candidates.append(SearchCandidate(file=file, reason=reason))
        if len(candidates) >= budget.max_files:
            walk.truncated = True
            break

    payload = [c.to_wire() for c in candidates]
    if walk.rate_limited:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.RATE_LIMITED.value,
            "candidates": payload,
        }
    if walk.time_exceeded:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.max_execution_time.value,
            "candidates": payload,
        }
    if walk.truncated:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.max_files.value,
            "candidates": payload,
        }
    if not payload:
        return {"status": OperationStatus.EMPTY.value, "candidates": []}
    return {"status": OperationStatus.COMPLETE.value, "candidates": payload}


def validate_find_args(arguments: dict) -> None:
    max_results = arguments.get("max_results")
    if max_results is not None and (
        not isinstance(max_results, int) or max_results < 1 or max_results > 40
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    for key in ("modified_after", "modified_before"):
        if arguments.get(key):
            _parse_dt(arguments[key])
    folder_id = arguments.get("folder_id")
    if folder_id is not None:
        from google_drive_mcp.mcp.validation import require_file_id

        require_file_id(folder_id)
