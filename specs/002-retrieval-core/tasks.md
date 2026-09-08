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
- [X] T009 Implement default resource budgets in `src/google_drive_mcp/domain/budgets.py` (max_files=40, max_bytes_per_file=5_000_000, max_bytes_per_operation=20_000_000, max_matches=50, max_execution_time=25s, max_context_lines=2, max_export_size=5_000_000)
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
- Do not implement a second `RetrievalScope` type or a second parent walk
- Push to `main` unless a PR is requested
- Verify story tests fail before implementation tasks in that phase

---

## Phase 8: Convergence

Remaining work from `/speckit-converge` (2026-09-08). Do not rewrite earlier tasks.

- [ ] T047 Return `status: PARTIAL` with `partial_reason: max_bytes` from `drive_grep` when `fetch_text` truncates a file at `max_bytes` / `max_export_size` instead of searching the prefix and possibly reporting `COMPLETE` in `retrieval/grep.py` (FR-041, FR-104, Article X) (partial)
- [ ] T048 Honor `max_execution_time` during production `GoogleDriveClient` list pagination in `infra/google_drive/client.py` (and surface `PARTIAL` / `max_execution_time`) instead of fetching the full grant/folder into memory before `walk_files` can stop (FR-104, FR-041) (partial)
- [ ] T049 Map a non-integer `drive_ls` `page_token` to `INVALID_ARGUMENT` in `infra/google_drive/list.py` / `retrieval/ls.py` instead of raising `ValueError` (FR-003, FR-060 `INVALID_ARGUMENT`) (partial)
