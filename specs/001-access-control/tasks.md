---
description: "Task list for Access Control Boundary"
---

# Tasks: Access Control Boundary

**Branch**: `main` (spec dir `specs/001-access-control`)

**Input**: Design documents from `/specs/001-access-control/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — plan.md and quickstart.md require pytest contract tests for auth failures.

**Organization**: User stories from spec.md (US1–US3). Shared package with Retrieval Core.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3 map to spec user stories
- Include exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Python package skeleton used by both features

- [X] T001 Create package directories `src/google_drive_mcp/{domain,access_control,infra/mcp_auth,infra/google_auth,mcp}` and `tests/{contract,integration,unit/access_control,fakes}` with empty `__init__.py` files
- [X] T002 Initialize Python 3.12 project with `pyproject.toml` dependencies `mcp`, `google-auth`, `google-api-python-client`, `pydantic`, `httpx`, `pytest`, `pytest-asyncio` and package layout `src/`
- [X] T003 [P] Configure Ruff and pytest in `pyproject.toml` (src layout, `pythonpath`, asyncio mode)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared domain types and config that every story uses

**⚠️ CRITICAL**: No user story work until this phase is complete

- [X] T004 Implement shared error taxonomy and `ErrorEnvelope` in `src/google_drive_mcp/domain/errors.py` per `specs/001-access-control/contracts/error-taxonomy.md` (canonical enum; Retrieval Core must not fork it)
- [X] T005 [P] Implement `RetrievalScope` (`default_whole_grant`, `folder_id`, `file_ids`) and `is_within_scope(file_id, scope, parent_lookup)` in `src/google_drive_mcp/domain/retrieval_scope.py` per Retrieval Core data-model; parent_lookup is a port (tests inject a map; production uses Drive metadata)
- [X] T006 [P] Implement `Principal` in `src/google_drive_mcp/access_control/principal.py` (deployment label only, v1 single identity)
- [X] T007 [P] Implement `AuthorizationDecision` in `src/google_drive_mcp/access_control/decisions.py`
- [X] T008 Load env secrets (`MCP_AUTH_TOKEN`, `MCP_PRINCIPAL_ID`, `GOOGLE_*`) without logging values in `src/google_drive_mcp/infra/config.py`
- [X] T009 Add structured logging helper that redacts secrets in `src/google_drive_mcp/infra/logging.py`
- [X] T010 Create MCP server composition root (Streamable HTTP) in `src/google_drive_mcp/mcp/server.py` that mounts `mcp/tools.py` when present; until then a stub tool that accepts `folder_id` and `file_ids` (AUTH test vehicle; not `drive_grep`)

**Checkpoint**: Foundation ready — user stories can start

---

## Phase 3: User Story 1 - Every call must clear the same authority chain (Priority: P1) 🎯 MVP

**Goal**: Ordered chain `MCP auth → MCP scope → Google auth → resource` with classified errors; Drive is never called on earlier failures.

**Independent Test**: Unauthenticated call → `AUTHENTICATION_ERROR` and Drive **content** count 0. Valid bearer + Google not-found → `FILE_NOT_FOUND` with no file metadata. Valid bearer + stub/`evaluate_chain` with `folder_id` + granted `file_id` outside that folder → `AUTHORIZATION_ERROR`, metadata get allowed, export/`get_media` count 0. A `file_id`-only call that Google misses is `FILE_NOT_FOUND`, never `AUTHORIZATION_ERROR`. Do not implement `drive_grep` here.

### Tests for User Story 1

- [X] T011 [P] [US1] Contract tests for missing/invalid bearer, Google-miss → `FILE_NOT_FOUND`, and folder∩file_ids AUTH mapping via `evaluate_chain` or the US1 stub (args: `folder_id` + `file_ids`, not a `drive_grep` tool) in `tests/contract/test_auth_contract.py` (assert content I/O = 0 on AUTH; metadata get may be 1)
- [X] T012 [P] [US1] Unit tests that chain steps are non-skippable, prior ALLOW is not reused, and `is_within_scope` uses an injected parent map (no Drive) in `tests/unit/access_control/test_chain.py`

### Implementation for User Story 1

- [X] T013 [P] [US1] Implement constant-time MCP bearer comparison in `src/google_drive_mcp/infra/mcp_auth/bearer.py`
- [X] T014 [P] [US1] Implement read-only Google credential mint (refresh token → access token, request-scoped) in `src/google_drive_mcp/infra/google_auth/refresh_token.py`
- [X] T015 [US1] Implement ordered `evaluate_chain` with ports for authn/authz/google in `src/google_drive_mcp/access_control/chain.py` (depends on T004–T007, T013)
- [X] T016 [US1] Implement `map_google_error` in `src/google_drive_mcp/domain/google_errors.py`: 404 / permission-as-404 → `FILE_NOT_FOUND` (no name/content); optional single-file HTTP 429 with no prefix → `RATE_LIMITED`. MUST NOT map list/find/grep **walk** 429 (those are `PARTIAL` in Retrieval T036)
- [X] T017 [US1] MCP middleware: run chain before any tool; `server.py` mounts stub or `tools.py`; stub accepts `folder_id` and `file_ids` (same scope shape as later `drive_grep`) and only runs its body on ALLOW in `src/google_drive_mcp/mcp/middleware.py`
- [X] T018 [US1] Single fake Drive port with metadata vs content invocation counters in `tests/fakes/fake_drive.py` (in-memory store skeleton; Retrieval Core populates files)

**Checkpoint**: US1 independently testable via `uv run pytest tests/contract/test_auth_contract.py tests/unit/access_control/test_chain.py`

---

## Phase 4: User Story 2 - Document text cannot grant authority (Priority: P1)

**Goal**: Retrieved text is not an input to `AuthorizationDecision`. No write/share/delete capability exists to misuse.

**Independent Test**: Feed adversarial document body into a subsequent call; chain outcome unchanged. `infra/google_auth` and MCP registration expose no mutating tools or write OAuth scopes (T020). Drive client write-method scan is Retrieval Core T040, not this story.

### Tests for User Story 2

- [X] T019 [P] [US2] Unit test that chain API does not accept document content as a decision input in `tests/unit/access_control/test_untrusted_content.py`
- [X] T020 [P] [US2] Static/unit test that `infra/google_auth` and MCP registration forbid mutating tools/scopes in `tests/unit/access_control/test_readonly_auth_adapters.py` (Drive client write-method scan is Retrieval Core T040, not this task)

### Implementation for User Story 2

- [X] T021 [US2] Keep `evaluate_chain` signature free of content/rationale parameters in `src/google_drive_mcp/access_control/chain.py`
- [X] T022 [US2] Restrict `src/google_drive_mcp/infra/google_auth/refresh_token.py` and any Drive client factory to readonly token scope `https://www.googleapis.com/auth/drive.readonly`
- [X] T023 [US2] Document structural read-only guarantee (no mutating tools registered) in `src/google_drive_mcp/mcp/server.py`; keep this file as the only composition root

**Checkpoint**: US2 tests pass; adversarial phrasing cannot change decisions

---

## Phase 5: User Story 3 - Credentials stay isolated and secret (Priority: P2)

**Goal**: Request-scoped credentials; logs/errors never contain tokens; concurrent requests do not share leftover auth state.

**Independent Test**: Capture logs and error JSON after success and failure — zero token substrings. Two overlapping requests use distinct credential objects.

### Tests for User Story 3

- [X] T024 [P] [US3] Tests that responses and logs omit bearer/refresh/access tokens in `tests/unit/access_control/test_secret_hygiene.py`
- [X] T025 [P] [US3] Concurrent-request isolation test in `tests/integration/test_request_isolation.py`

### Implementation for User Story 3

- [X] T026 [US3] Bind Google client/credential to request context, not a process global, in `src/google_drive_mcp/infra/google_auth/refresh_token.py`
- [X] T027 [US3] Ensure `ErrorEnvelope` and logging helpers in `src/google_drive_mcp/domain/errors.py` and `src/google_drive_mcp/infra/logging.py` never interpolate secrets
- [X] T028 [US3] Log only `request_id`, `MCP_PRINCIPAL_ID`, `step_failed`, `category` from middleware in `src/google_drive_mcp/mcp/middleware.py`

**Checkpoint**: US3 independent; quickstart secret-hygiene checks pass

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T029 [P] Align `specs/001-access-control/quickstart.md` commands with actual pytest paths
- [X] T030 Run `uv run pytest tests/contract/test_auth_contract.py tests/unit/access_control tests/integration/test_request_isolation.py -q` and fix failures (do not glob all of `tests/contract` or `tests/integration`; Retrieval owns those extra files)
- [X] T031 [P] Add `.env.example` listing `MCP_AUTH_TOKEN`, `MCP_PRINCIPAL_ID`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` with no real secrets

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all stories
- **US1 (Phase 3)**: Depends on Foundational — MVP
- **US2 (Phase 4)**: Depends on Foundational; uses chain from US1
- **US3 (Phase 5)**: Depends on Foundational; hardens US1 adapters
- **Polish**: After desired stories

### User Story Dependencies

- **US1 (P1)**: After Phase 2 — no other stories
- **US2 (P1)**: After US1 chain exists (same files `chain.py` / server) — independently testable
- **US3 (P2)**: After US1 credential adapters exist — independently testable

### Parallel Opportunities

- T003 with remaining setup after T001/T002
- T005, T006, T007 in parallel after T004
- T011 + T012 in parallel; T013 + T014 in parallel
- T019 + T020 in parallel
- T024 + T025 in parallel

---

## Parallel Example: User Story 1

```bash
# Tests (after they are written, before implementation):
Task: "Contract tests in tests/contract/test_auth_contract.py"
Task: "Unit tests in tests/unit/access_control/test_chain.py"

# Adapters in parallel:
Task: "Bearer auth in src/google_drive_mcp/infra/mcp_auth/bearer.py"
Task: "Refresh token in src/google_drive_mcp/infra/google_auth/refresh_token.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup
2. Phase 2 Foundational
3. Phase 3 US1
4. **STOP**: pytest contract + chain unit tests
5. Retrieval Core tasks can start (needs ALLOW path)

### Incremental Delivery

1. Setup + Foundational
2. US1 → auth chain MVP
3. US2 → untrusted content / read-only structure
4. US3 → secret hygiene / request scope
5. Polish + quickstart

---

## Notes

- Do not implement `drive_ls`/`find`/`read`/`grep` here — those are Retrieval Core
- AUTH folder∩file_ids tests use `evaluate_chain` or the US1 stub (`folder_id` + `file_ids`); Retrieval T039 replays the same case on real `drive_grep`
- `server.py` is the composition root; do not register a second server in Retrieval Core
- One fake: `tests/fakes/fake_drive.py` (do not add `fake_google_drive.py`)
- Commit after each task or logical group (push to `main` unless a PR is requested)
- Verify US1 tests fail before T015–T017 implementation

---

## Phase 7: Convergence

Remaining work from `/speckit-converge` (2026-09-08). Do not rewrite earlier tasks.

- [ ] T032 CRITICAL Wire the Streamable HTTP `Authorization` Bearer into the chain on the production entrypoint (`mcp/server.py` `main()` / Dockerfile `python -m google_drive_mcp`). `_wrap_auth` exists on `streamable_app()` but `main()` calls `server.run()` without it, so `get_authorization()` is always unset and every live call is `AUTHENTICATION_ERROR` (fail-closed: unauthenticated access is blocked, but AC-FR-010 / AC-FR-001 / US1 ALLOW cannot succeed on Cloud Run) (AC-FR-010, AC-FR-001, US1) (missing)
- [ ] T033 Bind the production Drive client to the per-request minted credentials in `infra/google_auth/refresh_token.py` and `mcp/server.py` `build_runtime`: today `GoogleDriveClient` is constructed once at process start while `mint_readonly_credentials()` results are unused for I/O (AC-FR-030, SC-004, plan: request-scoped credentials) (partial)
- [ ] T034 Unregister `scope_probe` from production `MCPServer` in `mcp/server.py` now that `drive_grep` exists; keep AUTH coverage on `evaluate_chain` / `drive_grep` only (Constitution V, Retrieval FR-090, AC T010 leftover) (unrequested)
- [ ] T035 Add httpx Streamable HTTP contract tests that send `Authorization: Bearer` and assert missing/invalid bearer never reaches Drive I/O (plan: Streamable HTTP contract tests, AC-FR-010) (partial)
- [ ] T036 Map non-404/403 Google failures during `evaluate_chain` to `DRIVE_API_ERROR` (or re-raise) instead of collapsing every `DomainError` into `FILE_NOT_FOUND` in `access_control/chain.py` (AC-FR-050, error-taxonomy.md) (partial)
