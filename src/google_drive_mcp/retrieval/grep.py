"""drive_grep: fetch → exact search → provenance → discard bytes.

No module-level file_id→bytes cache. Walk and multi-target export 429 → PARTIAL RATE_LIMITED.
Small files are downloaded ahead on worker threads; the scan order stays fixed.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime

from google_drive_mcp.domain.budgets import (
    GREP_MAX_FILES,
    GREP_PREFETCH_DEPTH,
    GREP_PREFETCH_MAX_FILE_BYTES,
    GREP_PREFETCH_WINDOW_BYTES,
    GREP_PREFETCH_WORKERS,
    Budget,
)
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.matches import SearchMatch
from google_drive_mcp.domain.operation import OperationStatus, PartialReason
from google_drive_mcp.domain.retrieval_scope import RetrievalScope
from google_drive_mcp.infra.exact_search.regex import (
    SearchTimeout,
    compile_pattern,
    search_text,
)
from google_drive_mcp.infra.google_drive.export import (
    SHEET_MIME,
    SLIDE_MIME,
    default_representation,
    fetch_text,
    is_workspace,
    representation_for,
)
from google_drive_mcp.infra.google_drive.list import walk_files
from google_drive_mcp.retrieval.ports import ExportResult

# Longest pattern accepted, literal or regex (the MCP schema says the same).
GREP_PATTERN_MAX_CHARS = 512
# A regex gets this long on a file even when the call's time is nearly gone
# (the first file of a call is searched past the deadline).
REGEX_MIN_TIMEOUT = 0.5


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _line_oriented(representation: str) -> bool:
    return representation.startswith("text/plain") or representation.startswith("text/")


def _blob_size(file) -> int | None:
    """Bytes a download of this file returns, when Drive knows it.

    Drive reports a storage size for Docs, Sheets and Slides too, but their
    text export has a different length, so they count as unknown size.
    """
    if file.size is None or is_workspace(file.mime_type):
        return None
    return file.size


def _sort_key(file) -> tuple:
    size = _blob_size(file)
    return (size is None, size or 0, file.id)


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


class _Prefetch:
    """Download small files ahead of the scan on worker threads.

    The scan still takes files one at a time in size order, so results never
    depend on which download finishes first. Only supported files with a known
    size up to GREP_PREFETCH_MAX_FILE_BYTES are fetched ahead, at most
    GREP_PREFETCH_DEPTH files and GREP_PREFETCH_WINDOW_BYTES at once, and never
    more bytes than the operation has left. The scan charges a file with a
    known blob size by that size, the same number used here, so a file fetched ahead
    always fits when the scan reaches it and a deferred file is never downloaded.
    """

    def __init__(
        self, files: list, fetch: Callable[[object], ExportResult], *, max_file_bytes: int
    ) -> None:
        self._files = files
        self._fetch = fetch
        # A file the per-file cap would truncate ends the scan, so never fetch one ahead.
        self._max_file_bytes = min(GREP_PREFETCH_MAX_FILE_BYTES, max_file_bytes)
        self._pool = ThreadPoolExecutor(
            max_workers=GREP_PREFETCH_WORKERS, thread_name_prefix="grep-fetch"
        )
        self._futures: dict[int, Future] = {}
        self._sizes: dict[int, int] = {}
        self._next = 0

    def top_up(self, index: int, *, bytes_left: int, files_left: int) -> None:
        self._next = max(self._next, index)
        queued = [i for i in self._futures if i >= index]
        room = min(GREP_PREFETCH_WINDOW_BYTES, bytes_left) - sum(self._sizes[i] for i in queued)
        depth = min(GREP_PREFETCH_DEPTH, files_left)
        count = len(queued)
        # Every position already passed (queued, or unsupported) uses up one
        # of the scan's files.
        slots = files_left - (self._next - index)
        while self._next < len(self._files) and count < depth and slots > 0:
            file = self._files[self._next]
            if file.is_folder:
                self._next += 1
                continue
            if default_representation(file.mime_type, file.name) is None:
                slots -= 1
                self._next += 1
                continue
            size = _blob_size(file)
            if room <= 0 or size is None or size > self._max_file_bytes or size > room:
                break
            self._futures[self._next] = self._pool.submit(self._fetch, file)
            self._sizes[self._next] = size
            room -= size
            count += 1
            slots -= 1
            self._next += 1

    def has(self, index: int) -> bool:
        return index in self._futures

    def take(self, index: int, timeout: float | None) -> ExportResult | None:
        """The prefetched text for files[index], or None if it was not fetched ahead.

        Raises TimeoutError when the download does not finish in time (None
        waits for it), and the fetch's own error (for example DomainError).
        """
        future = self._futures.pop(index, None)
        self._sizes.pop(index, None)
        if future is None:
            return None
        return future.result(timeout=None if timeout is None else max(timeout, 0.0))

    def discard(self, index: int) -> None:
        future = self._futures.pop(index, None)
        self._sizes.pop(index, None)
        if future is not None:
            future.cancel()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._futures.clear()
        self._sizes.clear()


def split_cursor(cursor: str) -> tuple[str, int]:
    """(file_id, skip) from a next_cursor value.

    ``file_id`` continues after that file. ``file_id:N`` continues inside that
    file after its first N matches.
    """
    file_id, sep, count = cursor.partition(":")
    if not sep:
        return file_id, 0
    if not _valid_skip(count):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    return file_id, int(count)


_CURSOR_SKIP_DIGITS = 10


def _valid_skip(count: str) -> bool:
    return (
        0 < len(count) <= _CURSOR_SKIP_DIGITS
        and count.isascii()
        and count.isdigit()
        and int(count) > 0
    )


def _files_needed(match_room: int, matches_so_far: int, files_searched: int) -> int:
    """How many more files this call is likely to scan before max_matches.

    Files fetched ahead past a max_matches stop are thrown away and fetched
    again by the next call, so look ahead only as far as the hits seen so far
    suggest: match_room + 1 before any file is searched, no limit while no
    file has matched, and the room divided by the hits per file after that.
    """
    if files_searched == 0:
        return match_room + 1
    if matches_so_far == 0:
        return GREP_PREFETCH_DEPTH
    per_file = matches_so_far / files_searched
    return int(match_room / per_file) + 1


def _searchable(file) -> bool:
    return not file.is_folder and default_representation(file.mime_type, file.name) is not None


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
    if file_ids:
        # A repeated id would be scanned twice and would stall a cursor on it.
        file_ids = list(dict.fromkeys(file_ids))
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
    files = []
    seen: set[str] = set()
    for item in walk.files:
        # A file with two parents in the tree is listed twice; scan it once.
        if item.id not in seen:
            seen.add(item.id)
            files.append(item)
    listing_complete = not walk.time_exceeded and not walk.rate_limited
    if not listing_complete:
        # A cut listing scans nothing: the cursor cannot be placed in it, and
        # a fresh call is repeated as a whole, so any match or deferral from
        # a partial listing would come back twice. A continuation hands back
        # its own cursor.
        reason = (
            PartialReason.RATE_LIMITED if walk.rate_limited else PartialReason.max_execution_time
        )
        return _coverage(
            status=OperationStatus.PARTIAL,
            partial_reason=reason.value,
            matches=[],
            files_scanned=0,
            bytes_scanned=0,
            next_cursor=cursor or None,
        )
    if not single_target:
        files.sort(key=_sort_key)
    skip = 0
    if cursor:
        resume_id, skip = split_cursor(cursor)
        ids = [item.id for item in files]
        if resume_id not in ids:
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT, request_id=request_id)
        start = ids.index(resume_id)
        files = files[start:] if skip else files[start + 1 :]

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
    match_cursor: str | None = None
    download_rate_limited = False

    def fetch(file) -> ExportResult:
        representation = representation_for(file.mime_type, None, name=file.name)
        return fetch_text(
            drive,
            file.id,
            file.mime_type,
            representation,
            max_bytes=budget.max_bytes_per_file,
            request_id=request_id,
            name=file.name,
            size=file.size,
        )

    prefetch = (
        None
        if single_target
        else _Prefetch(files, fetch, max_file_bytes=budget.max_bytes_per_file)
    )
    try:
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
            # Every call handles at least one file (the listing is finished
            # here), so a time stop always progresses. Read the clock once.
            late = budget.time_exceeded()
            if files_scanned and late:
                if pending:
                    resume = True
                    stopped_for_time = True
                break
            if files_scanned >= budget.max_files:
                if pending:
                    resume = True
                break
            # An unsupported file is skipped, never deferred: a deferred id is
            # one the host can grep on its own.
            if default_representation(file.mime_type, file.name) is None:
                skipped_unsupported += 1
                files_scanned += 1
                last_scanned_id = file.id
                last_unsupported = ErrorCategory.UNSUPPORTED_MIME_TYPE
                index += 1
                continue
            if not single_target:
                remaining = budget.max_bytes_per_operation - budget.bytes_seen
                if remaining <= 0:
                    deferred.extend(item.id for item in files[index:] if _searchable(item))
                    break
                size = _blob_size(file)
                if size is not None and size > remaining:
                    deferred.append(file.id)
                    if prefetch is not None:
                        prefetch.discard(index)
                    index += 1
                    continue
            try:
                exported = None
                if prefetch is not None:
                    # Resuming inside a file usually stops in it again, so do
                    # not download later files until the scan has moved past
                    # it; nor once the deadline has passed (only this file is
                    # scanned then). A file already fetched ahead is still used.
                    if not (index == 0 and skip) and not late:
                        prefetch.top_up(
                            index,
                            bytes_left=budget.max_bytes_per_operation - budget.bytes_seen,
                            files_left=min(
                                budget.max_files - files_scanned,
                                _files_needed(
                                    budget.max_matches - len(matches), len(matches), searchable
                                ),
                            ),
                        )
                    exported = prefetch.take(
                        index, timeout=budget.time_left() if files_scanned else None
                    )
                if exported is None:
                    exported = fetch(file)
            except TimeoutError:
                # A download outlived the time cap; resume from this file.
                resume = True
                stopped_for_time = True
                break
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
                    # A fresh single-file call reports the 429 as an error; a
                    # continuation keeps its place with a PARTIAL and cursor.
                    if single_target and not cursor:
                        raise
                    download_rate_limited = True
                    break
                raise
            files_scanned += 1
            scanned_before = last_scanned_id
            last_scanned_id = file.id
            searchable += 1
            # Charge a blob's Drive size: prefetch plans with the same number,
            # so what it fetched always fits (FR-038a). Exports and truncated
            # downloads are charged what was actually read.
            size = _blob_size(file)
            budget.note_bytes(
                size if size is not None and not exported.truncated else exported.byte_length
            )
            if exported.truncated:
                truncated_bytes = True
            match_room = budget.max_matches - len(matches)
            line_oriented = _line_oriented(
                exported.representation
            ) and not exported.representation.endswith("csv")
            if file.mime_type in (SHEET_MIME, SLIDE_MIME) or exported.representation == "text/csv":
                line_oriented = False
            skip_here = skip if index == 0 else 0
            timed_out = False
            try:
                # One extra match past the room tells whether this file has more.
                raw = search_text(
                    exported.text,
                    compiled,
                    line_oriented=line_oriented,
                    context_lines=context_lines,
                    remaining=match_room + 1,
                    skip=skip_here,
                    timeout=max(budget.time_left(), REGEX_MIN_TIMEOUT) if regex else None,
                )
            except SearchTimeout as exc:
                # A slow regex stops like the time cap; keep what it finished.
                raw = exc.found
                timed_out = True
            except DomainError:
                raise
            except Exception as exc:  # runtime engine failure after valid compile
                raise DomainError.of(ErrorCategory.SEARCH_ERROR, request_id=request_id) from exc
            more_in_file = len(raw) > match_room
            raw = raw[:match_room]
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
            if timed_out:
                stopped_for_time = True
                done = skip_here + len(raw)
                if done:
                    # Continue inside this file after the matches returned so far.
                    match_cursor = f"{file.id}:{done}"
                else:
                    # Continue at this file: after the one handled before it.
                    resume = True
                    last_scanned_id = scanned_before
                break
            if more_in_file:
                hit_match_cap = True
                match_cursor = f"{file.id}:{skip_here + len(raw)}"
                break
            if budget.matches_exhausted() and any(_searchable(item) for item in files[index + 1 :]):
                hit_match_cap = True
                match_cursor = file.id
                break
            if not single_target and (exported.truncated or budget.bytes_exhausted()):
                rest = [item.id for item in files[index + 1 :] if _searchable(item)]
                if rest:
                    deferred.extend(rest)
                    break
                # Nothing searchable is left out: an unsupported tail is still
                # counted as skipped, and the slice can finish.
            index += 1
    finally:
        if prefetch is not None:
            prefetch.close()

    wire = [m.to_wire() for m in matches]
    rate_limited = walk.rate_limited or download_rate_limited
    stopped = (
        rate_limited
        or walk.time_exceeded
        or stopped_for_time
        or resume
        or truncated_bytes
        or bool(deferred)
        or hit_match_cap
    )

    # A continuation slice left with only unsupported files is the tail of a
    # mixed walk (FR-037), not a walk where every target is unsupported.
    if searchable == 0 and skipped_unsupported and not stopped and not cursor:
        raise DomainError.of(
            last_unsupported or ErrorCategory.UNSUPPORTED_MIME_TYPE, request_id=request_id
        )

    # The listing is finished here (a cut listing returned early).
    next_cursor = None
    if match_cursor:
        next_cursor = match_cursor
    elif resume or download_rate_limited:
        # Continue after the last file scanned, or from the incoming cursor
        # when this call stopped before scanning anything.
        next_cursor = last_scanned_id or cursor or None
        if next_cursor is None:
            # Nothing was scanned; repeating the call revisits every file.
            deferred = []
    if next_cursor and deferred:
        # The next call revisits every file after the cursor, so a file there
        # is not also handed back for its own call.
        resume_id, resume_skip = split_cursor(next_cursor)
        order = {item.id: k for k, item in enumerate(files)}
        cut = order.get(resume_id, -1)
        first_revisited = cut if resume_skip else cut + 1
        deferred = [fid for fid in deferred if order[fid] < first_revisited]
    common = {
        "matches": wire,
        "files_scanned": files_scanned,
        "bytes_scanned": budget.bytes_seen,
        "deferred_file_ids": deferred,
        "next_cursor": next_cursor,
    }
    if rate_limited:
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
    if truncated_bytes or deferred:
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
    if skipped_unsupported and (searchable or cursor):
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
    ``next_cursor`` are the same continuation point: ``file_id`` continues after
    that file, ``file_id:N`` inside it after its first N matches. With file_ids,
    the cursor must name one of them.
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
    file_id, sep, count = chosen.partition(":")
    require_file_id(file_id)
    if sep and not _valid_skip(count):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
    named = arguments.get("file_ids")
    if named and file_id not in named:
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
    if not isinstance(pattern, str) or not pattern or len(pattern) > GREP_PATTERN_MAX_CHARS:
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
