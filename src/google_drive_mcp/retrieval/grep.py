"""drive_grep: fetch → exact search → provenance → discard bytes.

No module-level file_id→bytes cache. Walk and multi-target export 429 → PARTIAL RATE_LIMITED.
"""

from __future__ import annotations

from datetime import UTC, datetime

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.matches import SearchMatch
from google_drive_mcp.domain.operation import OperationStatus, PartialReason
from google_drive_mcp.domain.retrieval_scope import RetrievalScope
from google_drive_mcp.infra.exact_search.regex import compile_pattern, search_text
from google_drive_mcp.infra.google_drive.export import (
    SHEET_MIME,
    SLIDE_MIME,
    default_representation,
    fetch_text,
    representation_for,
)
from google_drive_mcp.infra.google_drive.list import walk_files


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _line_oriented(representation: str) -> bool:
    return representation.startswith("text/plain") or representation.startswith("text/")


def drive_grep(
    drive: object,
    *,
    pattern: str,
    file_ids: list[str] | None = None,
    folder_id: str | None = None,
    case_sensitive: bool = True,
    regex: bool = False,
    context_lines: int = 2,
    max_matches: int | None = None,
    budget: Budget | None = None,
    request_id: str | None = None,
) -> dict:
    budget = budget or Budget()
    if max_matches is not None:
        budget.max_matches = min(budget.max_matches, max_matches)
    compiled = compile_pattern(pattern, regex=regex, case_sensitive=case_sensitive)
    scope = RetrievalScope.from_tool_args(folder_id=folder_id, file_ids=file_ids)
    named_only = bool(file_ids) and not folder_id
    walk = walk_files(
        drive,
        scope,
        budget,
        include_folders=named_only,
        request_id=request_id,
    )

    matches: list[SearchMatch] = []
    skipped_unsupported = 0
    searchable = 0
    last_unsupported: ErrorCategory | None = None
    truncated_bytes = False

    for file in walk.files:
        if budget.time_exceeded():
            walk.time_exceeded = True
            break
        if budget.bytes_exhausted():
            walk.truncated = True
            break
        if file.is_folder:
            if named_only:
                skipped_unsupported += 1
                last_unsupported = ErrorCategory.UNSUPPORTED_MIME_TYPE
            continue
        if default_representation(file.mime_type) is None:
            skipped_unsupported += 1
            last_unsupported = ErrorCategory.UNSUPPORTED_MIME_TYPE
            continue
        try:
            representation = representation_for(file.mime_type, None)
            exported = fetch_text(
                drive,
                file.id,
                file.mime_type,
                representation,
                max_bytes=budget.max_bytes_per_file,
                request_id=request_id,
            )
        except DomainError as exc:
            if exc.error.category in (
                ErrorCategory.UNSUPPORTED_MIME_TYPE,
                ErrorCategory.FILE_NOT_EXPORTABLE,
            ):
                skipped_unsupported += 1
                last_unsupported = exc.error.category
                continue
            if exc.error.category == ErrorCategory.RATE_LIMITED:
                single_named_file = named_only and len(file_ids or []) == 1
                if single_named_file:
                    raise
                walk.rate_limited = True
                break
            raise
        searchable += 1
        budget.note_bytes(exported.byte_length)
        if exported.truncated:
            truncated_bytes = True
        remaining = budget.max_matches - len(matches)
        if remaining <= 0:
            break
        line_oriented = _line_oriented(exported.representation) and not exported.representation.endswith(
            "csv"
        )
        if file.mime_type in (SHEET_MIME, SLIDE_MIME) or exported.representation == "text/csv":
            line_oriented = False
        try:
            raw = search_text(
                exported.text,
                compiled,
                line_oriented=line_oriented,
                context_lines=context_lines,
                remaining=remaining,
            )
        except DomainError:
            raise
        except Exception as exc:  # runtime engine failure after valid compile
            raise DomainError.of(ErrorCategory.SEARCH_ERROR, request_id=request_id) from exc
        retrieved_at = _now()
        for item in raw:
            matches.append(
                SearchMatch(
                    file_id=file.id,
                    file_name=file.name,
                    mime_type=file.mime_type,
                    modified_time=file.modified_time,
                    source_url=file.source_url,
                    retrieved_at=retrieved_at,
                    pattern=pattern,
                    matched_text=item.matched_text,
                    location=item.location,
                    context=item.context,
                )
            )
        budget.note_matches(len(raw))
        if budget.matches_exhausted():
            break

    wire = [m.to_wire() for m in matches]
    hit_match_cap = len(matches) >= budget.max_matches and (
        walk.truncated or budget.matches_exhausted()
    )
    walk_incomplete = walk.rate_limited or walk.time_exceeded or walk.truncated

    if named_only and searchable == 0 and skipped_unsupported and not walk_incomplete:
        raise DomainError.of(last_unsupported or ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id)
    if (
        not named_only
        and searchable == 0
        and skipped_unsupported
        and not walk_incomplete
    ):
        raise DomainError.of(
            last_unsupported or ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id
        )

    if walk.rate_limited:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.RATE_LIMITED.value,
            "matches": wire,
        }
    if walk.time_exceeded:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.max_execution_time.value,
            "matches": wire,
        }
    if hit_match_cap:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.max_matches.value,
            "matches": wire,
        }
    if truncated_bytes:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.max_bytes.value,
            "matches": wire,
        }
    if walk.truncated or budget.bytes_exhausted():
        reason = (
            PartialReason.max_bytes.value
            if budget.bytes_exhausted()
            else PartialReason.max_files.value
        )
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": reason,
            "matches": wire,
        }
    if skipped_unsupported and searchable:
        return {
            "status": OperationStatus.PARTIAL.value,
            "partial_reason": PartialReason.unsupported_skipped.value,
            "matches": wire,
        }
    if not wire:
        return {"status": OperationStatus.EMPTY.value, "matches": []}
    return {"status": OperationStatus.COMPLETE.value, "matches": wire}


def validate_grep_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import require_file_id

    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    max_matches = arguments.get("max_matches")
    if max_matches is not None and (
        not isinstance(max_matches, int) or max_matches < 1 or max_matches > 50
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    context_lines = arguments.get("context_lines")
    if context_lines is not None and (
        not isinstance(context_lines, int) or context_lines < 0 or context_lines > 10
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    folder_id = arguments.get("folder_id")
    if folder_id is not None:
        require_file_id(folder_id)
    file_ids = arguments.get("file_ids")
    if file_ids is not None:
        if not isinstance(file_ids, list):
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
        for fid in file_ids:
            require_file_id(fid)
