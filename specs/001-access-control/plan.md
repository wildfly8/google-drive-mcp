# Implementation Plan: Access Control Boundary

**Branch**: `main` (spec dir `001-access-control`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-access-control/spec.md`

**Downstream**: Retrieval Core (`specs/002-retrieval-core/`) is a conformist consumer of this plan’s chain and error taxonomy.

## Summary

Every MCP call must pass `agent request → MCP authentication → MCP authorization → Google authorization → resource` with no skippable step, no default-allow, and no authority granted by document text. v1 is one Google Drive identity per deployment; MCP callers still authenticate so the endpoint is not anonymous. Google-grant misses return `FILE_NOT_FOUND` (no existence leak); MCP retrieval-boundary violations return `AUTHORIZATION_ERROR`.

Technical approach: a Python hexagonal MCP server on Cloud Run. Access control is a domain package with no Google client types. MCP bearer auth and Google OAuth refresh-token use are infrastructure adapters. Retrieval tools (next feature) may run only after this chain returns `ALLOW`.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Official MCP Python SDK (`mcp` 2.x, Streamable HTTP); `google-auth` + `google-api-python-client` (Google adapter only); `pydantic` for request-scoped models; `httpx` if needed for transport tests

**Storage**: None persistent. Google refresh token and MCP bearer secret live in the environment/secret manager, not in the app. Request-scoped objects only.

**Testing**: pytest, pytest-asyncio; contract tests for auth failures; unit tests for chain order and leak mapping

**Target Platform**: Linux, Cloud Run (stateless HTTP). Local stdio optional for inspector, not the production contract.

**Project Type**: MCP web service (stateless)

**Performance Goals**: Correctness over latency. Auth chain overhead must stay small relative to Drive calls; no extra Drive round-trip solely to “confirm existence” on grant denial.

**Constraints**: Read-only Google scope `https://www.googleapis.com/auth/drive.readonly`. No write APIs linked. Tokens never logged. Instance may die after each request. Concurrency > 1 on Cloud Run, so credentials are request-scoped.

**Scale/Scope**: One Google identity per deployment; many sequential/concurrent MCP tool calls from one or more authenticated agents sharing that identity.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Fitness line (Art. XV) | Gate |
| --- | --- |
| Drive is authoritative | PASS — Google authorization is the last check; MCP does not grant access Google would deny |
| the server is read-only | PASS — this context has nothing to grant for writes; no mutating Google methods in adapters |
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

**Post-Phase 1 re-check:** Still PASS. Contracts expose only read-side errors and a bearer-gated MCP surface. No cache, no multi-tenant Google identities, no write tools.

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
│   ├── errors.py              # shared flat taxonomy
│   └── retrieval_scope.py     # scope value object
├── access_control/
│   ├── chain.py               # ordered evaluation, no Google types
│   ├── principal.py
│   └── decisions.py
├── infra/
│   ├── mcp_auth/
│   │   └── bearer.py          # MCP caller authentication adapter
│   └── google_auth/
│       └── refresh_token.py   # Drive credential adapter (readonly)
├── mcp/
│   └── middleware.py          # run chain before any tool
tests/
├── contract/
│   └── test_auth_contract.py
├── integration/
│   └── test_chain_google_errors.py
└── unit/
    └── access_control/
```

**Structure Decision**: Single Python package. Access control owns `access_control/` and auth adapters. Retrieval Core adds tools and Drive content adapters. Domain errors are shared so the wire taxonomy stays flat.

## Complexity Tracking

> No constitution violations requiring justification.
