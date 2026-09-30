"""drive_grep: fetch → exact search → provenance → discard bytes.

No module-level file_id→bytes cache. Walk and multi-target export 429 → PARTIAL RATE_LIMITED.
"""

from __future__ import annotations

from datetime import UTC, datetime

from google_drive_mcp.domain.budgets import GREP_MAX_FILES, Budget
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


def _sort_key(file) -> tuple:
    return (file.size is None, file.size or 0, file.id)


def _coverage(
    *,
    status: OperationStatus,
    matches: list,
    files_scanned: int,
    bytes_scanned: int,
    partial_reason: str | None = None,
    deferred_file_ids: list[str] | None = None,
    next_cursor: str | None = None,
) -> dict:
    body: dict = {
        "status": status.value,
        "matches": matches,
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
    }
    if partial_reason is not None:
        body["partial_reason"] = partial_reason
    if deferred_file_ids:
        body["deferred_file_ids"] = deferred_file_ids
    if next_cursor:
        body["next_cursor"] = next_cursor
    return body


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
    cursor: str | None = None,
    budget: Budget | None = None,
    request_id: str | None = None,
) -> dict:
    budget = budget or Budget(max_files=GREP_MAX_FILES)
    if max_matches is not None:
        budget.max_matches = min(budget.max_matches, max_matches)
    compiled = compile_pattern(pattern, regex=regex, case_sensitive=case_sensitive)
    scope = RetrievalScope.from_tool_args(folder_id=folder_id, file_ids=file_ids)
    named_only = bool(file_ids) and not folder_id
    single_target = named_only and len(file_ids or []) == 1
    walk = walk_files(
        drive,
        scope,
        budget,
        include_folders=named_only,
        honor_file_cap=False,
        count_listed=False,
        request_id=request_id,
    )
    files = list(walk.files)
    listing_complete = not walk.time_exceeded and not walk.rate_limited
    if not single_target:
        files.sort(key=_sort_key)
    if cursor and listing_complete:
        ids = [item.id for item in files]
        if cursor not in ids:
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT, request_id=request_id)
        files = files[ids.index(cursor) + 1 :]

    matches: list[SearchMatch] = []
    skipped_unsupported = 0
    searchable = 0
    files_scanned = 0
    last_unsupported: ErrorCategory | None = None
    truncated_bytes = False
    deferred: list[str] = []
    last_scanned_id: str | None = None
    resume = False
    stopped_for_time = False
    hit_match_cap = False

    index = 0
    while index < len(files):
        file = files[index]
        if file.is_folder:
            if named_only:
                skipped_unsupported += 1
                files_scanned += 1
                last_unsupported = ErrorCategory.UNSUPPORTED_MIME_TYPE
                last_scanned_id = file.id
            index += 1
            continue
        pending = [item.id for item in files[index:] if not item.is_folder]
        if budget.time_exceeded():
            if pending:
                resume = True
                stopped_for_time = True
            break
        if files_scanned >= budget.max_files:
            if pending:
                resume = True
            break
        if not single_target:
            remaining = budget.max_bytes_per_operation - budget.bytes_seen
            if remaining <= 0:
                deferred.extend(pending)
                break
            if file.size is not None and file.size > remaining:
                deferred.append(file.id)
                index += 1
                continue
        if default_representation(file.mime_type, file.name) is None:
            skipped_unsupported += 1
            files_scanned += 1
            last_scanned_id = file.id
            last_unsupported = ErrorCategory.UNSUPPORTED_MIME_TYPE
            index += 1
            continue
        try:
            representation = representation_for(file.mime_type, None, name=file.name)
            exported = fetch_text(
                drive,
                file.id,
                file.mime_type,
                representation,
                max_bytes=budget.max_bytes_per_file,
                request_id=request_id,
                name=file.name,
            )
        except DomainError as exc:
            if exc.error.category in (
                ErrorCategory.UNSUPPORTED_MIME_TYPE,
                ErrorCategory.FILE_NOT_EXPORTABLE,
            ):
                skipped_unsupported += 1
                files_scanned += 1
                last_scanned_id = file.id
                last_unsupported = exc.error.category
                index += 1
                continue
            if exc.error.category == ErrorCategory.RATE_LIMITED:
                if single_target:
                    raise
                walk.rate_limited = True
                break
            raise
        files_scanned += 1
        last_scanned_id = file.id
        searchable += 1
        budget.note_bytes(exported.byte_length)
        if exported.truncated:
            truncated_bytes = True
        match_room = budget.max_matches - len(matches)
        if match_room <= 0:
            hit_match_cap = True
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
                remaining=match_room,
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
            hit_match_cap = True
            break
        if not single_target and (exported.truncated or budget.bytes_exhausted()):
            deferred.extend(item.id for item in files[index + 1 :] if not item.is_folder)
            break
        index += 1

    wire = [m.to_wire() for m in matches]
    stopped = (
        walk.rate_limited
        or walk.time_exceeded
        or stopped_for_time
        or resume
        or truncated_bytes
        or bool(deferred)
        or hit_match_cap
    )

    if searchable == 0 and skipped_unsupported and not stopped:
        raise DomainError.of(
            last_unsupported or ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id
        )

    next_cursor = None
    if listing_complete and resume and last_scanned_id and not walk.rate_limited:
        next_cursor = last_scanned_id
    common = {
        "matches": wire,
        "files_scanned": files_scanned,
        "bytes_scanned": budget.bytes_seen,
        "deferred_file_ids": deferred,
        "next_cursor": next_cursor,
    }
    if walk.rate_limited:
        return _coverage(
            status=OperationStatus.PARTIAL,
            partial_reason=PartialReason.RATE_LIMITED.value,
            **common,
        )
    if walk.time_exceeded or stopped_for_time:
        return _coverage(
            status=OperationStatus.PARTIAL,
            partial_reason=PartialReason.max_execution_time.value,
            **common,
        )
    if hit_match_cap:
        return _coverage(
            status=OperationStatus.PARTIAL,
            partial_reason=PartialReason.max_matches.value,
            **common,
        )
    if truncated_bytes or deferred or budget.bytes_exhausted():
        return _coverage(
            status=OperationStatus.PARTIAL,
            partial_reason=PartialReason.max_bytes.value,
            **common,
        )
    if resume:
        return _coverage(
            status=OperationStatus.PARTIAL,
            partial_reason=PartialReason.max_files.value,
            **common,
        )
    if skipped_unsupported and searchable:
        return _coverage(
            status=OperationStatus.PARTIAL,
            partial_reason=PartialReason.unsupported_skipped.value,
            **common,
        )
    if not wire:
        return _coverage(status=OperationStatus.EMPTY, **common)
    return _coverage(status=OperationStatus.COMPLETE, **common)


def grep_resume_cursor(arguments: dict) -> str | None:
    """Accept the previous result's next_cursor under either input name.

    Empty string and omitted values start from the first file. ``cursor`` and
    ``next_cursor`` are the same continuation point.
    """
    from google_drive_mcp.mcp.validation import require_file_id

    chosen: str | None = None
    for key in ("next_cursor", "cursor"):
        raw = arguments.get(key)
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
        text = raw.strip()
        if not text:
            continue
        if chosen is not None and text != chosen:
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
        chosen = text
    if chosen is None:
        return None
    require_file_id(chosen)
    if arguments.get("file_ids"):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    return chosen


def validate_grep_args(arguments: dict) -> None:
    from google_drive_mcp.mcp.validation import (
        CONTEXT_LINES_MAX,
        CONTEXT_LINES_MIN,
        MAX_MATCHES_MAX,
        MAX_MATCHES_MIN,
        require_file_id,
    )

    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)

    max_matches = arguments.get("max_matches")
    if max_matches is not None and (
        not isinstance(max_matches, int)
        or max_matches < MAX_MATCHES_MIN
        or max_matches > MAX_MATCHES_MAX
    ):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    context_lines = arguments.get("context_lines")
    if context_lines is not None and (
        not isinstance(context_lines, int)
        or context_lines < CONTEXT_LINES_MIN
        or context_lines > CONTEXT_LINES_MAX
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
    grep_resume_cursor(arguments)
