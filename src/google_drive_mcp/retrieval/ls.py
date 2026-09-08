"""drive_ls: immediate children of a folder (or My Drive root)."""

from __future__ import annotations

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.operation import OperationStatus, PartialReason
from google_drive_mcp.infra.google_drive.list import immediate_children


def drive_ls(
    drive: object,
    *,
    folder_id: str | None = None,
    max_results: int | None = None,
    page_token: str | None = None,
    budget: Budget | None = None,
    request_id: str | None = None,
) -> dict:
    budget = budget or Budget()
    page_size = max_results if max_results is not None else budget.max_files
    target = folder_id or "root"
    if budget.time_exceeded():
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.max_execution_time.value,
            "children": [],
        }
    walk = immediate_children(
        drive,
        target,
        page_token=page_token,
        page_size=page_size,
        request_id=request_id,
    )
    children = [f.child_wire() for f in walk.files]
    if walk.rate_limited:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.RATE_LIMITED.value,
            "children": children,
        }
    if not children and not walk.more and not page_token:
        return {"status": OperationStatus.EMPTY.value, "children": []}
    if walk.more or walk.truncated:
        out = {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.pagination.value,
            "children": children,
        }
        if walk.next_page_token:
            out["next_page_token"] = walk.next_page_token
        return out
    if budget.time_exceeded():
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.max_execution_time.value,
            "children": children,
        }
    return {"status": OperationStatus.COMPLETE.value, "children": children}


def validate_ls_args(arguments: dict) -> None:
    max_results = arguments.get("max_results")
    if max_results is not None and (
        not isinstance(max_results, int) or max_results < 1 or max_results > 40
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    folder_id = arguments.get("folder_id")
    if folder_id is not None:
        from google_drive_mcp.mcp.validation import require_file_id

        require_file_id(folder_id)
