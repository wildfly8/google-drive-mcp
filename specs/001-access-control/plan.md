# Implementation Plan: Access Control Boundary

**Branch**: `main` (spec dir `001-access-control`) | **Date**: 2026-09-08 (OAuth 2.1 alignment 2026-09-13) | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-access-control/spec.md`

**Downstream**: Retrieval Core (`specs/002-retrieval-core/`) is a conformist consumer of this plan’s chain and error taxonomy.

## Summary

Every MCP call must pass `agent request → MCP authentication → MCP authorization → Google authorization → resource` with no skippable step, no default-allow, and no authority granted by document text. v1 is one Google Drive identity per deployment; MCP callers still authenticate so the endpoint is not anonymous.

Denial split (locked):

- Google grant miss (404 / permission-as-404) → `FILE_NOT_FOUND` (no existence leak, no content).
- v1 `AUTHORIZATION_ERROR` when Google **grants** a named file that `is_within_scope` rejects: caller named **both** `folder_id` and `file_ids` (`drive_grep` / `evaluate_chain`), or a named id is outside deployment `DRIVE_ALLOWED_FOLDER_ID`.
- Access Control tests the folder∩file_ids AUTH case via `evaluate_chain`. Do not implement `drive_grep` here; Retrieval replays the same case on the real tool.

MCP authentication (locked, AC-FR-012): this Cloud Run origin is both OAuth 2.1 authorization server and MCP resource server. Hosts complete authorization-code + PKCE S256, DCR (`POST /register`), and RFC 9728 discovery, then call `/mcp` with a short-lived access token. `MCP_AUTH_TOKEN` is the consent password only — not a `/mcp` Bearer. Google OAuth (`GOOGLE_*` / authorized-user JSON) is the Drive identity adapter, never the MCP login.

Technical approach: a Python hexagonal MCP server on Cloud Run. Access control is a domain package with no Google client types. MCP OAuth 2.1 (JWT access tokens, in-memory DCR, consent) and Google OAuth refresh-token use are infrastructure adapters. Retrieval tools may run only after this chain returns `ALLOW`. Shared `map_google_error()` maps 404/403-as-404 (and single-file 429 with no prefix). Walk 429 is Retrieval completeness (`PARTIAL`), not this mapper.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Official MCP Python SDK (`mcp` 2.x, Streamable HTTP); `google-auth` + `google-api-python-client` (Google adapter only); `pydantic` for request-scoped models; `httpx` for Streamable HTTP contract tests

**Storage**: None persistent for Drive content. Google refresh token and the resource-owner consent password live in Secret Manager. MCP access, refresh, and authorization-code values are HS256 JWTs (verifiable on any instance). DCR client records and used-code / revocation `jti` sets are in-memory auth protocol state (Article III exception; hosts re-register).

**Testing**: pytest, pytest-asyncio; contract tests for auth failures via `evaluate_chain` (`folder_id` + `file_ids`); Streamable HTTP tests for RFC 9728 / AS metadata, DCR+PKCE token issue, and rejection of `MCP_AUTH_TOKEN` as Bearer; unit tests for JWT verify, chain order, `is_within_scope` with an injected parent map, and secret hygiene. Fake Drive counts **metadata** vs **content** I/O separately. Tests may set `MCP_OAUTH_AUTO_APPROVE=true` / `Settings.for_tests()`; production MUST leave auto-approve off.

**Target Platform**: Linux, Cloud Run (stateless HTTP). Local stdio optional for inspector, not the production contract.

**Project Type**: MCP web service (stateless)

**Performance Goals**: Correctness over latency. Auth chain overhead must stay small relative to Drive calls. Grant denial (`FILE_NOT_FOUND`) MUST NOT add a second round-trip solely to confirm existence of a file Google already hid. AUTH folder∩file_ids MAY use one metadata `files.get` (caller already named both ids); it MUST NOT export or `get_media`.

**Constraints**: Read-only Google scope `https://www.googleapis.com/auth/drive.readonly` (three-field refresh mint). MCP OAuth scope on issued access tokens is `drive.read` (not a Google scope). No write tools registered in this context (Drive client write-method scan is Retrieval). Tokens never logged. Instance may die after each request. Concurrency > 1 on Cloud Run, so Google credentials are request-scoped. HTTP serving requires `MCP_PUBLIC_URL` (HTTPS origin, no path, no `/mcp` suffix). Step 4 MAY touch Drive metadata; content adapters stay off until `ALLOW`.

### MCP OAuth 2.1 (plan-level, spec AC-FR-012)

| Choice | Value |
| --- | --- |
| Combined AS + RS | Same Cloud Run origin (`mcp` SDK `AuthSettings` + `DriveMcpOAuthProvider`) |
| Access token | HS256 JWT; `aud` / RFC 8707 resource = `{issuer}/mcp`; scope `drive.read` |
| Signing key | `MCP_OAUTH_SIGNING_KEY` if set, else `SHA-256("mcp-oauth-jwt-v1:" + MCP_AUTH_TOKEN)` |
| Default TTLs | access 3600s; refresh 2592000s; authorization code 120s |
| Consent | Production `GET`/`POST /consent`; password = `MCP_AUTH_TOKEN` (HMAC compare). Tests may auto-approve |
| PKCE | S256 required (MCP SDK authorize/token handlers) |
| DCR | `POST /register`; client map is process memory |
| `/mcp` Bearer | `verify_access_claims` only — `MCP_AUTH_TOKEN` MUST 401 |

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
| compute is ephemeral | PASS — JWT access tokens verify on any instance; Google creds minted per request |
| no hidden persistent state exists | PASS — no token cache on disk; secrets from env; in-memory DCR is a documented Article III exception |
| authorization is independently enforced | PASS — chain is explicit, ordered, non-skippable |
| agent reasoning and retrieval mechanics stay separate | PASS — agent justification cannot satisfy any step |
| no RAG index is required for correctness | PASS — not used |

**Post-Phase 1 re-check:** Still PASS. Contracts expose only read-side errors and an OAuth 2.1-gated MCP surface. AUTH uses metadata get, not content I/O. No cache, no multi-tenant Google identities, no write tools.

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
│   │   ├── bearer.py          # extract Bearer; HMAC-compare MCP_AUTH_TOKEN on /consent only
│   │   ├── jwt.py             # HS256 encode/decode (alg=none rejected)
│   │   ├── tokens.py          # mint/verify access, refresh, code, consent ticket
│   │   ├── provider.py        # DCR + auth-code + PKCE OAuthAuthorizationServerProvider
│   │   └── consent.py         # GET/POST /consent
│   └── google_auth/
│       └── refresh_token.py   # Drive credential adapter (readonly)
├── mcp/
│   ├── server.py              # composition root: AuthSettings, provider, /consent, mounts tools.py
│   └── middleware.py          # run chain before any tool
tests/
├── fakes/
│   └── fake_drive.py          # one in-memory Drive port + invocation counters
├── contract/
│   ├── test_auth_contract.py
│   ├── test_oauth_http.py
│   └── test_streamable_http_auth.py
├── integration/
│   └── test_request_isolation.py
└── unit/
    └── access_control/        # includes test_oauth_jwt.py
```

**Structure Decision**: Single Python package. Access control owns `access_control/` and MCP/Google auth adapters. Retrieval Core adds tools and Drive content adapters. Domain errors, Google error mapping, and `RetrievalScope` + `is_within_scope` are shared. `mcp/server.py` is the only composition root: it wires OAuth 2.1 (`AuthSettings` + `DriveMcpOAuthProvider` + `/consent`) and mounts `mcp/tools.py`. Folder∩file_ids AUTH is proven with `evaluate_chain` (and Retrieval’s `drive_grep`). One fake Drive port (`tests/fakes/fake_drive.py`) is a counting wrapper over an in-memory store (metadata vs content counters); Retrieval Core populates the store.

## Complexity Tracking

> No constitution violations requiring justification.
