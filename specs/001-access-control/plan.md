# Implementation Plan: Access Control Boundary

**Branch**: `main` (spec dir `001-access-control`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-access-control/spec.md`

**Downstream**: Retrieval Core (`specs/002-retrieval-core/`) is a conformist consumer of this plan’s chain and error taxonomy.

## Summary

Every MCP call must pass `agent request → MCP authentication → MCP authorization → Google authorization → resource` with no skippable step, no default-allow, and no authority granted by document text. v1 is one Google Drive identity per deployment; MCP callers still authenticate so the endpoint is not anonymous.

Denial split (locked):

- Google grant miss (404 / permission-as-404) → `FILE_NOT_FOUND` (no existence leak, no content).
- v1 `AUTHORIZATION_ERROR` only when the call names **both** `folder_id` and `file_ids` and Google **grants** a named file that `is_within_scope` rejects. `drive_read` / `drive_ls` / `drive_find` never emit `AUTHORIZATION_ERROR` in v1.
- Access Control tests that AUTH case via `evaluate_chain` or a stub that accepts `folder_id` + `file_ids`. Do not implement `drive_grep` here; Retrieval replays the same case on the real tool.

Technical approach: a Python hexagonal MCP server on Cloud Run. Access control is a domain package with no Google client types. MCP bearer auth and Google OAuth refresh-token use are infrastructure adapters. Retrieval tools (next feature) may run only after this chain returns `ALLOW`. Shared `map_google_error()` maps 404/403-as-404 (and single-file 429 with no prefix). Walk 429 is Retrieval completeness (`PARTIAL`), not this mapper.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Official MCP Python SDK (`mcp` 2.x, Streamable HTTP); `google-auth` + `google-api-python-client` (Google adapter only); `pydantic` for request-scoped models; `httpx` for Streamable HTTP contract tests

**Storage**: None persistent. Google refresh token and MCP bearer secret live in the environment/secret manager, not in the app. Request-scoped objects only.

**Testing**: pytest, pytest-asyncio; contract tests for auth failures via `evaluate_chain` / US1 stub (`folder_id` + `file_ids`); unit tests for chain order, `is_within_scope` with an injected parent map, and secret hygiene. Fake Drive counts **metadata** vs **content** I/O separately.

**Target Platform**: Linux, Cloud Run (stateless HTTP). Local stdio optional for inspector, not the production contract.

**Project Type**: MCP web service (stateless)

**Performance Goals**: Correctness over latency. Auth chain overhead must stay small relative to Drive calls. Grant denial (`FILE_NOT_FOUND`) MUST NOT add a second round-trip solely to confirm existence of a file Google already hid. AUTH folder∩file_ids MAY use one metadata `files.get` (caller already named both ids); it MUST NOT export or `get_media`.

**Constraints**: Read-only Google scope `https://www.googleapis.com/auth/drive.readonly`. No write tools registered in this context (Drive client write-method scan is Retrieval). Tokens never logged. Instance may die after each request. Concurrency > 1 on Cloud Run, so credentials are request-scoped. Step 4 MAY touch Drive metadata; content adapters stay off until `ALLOW`.

**Scale/Scope**: One Google identity per deployment; many sequential/concurrent MCP tool calls from one or more authenticated agents sharing that identity.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Fitness line (Art. XV) | Gate |
| --- | --- |
| Drive is authoritative | PASS — Google authorization is the last check; MCP does not grant access Google would deny |
| the server is read-only | PASS — this context registers no mutating tools; Drive client write scan is Retrieval |
| document content is untrusted | PASS — retrieved text is never an input to `AuthorizationDecision` |
| retrieval can iterate | PASS — chain is re-evaluated every call; prior success is not a credential |
| exact search is deterministic | N/A (Retrieval Core) |
| evidence carries provenance | N/A (Retrieval Core) |
| partiality is visible | PASS — auth failures are classified errors, never empty success |
| compute is ephemeral | PASS — auth state re-derived per request |
| no hidden persistent state exists | PASS — no token cache on disk; secrets from env |
| authorization is independently enforced | PASS — chain is explicit, ordered, non-skippable |
| agent reasoning and retrieval mechanics stay separate | PASS — agent justification cannot satisfy any step |
| no RAG index is required for correctness | PASS — not used |

**Post-Phase 1 re-check:** Still PASS. Contracts expose only read-side errors and a bearer-gated MCP surface. AUTH uses metadata get, not content I/O. No cache, no multi-tenant Google identities, no write tools.

## Project Structure

### Documentation (this feature)

```text
specs/001-access-control/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md              # NOT created by /speckit-plan
```

### Source Code (repository root)

Shared with Retrieval Core (one deployable):

```text
src/google_drive_mcp/
├── domain/
│   ├── errors.py              # shared flat taxonomy (ErrorEnvelope)
│   ├── google_errors.py       # map_google_error: 404/403-as-404; single-file 429; not walk 429
│   └── retrieval_scope.py     # RetrievalScope + is_within_scope (parent_lookup port)
├── access_control/
│   ├── chain.py               # ordered evaluation, no Google types
│   ├── principal.py
│   └── decisions.py
├── infra/
│   ├── config.py
│   ├── logging.py
│   ├── mcp_auth/
│   │   └── bearer.py          # MCP caller authentication adapter
│   └── google_auth/
│       └── refresh_token.py   # Drive credential adapter (readonly)
├── mcp/
│   ├── server.py              # composition root; stub accepts folder_id + file_ids until tools.py exists
│   └── middleware.py          # run chain before any tool
tests/
├── fakes/
│   └── fake_drive.py          # one in-memory Drive port + invocation counters
├── contract/
│   └── test_auth_contract.py
├── integration/
│   └── test_request_isolation.py
└── unit/
    └── access_control/
```

**Structure Decision**: Single Python package. Access control owns `access_control/` and auth adapters. Retrieval Core adds tools and Drive content adapters. Domain errors, Google error mapping, and `RetrievalScope` + `is_within_scope` are shared. `mcp/server.py` is the composition root: it mounts `mcp/tools.py` when Retrieval Core registers tools; until then a stub with `folder_id` + `file_ids` proves the AUTH case without implementing grep. One fake Drive port (`tests/fakes/fake_drive.py`) is a counting wrapper over an in-memory store (metadata vs content counters); Retrieval Core populates the store.

## Complexity Tracking

> No constitution violations requiring justification.
