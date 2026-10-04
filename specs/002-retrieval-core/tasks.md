---
description: "Task list for Retrieval Core"
---

# Tasks: Retrieval Core

**Branch**: `main` (spec dir `specs/002-retrieval-core`)

**Input**: Design documents from `/specs/002-retrieval-core/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/; Access Control MVP (US1 ALLOW path)

**Tests**: Included — plan.md and quickstart.md require pytest contract tests against a fake Drive.

**Organization**: User stories US1–US4 from spec.md. Same package as Access Control.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4 map to spec user stories
- Include exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Extend the Access Control package; do not re-init a second project

- [X] T001 Confirm Access Control `pyproject.toml` and `src/google_drive_mcp` exist; add retrieval directories `src/google_drive_mcp/{retrieval,infra/google_drive,infra/exact_search}` and `tests/unit/retrieval` with `__init__.py` (reuse `tests/fakes` from Access Control; do not create a second fake module)
- [X] T002 [P] Extend the shared fake Drive port in `tests/fakes/fake_drive.py` (in-memory files/folders, metadata vs content counters, no persistence; do not add `fake_drive_store.py`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Domain models, ports, budgets, tool registration hook — BLOCKS stories

- [X] T003 Implement `DriveFile` / folder helpers in `src/google_drive_mcp/domain/drive_file.py`
- [X] T004 [P] Implement `Provenance` requiring `file_id` in `src/google_drive_mcp/domain/provenance.py`
- [X] T005 [P] Implement `DocumentContent` (ephemeral) in `src/google_drive_mcp/domain/content.py`
- [X] T006 [P] Implement `SearchCandidate` (not evidence) in `src/google_drive_mcp/domain/candidates.py`
- [X] T007 [P] Implement `SearchMatch` in `src/google_drive_mcp/domain/matches.py`
- [X] T008 Implement operation status `COMPLETE|PARTIAL|EMPTY|ERROR` and `partial_reason` in `src/google_drive_mcp/domain/operation.py` per `specs/002-retrieval-core/contracts/result-status.md`
- [X] T009 Implement default resource budgets in `src/google_drive_mcp/domain/budgets.py` (max_files=40, max_bytes_per_file=20_000_000, max_bytes_per_operation=20_000_000, max_matches=50, max_execution_time=25s, max_context_lines=2, max_export_size=20_000_000)
- [X] T010 Define Drive list/export ports (no Google types) in `src/google_drive_mcp/retrieval/ports.py` (parent_lookup used by `is_within_scope`; do not reimplement descendant checks)
- [X] T011 Register empty MCP tools module in `src/google_drive_mcp/mcp/tools.py` and mount it from existing `mcp/server.py` composition root through access-control middleware (do not create a second server)

**Checkpoint**: Foundation ready — user stories can start (requires Access Control chain wrapping tools)

---

## Phase 3: User Story 1 - Discover candidates, then read current content (Priority: P1) 🎯 MVP

**Goal**: `drive_ls` (immediate children), `drive_find` (recursive descendants), `drive_read` (live text + provenance). Unsupported types fail classified, not empty.

**Independent Test**: Fake Drive with a nested Doc. `ls` has no body and includes `source_url`; `find` on parent includes nested file as candidate; `read` returns text + `file_id`/`modified_time`; binary file by id → `UNSUPPORTED_MIME_TYPE`.

### Tests for User Story 1

- [X] T012 [P] [US1] Contract tests for `drive_ls` in `tests/contract/test_drive_ls.py`
- [X] T013 [P] [US1] Contract tests for `drive_find` (nested descendants, no content field) in `tests/contract/test_drive_find.py`
- [X] T014 [P] [US1] Contract tests for `drive_read` provenance, default `content_format` (plan export map), and unsupported MIME in `tests/contract/test_drive_read.py`

### Implementation for User Story 1

- [X] T015 [P] [US1] Implement metadata list adapter (immediate children vs descendant walk via `is_within_scope`) in `src/google_drive_mcp/infra/google_drive/list.py`
- [X] T016 [P] [US1] Implement export/download adapter (Docs/Sheets/Slides map + text/* download) in `src/google_drive_mcp/infra/google_drive/export.py`; 404/403-as-404 and single-file 429 via `domain/google_errors.map_google_error` (do not map walk 429 here)
- [X] T017 [US1] Implement `drive_ls` use case in `src/google_drive_mcp/retrieval/ls.py` (no content in output)
- [X] T018 [US1] Implement `drive_find` use case in `src/google_drive_mcp/retrieval/find.py` (candidates only; recursive folder)
- [X] T019 [US1] Implement `drive_read` use case in `src/google_drive_mcp/retrieval/read.py` (call-time fetch, provenance required; omitted `content_format` uses the plan export map; unknown `content_format` → `INVALID_ARGUMENT`)
- [X] T020 [US1] Expose `drive_ls`, `drive_find`, `drive_read` in `src/google_drive_mcp/mcp/tools.py` behind chain middleware
- [X] T021 [US1] Populate `tests/fakes/fake_drive.py` with folder, nested Doc/Sheet/Slide, text file, and opaque binary

**Checkpoint**: US1 pytest contract tests pass; discover → read works without grep

---

## Phase 4: User Story 2 - Exact search turns retrieved bytes into evidence (Priority: P1)

**Goal**: `drive_grep` is local exact match on bytes retrieved in this call; deterministic; EMPTY vs fabricated; literal vs regex; case flag.

**Independent Test**: Unique phrase → match + provenance. Missing phrase → `matches: []`, `EMPTY`. Same bytes+params twice → identical matches. `regex` and `case_sensitive` differ as specified.

### Tests for User Story 2

- [X] T022 [P] [US2] Contract tests for grep matches, EMPTY, literal vs regex, case flag in `tests/contract/test_drive_grep.py`
- [X] T023 [P] [US2] Unit tests for regex adapter determinism in `tests/unit/retrieval/test_regex.py`
- [X] T046 [P] [US2] Mixed-folder grep: skip unsupported files → `PARTIAL`; all-unsupported → classified error in `tests/contract/test_drive_grep.py` (FR-037)

### Implementation for User Story 2

- [X] T024 [P] [US2] Implement exact-search adapter (`re.escape` vs compile, IGNORECASE) in `src/google_drive_mcp/infra/exact_search/regex.py`
- [X] T025 [US2] Implement `drive_grep` use case (fetch → search → provenance → discard bytes; map runtime engine failures to `SEARCH_ERROR`) in `src/google_drive_mcp/retrieval/grep.py`
- [X] T026 [US2] Register `drive_grep` in `src/google_drive_mcp/mcp/tools.py` (real tool; AUTH folder∩file_ids is replayed in T039)
- [X] T027 [US2] Add line-context vs 200-char window for non-line formats in `src/google_drive_mcp/retrieval/grep.py`

**Checkpoint**: US2 independently testable; no Drive `fullText` used for grep

---

## Phase 5: User Story 3 - Iterate without a RAG index (Priority: P1)

**Goal**: Multi-step find → read → grep uses live fetches only; no persistent index or leftover exports.

**Independent Test**: Chain tools on fake Drive; grep the repo for vector/embedding stores (none). Temp dirs from exports are gone after the call. Second request does not reuse first request bytes.

### Tests for User Story 3

- [X] T028 [P] [US3] Integration chain find→read→grep→read→grep in `tests/integration/test_iterative_retrieval.py`
- [X] T029 [P] [US3] Assert no leftover temp export files after operations in `tests/integration/test_ephemeral_storage.py`

### Implementation for User Story 3

- [X] T030 [US3] Ensure export/download uses in-memory or `TemporaryDirectory` cleaned in `finally` in `src/google_drive_mcp/infra/google_drive/export.py`; tempfile failures → `TEMPORARY_STORAGE_ERROR`
- [X] T031 [US3] Forbid cross-call content cache (no module-level dict of file_id→bytes) in `src/google_drive_mcp/retrieval/read.py` and `src/google_drive_mcp/retrieval/grep.py`
- [X] T032 [US3] Add a unit/grep check that `src/` contains no embedding/vector index dependencies in `tests/unit/retrieval/test_no_rag.py`

**Checkpoint**: Iteration works; Art. II/III hold in tests

---

## Phase 6: User Story 4 - Freshness and visible completeness (Priority: P2)

**Goal**: Re-read sees fixture updates; limits yield `PARTIAL` with reason; rate-limit stop is completeness, not silent full success.

**Independent Test**: Mutate fake Drive between reads. `max_matches=1` with two hits → `PARTIAL`. Simulated rate-limit during find/grep → `status: PARTIAL`, `partial_reason: RATE_LIMITED` (including zero items), never `EMPTY`/`COMPLETE` by omission. Single-file 429 with no prefix → `ErrorEnvelope` `RATE_LIMITED`.

### Tests for User Story 4

- [X] T033 [P] [US4] Freshness test (update fixture, second read) in `tests/integration/test_freshness.py`
- [X] T034 [P] [US4] `PARTIAL` for max_files/max_matches/max_bytes/`max_execution_time` and walk rate-limit in `tests/contract/test_partial_status.py`

### Implementation for User Story 4

- [X] T035 [US4] Thread budgets through ls/find/read/grep and set `status`/`partial_reason` in `src/google_drive_mcp/retrieval/{ls,find,read,grep}.py`
- [X] T036 [US4] Map sustained Google rate-limit during a walk to `status: PARTIAL` + `partial_reason: RATE_LIMITED` (no silent retry-to-COMPLETE; not ErrorEnvelope RATE_LIMITED) in `src/google_drive_mcp/infra/google_drive/list.py` and `src/google_drive_mcp/retrieval/grep.py`
- [X] T037 [US4] Pagination: `drive_ls` `page_token`/`max_results` must not report `COMPLETE` when more children exist in `src/google_drive_mcp/retrieval/ls.py`

**Checkpoint**: Completeness is visible; no stale MCP copy

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T038 [P] Run `specs/002-retrieval-core/quickstart.md` pytest commands and fix gaps
- [X] T039 [P] Confirm unauthenticated tools never hit fake Drive content I/O in `tests/contract/test_tools_require_auth.py` (do not edit Access Control `test_auth_contract.py`; reuse fixtures). Replay AUTH on real `drive_grep`: `folder_id` + granted `file_id` outside that folder → `AUTHORIZATION_ERROR`, content I/O = 0
- [X] T040 Scan `src/google_drive_mcp/infra/google_drive` for write methods (`create`, `update`, `delete`, `permissions`) and fail the build if found in `tests/unit/retrieval/test_readonly_drive_adapter.py` (oauth/tool-registration scan remains Access Control T020)
- [X] T041 Dockerfile for Cloud Run serving Streamable HTTP in `Dockerfile` (no document volume, read-only Drive env secrets)
- [X] T042 [P] Retrieval structured logs (`request_id, tool, file count, bytes processed, duration, result count, status, error category`; no document bodies) in `src/google_drive_mcp/infra/logging.py` or `src/google_drive_mcp/mcp/tools.py` per FR-103
- [X] T043 [P] Contract tests for `INVALID_ARGUMENT` (bad regex, bad file_id shape, max_bytes/max_results out of range, unknown `content_format`) in `tests/contract/test_invalid_argument.py`
- [X] T044 [P] Untrusted-content control-flow test: document body containing tool-like instructions does not change grep flags, pagination, or status in `tests/unit/retrieval/test_untrusted_tool_control_flow.py` (FR-080)
- [X] T045 Confirm list/export/read/grep use `map_google_error` for 404/403-as-404 (and single-file 429 with no prefix); walk 429 stays T036 `PARTIAL` — do not invent a second 404 mapper or send walk 429 through the mapper as `RATE_LIMITED`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup**: Requires Access Control package skeleton (`pyproject.toml`, chain middleware)
- **Foundational**: Depends on Setup — BLOCKS stories
- **US1**: MVP discover + read
- **US2**: Grep (can start after Foundational; needs read/export from US1 for real bytes)
- **US3**: Depends on US1+US2 tools existing
- **US4**: Depends on tools + budgets
- **Polish**: After desired stories

### User Story Dependencies

- **US1 (P1)**: After Phase 2
- **US2 (P1)**: After US1 export/read path (same fake store)
- **US3 (P1)**: After US1+US2
- **US4 (P2)**: After US1 (PARTIAL on ls/find/read) and US2 (PARTIAL on grep)

### Parallel Opportunities

- T003–T007 models in parallel after T001
- T012–T014 contract tests in parallel
- T015–T016 adapters in parallel
- T022–T023 and T046 tests in parallel
- T028–T029 in parallel
- T033–T034 in parallel
- T042–T044 in parallel with polish

---

## Parallel Example: User Story 1

```bash
Task: "Contract tests in tests/contract/test_drive_ls.py"
Task: "Contract tests in tests/contract/test_drive_find.py"
Task: "Contract tests in tests/contract/test_drive_read.py"

Task: "List adapter in src/google_drive_mcp/infra/google_drive/list.py"
Task: "Export adapter in src/google_drive_mcp/infra/google_drive/export.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Access Control US1 complete
2. Retrieval Setup + Foundational
3. Retrieval US1 (`ls`/`find`/`read`)
4. **STOP**: contract tests + quickstart steps **1–3, 7, 9–10** (`drive_ls` / `drive_find` / `drive_read`, binary-by-id unsupported, no leftover temp files, unauthenticated content I/O = 0). Skip 4–6, 8, 11 until US2/US4.

### Incremental Delivery

1. US1 discover/read
2. US2 grep
3. US3 ephemeral iteration
4. US4 PARTIAL/freshness
5. Dockerfile polish

---

## Notes

- Tools MUST go through Access Control middleware; do not call Drive adapters from tools directly on AUTH failures
- AUTH folder∩file_ids on real `drive_grep` is T039 (Access Control US1 already covered the same args on the stub)
- One fake Drive port: `tests/fakes/fake_drive.py`; do not add `fake_drive_store.py`
- No embeddings, vector DBs, or persistent file cache
- Do not implement a second `RetrievalScope` type or a descendant check outside `domain/retrieval_scope.py`
- Push to `main` unless a PR is requested
- Verify story tests fail before implementation tasks in that phase

---

## Phase 8: Convergence

Remaining work from `/speckit-converge` (2026-09-08). Do not rewrite earlier tasks.

- [X] T047 Return `status: PARTIAL` with `partial_reason: max_bytes` from `drive_grep` when `fetch_text` truncates a file at `max_bytes` / `max_export_size` instead of searching the prefix and possibly reporting `COMPLETE` in `retrieval/grep.py` (FR-041, FR-104, Article X) (partial)
- [X] T048 Honor `max_execution_time` during production `GoogleDriveClient` list pagination in `infra/google_drive/client.py` (and surface `PARTIAL` / `max_execution_time`) instead of fetching the full grant/folder into memory before `walk_files` can stop (FR-104, FR-041) (partial)
- [X] T049 Map a non-integer `drive_ls` `page_token` to `INVALID_ARGUMENT` in `infra/google_drive/list.py` / `retrieval/ls.py` instead of raising `ValueError` (FR-003, FR-060 `INVALID_ARGUMENT`) (partial)

---

## Phase 9: Convergence

Remaining work from `/speckit-converge` (2026-09-08, second pass). Do not rewrite earlier tasks.

- [X] T050 CRITICAL Return `PARTIAL` with `partial_reason: RATE_LIMITED` / `max_files` / `max_execution_time` from `drive_grep` when a folder or whole-grant walk is cut short with zero searchable files, instead of raising `UNSUPPORTED_MIME_TYPE` because the all-unsupported check runs before completeness flags in `retrieval/grep.py` (FR-037, FR-041, US4/AC3, Article X, result-status.md) (contradicts) — whole-grant walks removed by T064
- [X] T051 Skip `file.is_folder` in `drive_grep` without counting folders as unsupported skips, so a completed search over folders plus searchable docs is not `PARTIAL`/`unsupported_skipped` and a folder-only tree is `EMPTY` rather than `UNSUPPORTED_MIME_TYPE` in `retrieval/grep.py` (FR-037, FR-041, Article X) (contradicts)
- [X] T052 Stop counting folder nodes toward grep `max_files` in `infra/google_drive/list.py` `walk_files`/`consider()` (or exclude folders from the grep walk payload while still using them for BFS) so nested docs remain reachable under the file budget (FR-030, FR-104) (partial)

---

## Phase 10: Convergence

Remaining work from `/speckit-converge` (2026-09-08, third pass). Do not rewrite earlier tasks.

- [X] T053 Wrap `drive.get_metadata` failures in `retrieval/read.py` with `map_google_error` so a post-ALLOW 404/429 becomes `FILE_NOT_FOUND` / `RATE_LIMITED` instead of an uncaught `GoogleApiError` (FR-060, T045, Article XI, drive_read.md) (contradicts)
- [X] T054 Treat Google Slides as a non-line-oriented grep target (200-character window, not `max_context_lines`) in `retrieval/grep.py` per plan: Sheets/Slides context (FR-034, plan: Sheets/Slides context) (partial)

---

## Phase 11: Convergence

Remaining work from `/speckit-converge` (2026-09-08, fourth pass). Do not rewrite earlier tasks.

- [X] T055 CRITICAL Intercept Google HTTP 429 from `fetch_text` / export / `get_media` during multi-target `drive_grep` (folder_id, default_whole_grant, or multiple file_ids) as `status: PARTIAL` with `partial_reason: RATE_LIMITED` (preserve matches already found; empty matches still PARTIAL), instead of re-raising `map_google_error` `ErrorEnvelope` `RATE_LIMITED`; keep single-file `drive_read` and single-`file_ids` grep export 429 with no usable prefix as `ErrorEnvelope` `RATE_LIMITED` in `retrieval/grep.py` (FR-041, FR-060, US4/AC3, Article X, result-status.md, plan: walk 429) (contradicts) — `default_whole_grant` grep removed by T064

---

## Phase 12: Convergence

Remaining work from `/speckit-converge` (2026-09-13). Do not rewrite earlier tasks.

- [X] T056 Honor `trashed=true` on folder-scoped `drive_find` by threading `include_trashed` through `walk_files` → `GoogleDriveClient.list_children` / `FakeDrive.list_children` instead of hard-coding `trashed = false` (whole-grant `list_all` already respects the flag; `list_all` since removed by T064) in `src/google_drive_mcp/infra/google_drive/list.py`, `src/google_drive_mcp/infra/google_drive/client.py`, and `tests/fakes/fake_drive.py` per FR-010 (partial)
- [X] T057 Advertise `FILE_ID_PATTERN` on `drive_grep` `file_ids` JSON Schema array items in `src/google_drive_mcp/mcp/server.py` so `tools/list` matches `require_file_id` validation (today items are plain `string`) per FR-091 (partial)

---

## Phase 13: Find pushdown and grep coverage

Filename discovery and folder grep coverage (FR-012, FR-036, FR-038). No persistent index, no BM25, no per-file cap below 20 MB.

- [X] T058 Push `name contains`, MIME, `modifiedTime`, and `trashed = false` into `files.list` (`pageSize` 1000) and count `drive_find` `max_results` only for matching non-folder files, without `files.get` on each listed child, in `domain/list_filter.py`, `infra/google_drive/query.py`, `infra/google_drive/client.py`, `infra/google_drive/list.py`, `retrieval/find.py`, and `tests/fakes/fake_drive.py` (FR-012)
- [X] T059 Scan folder and whole-grant `drive_grep` known-smaller files first; defer a known size that does not fit remaining operation bytes (and the larger tail) as `deferred_file_ids` without downloading; always return `files_scanned` and `bytes_scanned`; set `next_cursor` only when the listing finished and more non-deferred files remain; never defer a single `file_id` in `retrieval/grep.py`, `mcp/server.py`, `mcp/tools.py`, and `mcp/tool_schema.py` (FR-038, FR-036) — whole-grant grep removed by T064
- [X] T060 Contract tests for find pushdown, grep deferral, cursor resume, and coverage counts in `tests/contract/test_drive_find.py`, `tests/contract/test_drive_grep.py`, and `tests/unit/retrieval/test_list_query.py`

---

## Phase 14: Default kb scope and next_cursor input

- [X] T061 When `DRIVE_DEFAULT_FOLDER_ID` is set, omitted `drive_find` and `drive_grep` search that folder (`kb` on this deployment) without disallowing a named folder or file id, and omitted `drive_ls` still lists My Drive root, in `domain/retrieval_scope.py`, `mcp/tools.py`, `infra/config.py`, and `scripts/deploy-cloud-run.sh` (FR-010, FR-030) — superseded by T064: `DRIVE_DEFAULT_FOLDER_ID` removed
- [X] T062 Advertise `next_cursor` as a `drive_grep` input (alias `cursor`) so a host can pass the previous result field back, in `mcp/server.py`, `retrieval/grep.py`, and `mcp/tool_schema.py` (FR-030)

---

## Phase 15: Allow only the kb folder

- [X] T063 Set `DRIVE_ALLOWED_FOLDER_ID` to the `kb` folder on this deployment so omitted `drive_ls`, `drive_find`, and `drive_grep` run in `kb`, and a named `folder_id` or `file_id` outside `kb` is `AUTHORIZATION_ERROR`, in `scripts/deploy-cloud-run.sh`, `mcp/server.py`, `mcp/tool_schema.py`, and host copy (AC-FR-021, FR-001, FR-010, FR-030)
- [X] T064 Fail closed so only `kb` and its descendants are readable and nothing outside `kb` can be listed: require `DRIVE_ALLOWED_FOLDER_ID` (the server refuses to start when it is unset, blank, an alias such as `root` / `appDataFolder`, or not a plain id; the chain returns `AUTHORIZATION_ERROR` `no_allowed_folder` for every call without it, before any Google call); delete `DRIVE_DEFAULT_FOLDER_ID` and `apply_default_search_folder`; refuse a call that names no folder or file after the rewrite (`whole_grant_refused`), raise `AUTHORIZATION_ERROR` from `drive_ls` with no folder instead of listing My Drive `root`, stop `walk_files` from listing the whole grant, and remove `list_all` from the Drive client, port, and fake; check the allow-list first for every named `folder_id` / `file_id` / `file_ids` so an id outside `kb`, a missing id, and an ungranted id all get the same `AUTHORIZATION_ERROR` (`FILE_NOT_FOUND` only for an id proven inside `kb` that then misses); accept only the argument keys each tool body reads (`TOOL_ARGUMENTS`, else `INVALID_ARGUMENT` before the chain) and stop blank ids from skipping the `kb` rewrite; drop listed children whose `parents` do not include the listed folder; pin the `kb` folder id in deploy, route all traffic to the newest revision, check it carries the allow-list, and delete older revisions without it, in `domain/retrieval_scope.py`, `access_control/chain.py`, `mcp/tools.py`, `mcp/server.py`, `mcp/tool_schema.py`, `infra/config.py`, `infra/google_drive/list.py`, `infra/google_drive/client.py`, `retrieval/ls.py`, `retrieval/ports.py`, `scripts/deploy-cloud-run.sh`, `.env.example`, and tests (AC-FR-021, AC-FR-023, AC-FR-024, FR-001, FR-010, FR-012, FR-030)

---

## Phase 16: Grep coverage per call

- [X] T065 Return one `drive_grep` match per (file, line) in line-oriented text: first hit's `matched_text` and `location.offset`, `location.occurrences` for every hit on that line, so `max_matches` counts lines; Sheets, Slides, CSV and JSON keep one match per hit, in `infra/exact_search/regex.py`, `mcp/tool_schema.py`, `mcp/server.py`, and tests (FR-034, FR-039)
- [X] T066 Raise the `drive_grep` file cap to 200 per call (`GREP_MAX_FILES`); the 20 MB operation cap and the 25 s time cap still bound each call, and `drive_ls` / `drive_find` keep 40, in `domain/budgets.py`, `retrieval/grep.py`, `mcp/tool_schema.py`, and tests (FR-038, FR-104)

---

## Phase 17: Whole-kb grep in fewer calls

- [X] T067 Download small files ahead in `drive_grep` on 8 worker threads (known size up to 2 MB, at most 16 files and 8 MB ahead, within the operation's remaining bytes), keep the scan in size order so matches equal a sequential scan, never download a deferred file, bound each wait by the time left, and give every thread its own authorized connection, in `retrieval/grep.py`, `domain/budgets.py`, `infra/google_drive/client.py`, and tests (FR-031, FR-038, FR-038a)
- [X] T068 Return `next_cursor` after a `max_matches` stop (`file_id:N` inside a file with more matches, the file id when later files remain), make an exact fill with nothing left `COMPLETE`, and accept a cursor with `file_ids` when it names one of them, in `retrieval/grep.py`, `mcp/server.py`, `mcp/tool_schema.py`, and tests (FR-030, FR-039a)
- [X] T069 Return `next_cursor` (last file scanned) when a download is rate-limited after the listing finished, in `retrieval/grep.py` and tests (FR-038a)
- [X] T070 Stop matching folders from consuming `drive_find` `max_results` unless `mime_type` is the folder type, in `retrieval/find.py`, `mcp/server.py`, `mcp/tool_schema.py`, and tests (FR-012)
- [X] T071 Review follow-ups for T067-T070: skip continuation matches without building them (a deep `file_id:N` costs no memory); cap `N` at 10 ASCII digits; search repeated ids once; no `max_matches` cursor when only unsupported files remain, and a continuation left with only unsupported files is `PARTIAL` `unsupported_skipped`; drop deferred ids the cursor revisits; charge Drive's size when known so a file fetched ahead is never deferred; count unsupported files against the download-ahead file budget; do not download ahead while resuming inside a file; cap matching folders in `drive_find` separately, in `retrieval/grep.py`, `infra/exact_search/regex.py`, `retrieval/find.py`, host copy, and tests (FR-012, FR-037, FR-038a, FR-039a)
- [X] T072 Round-2 review follow-ups: every call handles at least one file after a finished listing (a timed-out first download-ahead could livelock a cursor chain); treat the Drive size of Docs, Sheets and Slides as unknown (it is storage, not export length) for sorting, deferral, download-ahead and charging; charge a truncated download the bytes read; never fetch ahead a file the per-file cap would truncate; fix the download-ahead slot count; a continuation whose listing is cut returns its own cursor instead of rescanning; drop deferred ids when a no-cursor stop will be repeated; host copy and spec wording, in `retrieval/grep.py`, `retrieval/find.py`, `mcp/tool_schema.py`, and tests (FR-012, FR-030, FR-038a, FR-039a)
- [X] T073 Round-3 review follow-ups: flag a listing cut when the time cap drops an in-scope file, including the last named id (a named listing cut at the deadline could report a false `EMPTY`/`COMPLETE`); apply the first-file time exemption only after a finished listing; start no download-ahead once the deadline has passed; skip unsupported files before the byte deferral so `deferred_file_ids` only holds files the host can grep; qualify the progress and cursor wording in host copy and specs, in `infra/google_drive/list.py`, `retrieval/grep.py`, `mcp/tool_schema.py`, and tests (FR-037, FR-038, FR-038a, FR-039a)
- [X] T074 Round-4 review follow-ups: a call whose listing is cut by 429 (like one cut by time) scans nothing, so a repeated fresh call never returns a match or deferred id twice; a single-file continuation that gets a 429 returns `PARTIAL` with its own cursor; read the deadline once per file so a file fetched ahead is never downloaded again on the request thread; cursor wording for byte-cap and pre-scan stops, in `retrieval/grep.py`, `mcp/tool_schema.py`, and tests (FR-038a)
- [X] T075 Round-5 review follow-ups: size download-ahead by the `max_matches` room left and the hits per file seen so far, so `max_matches` chains stop re-downloading files fetched ahead; report `max_bytes` only when a file was truncated or deferred (a slice whose last Doc crosses the byte cap is `COMPLETE`/`EMPTY`); host copy wording for rate-limited continuations, in `retrieval/grep.py`, `mcp/tool_schema.py`, and tests (FR-038a)

---

## Phase 18: Allow-list hardening

- [X] T076 Give the Drive port, client and fake `list_subfolders` (`subfolders_query`: folders, trashed included; the client puts up to 40 parents in one query) so Access Control checks each named id against `kb`'s folder tree (`folder_tree`, `is_inside_tree`) and an id outside `kb`, a missing id and an ungranted id take the same Drive calls; refuse at startup an allow-list id that Drive cannot read or reports as a file, a Drive root (alias or real id) or trashed; in deploy, check the newest revision carries the allow-list, route all traffic to it, clear traffic tags and delete every other revision, in `domain/retrieval_scope.py`, `access_control/chain.py`, `access_control/allowed_folder.py`, `retrieval/ports.py`, `infra/google_drive/client.py`, `infra/google_drive/query.py`, `mcp/middleware.py`, `mcp/server.py`, `scripts/deploy-cloud-run.sh`, `tests/fakes/fake_drive.py`, `tests/contract/test_allowed_folder.py`, and `tests/unit/access_control/test_chain.py` (AC-FR-021, FR-001, FR-010, FR-030)
- [X] T077 Read the `kb` folder id in deploy from the Secret Manager secret `DRIVE_ALLOWED_FOLDER_ID` (never from the operator's shell or the repo), refuse a missing or malformed value, and stop printing it; `.env.example` and tests use placeholder ids, and the live kb comparison needs `LIVE_KB_FOLDER_ID`, in `scripts/deploy-cloud-run.sh`, `.env.example`, `tests/contract/test_allowed_folder.py`, and `tests/e2e/test_live_mcp.py` (FR-001, FR-010, FR-030)

---

## Phase 19: Regex time cap

- [X] T078 Run `drive_grep` `regex=true` on the `regex` package with the call's remaining time (at least 0.5 s per file) as the matching timeout, keep stdlib `re` for literals; a timeout stops the scan as `PARTIAL` `max_execution_time` with the matches finished and `next_cursor` in that file (`file_id:N`, else the file handled before it); accept only stdlib `re` syntax and refuse counted repeats that unroll past 10,000 items (the `regex` package writes them out when it compiles) as `INVALID_ARGUMENT`; compile without the pattern cache; cap `pattern` at 512 characters in the schema and `validate_grep_args`; host copy, in `infra/exact_search/regex.py`, `retrieval/grep.py`, `mcp/server.py`, `mcp/tool_schema.py`, `tests/unit/retrieval/test_regex.py`, and `tests/contract/test_drive_grep.py` (FR-031, FR-033, FR-033a, FR-104)

## Phase 20: Structured logs Cloud Logging can read

- [X] T079 `configure_logging()` at the top of `main()`: one stdout handler on the `google_drive_mcp` logger (`propagate=False`) writing one JSON object per line with `severity`, `message` and only allow-listed fields (`request_id`, `tool`, `file_count`, `bytes_processed`, `duration_ms`, `result_count`, `status`, `error_category`, `step_failed`, `category`, `principal_id`, `http_status`, `event`) through `redact()`; `httpx` and `httpcore` at `WARNING` so request URLs (API key, typed email) are never logged; idempotent; uvicorn runs with `access_log=False`; `log_retrieval` logs `status == "ERROR"` at `WARNING`; the Identity Toolkit key goes in `x-goog-api-key`, in `infra/logging.py`, `mcp/server.py`, `infra/billing/email_link.py`, and `tests/unit/test_logging_hygiene.py` (FR-103)

## Phase 21: Large results and Cloud Run limits

- [x] T080 Keep a 20 MB result under Cloud Run's 32 MiB response cap and bound memory per instance: only a `tools/list` answer is buffered and rewritten (`ensure_ascii=False`, batch answers stamped per response), every other `/mcp` answer streams through unchanged; downloads stay in memory with no temp-file copy; at most two downloads over 2 MB or of unknown size (any Workspace export) run at once per process, and one that gets no slot within 10 s is `RATE_LIMITED` (`PARTIAL` with `next_cursor` inside a multi-file grep); a stalled Drive HTTP call gives up after 20 s and is `DRIVE_API_ERROR`; deploy with 1 GiB, concurrency 10 and at most 3 instances; annotate the tools `openWorldHint: false` and stop naming `MCP_AUTH_TOKEN` in `instructions`, in `infra/mcp_auth/chatgpt_compat.py`, `infra/google_drive/export.py`, `infra/google_drive/client.py`, `retrieval/read.py`, `retrieval/grep.py`, `mcp/tool_schema.py`, `scripts/deploy-cloud-run.sh`, `tests/contract/test_large_responses.py`, `tests/contract/test_tool_schemas.py`, `tests/unit/retrieval/test_large_download_slots.py`, and `tests/unit/retrieval/test_drive_http_timeout.py` (FR-038a, FR-093, FR-100, FR-104, FR-106)
- [X] T081 Merge-review fixes: `drive_read` also bounds the JSON-escaped size of the content (twice escaped on the wire) to 30 MiB and returns `PARTIAL` `max_bytes` when it cuts quote- or newline-heavy text, so a 20 MB CSV never exceeds Cloud Run's 32 MiB response cap; a Drive download that stalls (socket timeout, now 30 s) defers that file in a folder grep (`deferred_file_ids`, `PARTIAL` `max_execution_time` when only stalls were set aside) instead of failing the call; a single-file grep still reports `DRIVE_API_ERROR`

## Phase 22: One-line citation

- [X] T082 Answers cite onto-kb in one line (owner decision, 2026-10-04; constitution v2.0.0, Article VIII): the server instructions and all four tool descriptions tell the host to end any answer that uses tool results with the single line `Source: onto-kb connector` and never to list, number or link separate references (file names, ids, `drive:` locators, document URLs, footnotes, per-quote attributions); tool results keep full provenance for the agent's own use. Test `test_answers_cite_onto_kb_in_one_line_only` in `tests/contract/test_tool_schemas.py`; text in `src/google_drive_mcp/mcp/tool_schema.py` (FR-050a, FR-051)

## Phase 23: Examined content first

- [X] T083 Put a folder's own files before its subfolders' (owner decision, 2026-10-04: `kb`'s examined essays are searched and loaded first): `walk_files` records each item's depth, a folder `drive_grep` sorts by depth then known size, listed children are ordered files first then by name (stable `drive_ls` pages; `drive_find` keeps the shallowest matches under `max_results`), and the server instructions tell hosts to start with `kb`'s own files, in `src/google_drive_mcp/infra/google_drive/list.py`, `src/google_drive_mcp/retrieval/grep.py`, `src/google_drive_mcp/mcp/tool_schema.py`, and `tests/contract/test_shallow_first_order.py` (FR-038, FR-038c)

## Phase 24: Stack Exchange quotes keep their link

- [X] T084 Text quoted word for word from Stack Exchange (CC BY-SA 4.0) carries the link to its post beside the quote; everything else still cites `Source: onto-kb connector` once (owner decision, 2026-10-04; constitution v2.1.0, Article VIII): server instructions and all four tool descriptions, in `src/google_drive_mcp/mcp/tool_schema.py` and `tests/contract/test_tool_schemas.py` (FR-050a)
