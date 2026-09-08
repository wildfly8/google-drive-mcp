---
description: "Task list for Retrieval Core"
---

# Tasks: Retrieval Core

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

- [ ] T001 Confirm Access Control `pyproject.toml` and `src/google_drive_mcp` exist; add retrieval/test directories `src/google_drive_mcp/{retrieval,infra/google_drive,infra/exact_search}` and `tests/{unit/retrieval,fakes}` with `__init__.py`
- [ ] T002 [P] Add fake Drive fixture module skeleton in `tests/fakes/fake_drive_store.py` (in-memory files/folders, no persistence)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Domain models, ports, budgets, tool registration hook — BLOCKS stories

- [ ] T003 Implement `DriveFile` / folder helpers in `src/google_drive_mcp/domain/drive_file.py`
- [ ] T004 [P] Implement `Provenance` requiring `file_id` in `src/google_drive_mcp/domain/provenance.py`
- [ ] T005 [P] Implement `DocumentContent` (ephemeral) in `src/google_drive_mcp/domain/content.py`
- [ ] T006 [P] Implement `SearchCandidate` (not evidence) in `src/google_drive_mcp/domain/candidates.py`
- [ ] T007 [P] Implement `SearchMatch` in `src/google_drive_mcp/domain/matches.py`
- [ ] T008 Implement operation status `COMPLETE|PARTIAL|EMPTY|ERROR` and `partial_reason` in `src/google_drive_mcp/domain/operation.py` per `specs/002-retrieval-core/contracts/result-status.md`
- [ ] T009 Implement default resource budgets in `src/google_drive_mcp/domain/budgets.py` (max_files=40, max_bytes=5_000_000, max_matches=50, max_execution_time=25s, max_context_lines=2, max_export_size=5_000_000)
- [ ] T010 Define Drive list/export ports (no Google types) in `src/google_drive_mcp/retrieval/ports.py`
- [ ] T011 Register empty MCP tools module wired through access-control middleware in `src/google_drive_mcp/mcp/tools.py`

**Checkpoint**: Foundation ready — user stories can start (requires Access Control chain wrapping tools)

---

## Phase 3: User Story 1 - Discover candidates, then read current content (Priority: P1) 🎯 MVP

**Goal**: `drive_ls` (immediate children), `drive_find` (recursive descendants), `drive_read` (live text + provenance). Unsupported types fail classified, not empty.

**Independent Test**: Fake Drive with a nested Doc. `ls` has no body; `find` on parent includes nested file as candidate; `read` returns text + `file_id`/`modified_time`; binary file → `UNSUPPORTED_MIME_TYPE`.

### Tests for User Story 1

- [ ] T012 [P] [US1] Contract tests for `drive_ls` in `tests/contract/test_drive_ls.py`
- [ ] T013 [P] [US1] Contract tests for `drive_find` (nested descendants, no content field) in `tests/contract/test_drive_find.py`
- [ ] T014 [P] [US1] Contract tests for `drive_read` provenance and unsupported MIME in `tests/contract/test_drive_read.py`

### Implementation for User Story 1

- [ ] T015 [P] [US1] Implement metadata list adapter (immediate children vs descendant walk) in `src/google_drive_mcp/infra/google_drive/list.py`
- [ ] T016 [P] [US1] Implement export/download adapter (Docs/Sheets/Slides map + text/* download) in `src/google_drive_mcp/infra/google_drive/export.py`
- [ ] T017 [US1] Implement `drive_ls` use case in `src/google_drive_mcp/retrieval/ls.py` (no content in output)
- [ ] T018 [US1] Implement `drive_find` use case in `src/google_drive_mcp/retrieval/find.py` (candidates only; recursive folder)
- [ ] T019 [US1] Implement `drive_read` use case in `src/google_drive_mcp/retrieval/read.py` (call-time fetch, provenance required)
- [ ] T020 [US1] Expose `drive_ls`, `drive_find`, `drive_read` in `src/google_drive_mcp/mcp/tools.py` behind chain middleware
- [ ] T021 [US1] Populate `tests/fakes/fake_drive_store.py` with folder, nested Doc/Sheet/Slide, text file, and opaque binary

**Checkpoint**: US1 pytest contract tests pass; discover → read works without grep

---

## Phase 4: User Story 2 - Exact search turns retrieved bytes into evidence (Priority: P1)

**Goal**: `drive_grep` is local exact match on bytes retrieved in this call; deterministic; EMPTY vs fabricated; literal vs regex; case flag.

**Independent Test**: Unique phrase → match + provenance. Missing phrase → `matches: []`, `EMPTY`. Same bytes+params twice → identical matches. `regex` and `case_sensitive` differ as specified.

### Tests for User Story 2

- [ ] T022 [P] [US2] Contract tests for grep matches, EMPTY, literal vs regex, case flag in `tests/contract/test_drive_grep.py`
- [ ] T023 [P] [US2] Unit tests for regex adapter determinism in `tests/unit/retrieval/test_regex.py`

### Implementation for User Story 2

- [ ] T024 [P] [US2] Implement exact-search adapter (`re.escape` vs compile, IGNORECASE) in `src/google_drive_mcp/infra/exact_search/regex.py`
- [ ] T025 [US2] Implement `drive_grep` use case (fetch → search → provenance → discard bytes) in `src/google_drive_mcp/retrieval/grep.py`
- [ ] T026 [US2] Register `drive_grep` in `src/google_drive_mcp/mcp/tools.py`
- [ ] T027 [US2] Add line-context vs 200-char window for non-line formats in `src/google_drive_mcp/retrieval/grep.py`

**Checkpoint**: US2 independently testable; no Drive `fullText` used for grep

---

## Phase 5: User Story 3 - Iterate without a RAG index (Priority: P1)

**Goal**: Multi-step find → read → grep uses live fetches only; no persistent index or leftover exports.

**Independent Test**: Chain tools on fake Drive; grep the repo for vector/embedding stores (none). Temp dirs from exports are gone after the call. Second request does not reuse first request bytes.

### Tests for User Story 3

- [ ] T028 [P] [US3] Integration chain find→read→grep→read→grep in `tests/integration/test_iterative_retrieval.py`
- [ ] T029 [P] [US3] Assert no leftover temp export files after operations in `tests/integration/test_ephemeral_storage.py`

### Implementation for User Story 3

- [ ] T030 [US3] Ensure export/download uses in-memory or `TemporaryDirectory` cleaned in `finally` in `src/google_drive_mcp/infra/google_drive/export.py`
- [ ] T031 [US3] Forbid cross-call content cache (no module-level dict of file_id→bytes) in `src/google_drive_mcp/retrieval/read.py` and `src/google_drive_mcp/retrieval/grep.py`
- [ ] T032 [US3] Add a unit/grep check that `src/` contains no embedding/vector index dependencies in `tests/unit/retrieval/test_no_rag.py`

**Checkpoint**: Iteration works; Art. II/III hold in tests

---

## Phase 6: User Story 4 - Freshness and visible completeness (Priority: P2)

**Goal**: Re-read sees fixture updates; limits yield `PARTIAL` with reason; rate-limit stop is completeness, not silent full success.

**Independent Test**: Mutate fake Drive between reads. `max_matches=1` with two hits → `PARTIAL`. Simulated rate-limit during find/grep → `PARTIAL` or `RATE_LIMITED`, never `EMPTY`/`COMPLETE` by omission.

### Tests for User Story 4

- [ ] T033 [P] [US4] Freshness test (update fixture, second read) in `tests/integration/test_freshness.py`
- [ ] T034 [P] [US4] `PARTIAL` for max_files/max_matches/max_bytes and rate-limit in `tests/contract/test_partial_status.py`

### Implementation for User Story 4

- [ ] T035 [US4] Thread budgets through ls/find/read/grep and set `status`/`partial_reason` in `src/google_drive_mcp/retrieval/{ls,find,read,grep}.py`
- [ ] T036 [US4] Map sustained Google rate-limit during a walk to `PARTIAL` + reason, no silent retry-to-COMPLETE, in `src/google_drive_mcp/infra/google_drive/list.py` and `src/google_drive_mcp/retrieval/grep.py`
- [ ] T037 [US4] Pagination: `drive_ls` `page_token`/`max_results` must not report `COMPLETE` when more children exist in `src/google_drive_mcp/retrieval/ls.py`

**Checkpoint**: Completeness is visible; no stale MCP copy

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T038 [P] Run `specs/002-retrieval-core/quickstart.md` pytest commands and fix gaps
- [ ] T039 [P] Confirm unauthenticated tools never hit fake Drive (reuse Access Control contract) in `tests/contract/test_auth_contract.py`
- [ ] T040 Scan `src/google_drive_mcp/infra/google_drive` for write methods (`create`, `update`, `delete`, `permissions`) and fail the build if found in `tests/unit/retrieval/test_readonly_drive_adapter.py`
- [ ] T041 Dockerfile for Cloud Run serving Streamable HTTP in `Dockerfile` (no document volume, read-only Drive env secrets)

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
- T022–T023 tests in parallel
- T028–T029 in parallel
- T033–T034 in parallel

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
4. **STOP**: contract tests + quickstart steps 1–3, 7–9

### Incremental Delivery

1. US1 discover/read
2. US2 grep
3. US3 ephemeral iteration
4. US4 PARTIAL/freshness
5. Dockerfile polish

---

## Notes

- Tools MUST go through Access Control middleware; do not call Drive adapters from tools directly on AUTH failures
- No embeddings, vector DBs, or persistent file cache
- Push to `main` unless a PR is requested
- Verify story tests fail before implementation tasks in that phase
