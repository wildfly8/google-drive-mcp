# Implementation Plan: Access Control Boundary

**Branch**: `main` (spec dir `001-access-control`) | **Date**: 2026-09-08 (OAuth 2.1 alignment 2026-09-13; allow-list tree check 2026-09-29; paid Allow page 2026-10-01) | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-access-control/spec.md`

**Downstream**: Retrieval Core (`specs/002-retrieval-core/`) is a conformist consumer of this plan’s chain and error taxonomy.

## Summary

Every MCP call must pass `agent request → MCP authentication → MCP authorization → Google authorization → resource` with no skippable step, no default-allow, and no authority granted by document text. v1 is one Google Drive identity per deployment; MCP callers still authenticate so the endpoint is not anonymous.

Denial split (locked):

- A named id not proven to be deployment `DRIVE_ALLOWED_FOLDER_ID` (`kb`) or a descendant → `AUTHORIZATION_ERROR` (`outside_allowed_folder`), whether it lies outside `kb`, does not exist, or Google does not grant it. One reply for all three, so no existence leak and no content.
- `AUTHORIZATION_ERROR` also when no allow-list is configured (`no_allowed_folder`), when a call names no folder or file after the rewrite (`whole_grant_refused`), and when the caller names **both** `folder_id` and `file_ids` (`drive_grep` / `evaluate_chain`) and Google grants a named file that `is_inside_tree` places outside that folder (`file_outside_folder`).
- How step 4 decides (2026-09-29): list the allow-list folder’s subfolder tree from the top down (`folder_tree`, folders only, trashed included), then one metadata `files.get` per named id, then decide membership in memory (`is_inside_tree`). An id outside `kb`, a missing id, and an ungranted id make the same Drive calls, so timing does not leak existence. No lookup climbs above `kb`. When the only named id is `kb` itself, the tree is not listed.
- In the chain, a 404 / permission-as-404 while listing the allow-list folder’s own tree (the folder was removed or unshared after startup) → `FILE_NOT_FOUND` (`google_grant_miss`). After `ALLOW`, a 404 on an id the chain proved inside `kb` → `FILE_NOT_FOUND` through the same `map_google_error()`. No content either way.
- Access Control tests the folder∩file_ids AUTH case via `evaluate_chain` and the in-process `scope_probe` tool name (not registered on the MCP server). Do not implement `drive_grep` here; Retrieval replays the same case on the real tool.

MCP authentication (locked, AC-FR-012): this Cloud Run origin is both OAuth 2.1 authorization server and MCP resource server. Hosts complete authorization-code + PKCE S256, DCR (`POST /register`) or CIMD, and RFC 9728 discovery, then call `/mcp` with a short-lived access token. `MCP_AUTH_TOKEN` is the consent password only — not a `/mcp` Bearer. Google OAuth (`GOOGLE_*` / authorized-user JSON) is the Drive identity adapter, never the MCP login.

Paid Connect (locked, AC-FR-013, 2026-10-01): with the 004 paywall on, a browser without an active subscription is sent to `/subscribe`. For an active subscriber, `/authorize` always mints a consent ticket that names the subscriber by a keyed hash (`scid_hash`; the ticket URL lands in request logs, so never the customer id) and redirects to the `/consent` Allow page. `POST /consent` issues the code, for the browser’s own `scid`, only when the hash of the browser’s entitlement matches and the processor reports it active. `MCP_OAUTH_AUTO_APPROVE` only skips consent when the paywall is off.

Technical approach: a Python hexagonal MCP server on Cloud Run. Access control is a domain package with no Google client types. MCP OAuth 2.1 (JWT access tokens, stateless DCR, consent) and Google OAuth refresh-token use are infrastructure adapters. Retrieval tools may run only after this chain returns `ALLOW`. Shared `map_google_error()` maps 404/403-as-404 (and single-file 429 with no prefix). Walk 429 is Retrieval completeness (`PARTIAL`), not this mapper.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Official MCP Python SDK (`mcp` 2.x, Streamable HTTP); `google-auth` + `google-api-python-client` (Google adapter only); `pydantic` for request-scoped models; `httpx` for CIMD fetches and Streamable HTTP contract tests

**Storage**: None persistent for Drive content. Google refresh token (or authorized-user JSON), the resource-owner consent password, and the `kb` folder id (`DRIVE_ALLOWED_FOLDER_ID`) live in Secret Manager. MCP access, refresh, authorization-code, consent-ticket, and DCR `client_id` values are HS256 JWTs (verifiable on any instance; DCR hosts do not re-register). CIMD client records fetched on demand and used-code / revocation `jti` maps are bounded in-memory auth protocol state (Article III exception).

**Testing**: pytest, pytest-asyncio; contract tests for auth failures via `evaluate_chain` (`folder_id` + `file_ids`) and the in-process `scope_probe` tool; allow-list tests for the omitted-folder rewrite, equal Drive calls for outside / missing / ungranted ids, and the startup checks; Streamable HTTP tests for RFC 9728 / AS metadata, DCR+PKCE and CIMD token issue, the consent password, and rejection of `MCP_AUTH_TOKEN` as Bearer; OAuth limit tests (`tests/contract/test_oauth_limits.py`: a DCR client used on a fresh app instance, tampered `client_id`, metadata limits, CIMD bounds, body caps, rate limits, ticket privacy, loopback verdict); paywall contract tests for the Allow page (004); unit tests for JWT verify, chain order, `is_within_scope` with an injected parent map, and secret hygiene. Fake Drive counts **metadata**, **subfolder listing**, and **content** I/O separately. `Settings.for_tests()` sets `MCP_OAUTH_AUTO_APPROVE=true` with the paywall off. Production (`scripts/deploy-cloud-run.sh`) also sets it to true, but the deploy refuses to run without the paywall, and with the paywall on auto-approve is ignored. A deploy without the paywall MUST leave auto-approve off unless knowing the URL is meant to be enough to Connect.

**Target Platform**: Linux, Cloud Run (stateless HTTP). Local stdio optional for inspector, not the production contract.

**Build and CI** (2026-10-01; now owned by [`specs/005-delivery-pipeline/`](../005-delivery-pipeline/spec.md)): The image is built from `uv.lock`. A builder stage with `uv` pinned by version and digest runs `uv sync --frozen --no-dev --no-install-project` into `/app/.venv` (hashes checked; no build backend is fetched). The slim runtime stage copies the venv and `src` (`PYTHONPATH=/app/src`) and runs as uid 10001. `pyproject.toml` bounds `mcp>=2.2,<3`, declares `starlette` and `uvicorn` (imported directly), and keeps `pytest`, `pytest-asyncio` and `ruff` in the `dev` dependency group, out of the image. `.github/workflows/ci.yml` (push and pull request) runs `uv lock --check`, `uv sync --frozen`, `uv run pytest -q --ignore=tests/e2e`, `uv run ruff check --select F,E9 src tests`, and `pip-audit` over the hashed `uv export --frozen --no-dev`. Dependabot proposes weekly uv, docker and github-actions updates. `scripts/deploy-cloud-run.sh` refuses a git tree with uncommitted or untracked files (`ALLOW_DIRTY=1` overrides) and, when `uv` is on PATH, runs `uv run --locked pytest -q --ignore=tests/e2e` (`SKIP_TESTS=1` skips) before it touches the project with gcloud.

**Project Type**: MCP web service (stateless)

**Performance Goals**: Correctness over latency. Auth chain overhead must stay small relative to Drive calls. Step 4 costs one folder-only `files.list` per level of the allow-list tree (one more per extra 40 folders on a level, since a query holds at most 40 parent ids; 1000 results per page) plus one metadata `files.get` per named id, and the same calls for any id, so denying an ungranted or missing id adds no round-trip that would reveal existence. AUTH folder∩file_ids reuses those gets; it MUST NOT export or `get_media`.

**Constraints**: Read-only Google scope `https://www.googleapis.com/auth/drive.readonly` (three-field refresh mint). `GOOGLE_AUTHORIZED_USER_JSON`, preferred when set, keeps the scopes on the blob, so the operator must keep that grant read-only. MCP OAuth scope on issued access tokens is `drive.read` (not a Google scope). No write tools registered in this context (Drive client write-method scan is Retrieval). Tokens never logged. Instance may die after each request. Concurrency > 1 on Cloud Run (deploy: 10 requests per instance, at most 3 instances, overridable with `CLOUD_RUN_CONCURRENCY` / `CLOUD_RUN_MAX_INSTANCES`; 1 GiB; 60 s request timeout; a cost ceiling and room for two 20 MB reads at once, Retrieval FR-106), so Google credentials are request-scoped. HTTP serving requires `MCP_PUBLIC_URL` (HTTPS origin, no path, no `/mcp` suffix). Step 4 MAY touch Drive metadata (folder listings of the allow-list tree and `files.get`); content adapters stay off until `ALLOW`. Per request, Google credentials are minted only after steps 2–3 pass; the startup folder check below mints once. `DRIVE_ALLOWED_FOLDER_ID` is required: the server refuses to start when it is unset, blank, an alias such as `root` / `appDataFolder`, or not a plain id (`Settings.require_allowed_folder`, `[A-Za-z0-9_-]{1,128}`). `main()` then reads the id from Drive (`check_allowed_folder`) and refuses to serve unless it is a readable folder that has a parent, is not the real My Drive root id, and is not trashed (shared-drive roots have no parent). The deploy script reads the id from the Secret Manager secret `DRIVE_ALLOWED_FOLDER_ID`, refuses to deploy without it, and refuses to deploy without the Stripe key and price.

### MCP OAuth 2.1 (plan-level, spec AC-FR-012)

| Choice | Value |
| --- | --- |
| Combined AS + RS | Same Cloud Run origin (`mcp` SDK `AuthSettings` + `DriveMcpOAuthProvider`) |
| Access token | HS256 JWT; `aud` / RFC 8707 resource = `{issuer}/mcp`; scope `drive.read` |
| Claims | `typ` (`access` / `refresh` / `code` / `ticket`), `iss`, `aud`, `sub` = `MCP_PRINCIPAL_ID`, `client_id`, `scope`, `iat`, `exp`, `jti`, `resource`. Access and refresh may add `cid` (Connect id, 003); access, refresh, and code may add `scid` (Stripe customer, 004), and the ticket instead adds `scid_hash` (base64url `HMAC-SHA256(key, "consent-scid:" + scid)`). Code and ticket add `redirect_uri`, `redirect_uri_provided_explicitly`, `code_challenge`; the ticket adds `state`. A DCR `client_id` is a JWT with `typ` = `dcr`, `aud` = issuer, `iat`, a random `jti`, and the registration (see DCR) |
| Verify | Signature, `typ`, `iss`, `aud`, unexpired `exp`, scope `drive.read`, non-empty `client_id` and `jti`. Header must be `alg=HS256`, `typ=JWT`; tokens over 8 KiB are rejected. On `/mcp` the `Bearer ` prefix is optional (`extract_bearer`) |
| Signing key | `SHA-256(MCP_OAUTH_SIGNING_KEY)` if set, else `SHA-256("mcp-oauth-jwt-v1:" + MCP_AUTH_TOKEN)`. The same key signs consent tickets, DCR `client_id` values, and the 004 entitlement and email-link cookies; `typ` and `aud` keep them apart. It also derives DCR client secrets and the ticket `scid_hash` (HMAC with a distinct label each) |
| Default TTLs | access 3600s; refresh 2592000s (a paid refresh token with `scid`: 400 days, and each refresh re-checks the processor); authorization code 120s; consent ticket 600s (`aud` = `{issuer}/consent`) |
| Consent (paywall off) | `GET`/`POST /consent` password page; password = `MCP_AUTH_TOKEN` (HMAC compare). Skipped when `MCP_OAUTH_AUTO_APPROVE=true` |
| Consent (paywall on) | Unpaid `GET /authorize` → `/subscribe`. Entitled → `/consent` Allow page (client name, return host marked a known AI chat app address, a program on this computer for a loopback host, or neither; no password). `POST /consent` needs the keyed hash of the browser’s entitlement `scid` = ticket `scid_hash` and an active subscription, else the expired page (400); the code carries the browser’s `scid`. Code exchange and refresh re-check the subscription (`invalid_grant`). Auto-approve ignored |
| Consent page headers | `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'` |
| PKCE | S256 required (MCP SDK authorize/token handlers) |
| Scope and resource | Only `drive.read`; any other scope is `invalid_scope`. A `resource` other than this server’s `/mcp` URL is `invalid_target` |
| DCR | `POST /register`, stateless (`infra/mcp_auth/dcr.py`): the provider replaces the SDK’s random `client_id` with a signed record (`ru`, `cn` first 100 characters, `gt`, `rt`, `am`, `sc`) and, for secret auth methods, sets `client_secret` = hex `HMAC-SHA256(key, "dcr-secret:" + client_id)`, `client_secret_expires_at` = 0. The SDK `RegistrationHandler` returns that same object. `get_client` verifies and decodes it on any instance (LRU of 1000). Limits: name ≤ 200, ≤ 5 redirect URIs of ≤ 512, ≤ 5 contacts of ≤ 254, ≤ 16 KB, `client_id` ≤ 4096 characters, else 400 `invalid_client_metadata` |
| CIMD | `client_id` HTTPS URLs on `chatgpt.com`, `claude.ai`, `claude.com` (and `www.`) only, at most 512 characters; fetched on demand (5 s, no redirects); a same-shape public client is synthesized when the fetch fails and kept 5 minutes; records are an LRU of 2000 per instance (`CimdClients`); granted `drive.read`; public client (`none`) |
| Codes and refresh | A code is single-use per instance (used `jti` map). Each refresh rotates and revokes the old refresh `jti` on that instance. Both maps hold `jti` → `exp` and drop expired entries on insert |
| Request limits | `mcp/limits.py`, the outermost middleware: bodies over 4 MiB (`/mcp`), 1 MiB (`/webhooks/stripe`), or 64 KB (elsewhere) → 413 before any route; per client address (last `X-Forwarded-For` entry) `POST /register` 20/hour, `POST /token` 600/minute (hosts refresh from shared server addresses), `GET`+`POST /authorize` 120/minute → 429 + `Retry-After` |
| Revocation | `POST /revoke` (RFC 7009) adds the `jti` to that instance’s memory; code and refresh exchange on that instance honor it. The MCP SDK handler requires a `client_secret` form field, so a public client that omits it gets HTTP 400 (`invalid_request`) |
| `/mcp` Bearer | `verify_access_claims` only (JWT; the revoked `jti` set and the processor are not consulted, so an access token works until it expires) — `MCP_AUTH_TOKEN` MUST 401 |
| Mixed auth | Only a `tools/call` that names a `drive_*` tool needs a Bearer; `initialize`, `tools/list`, other JSON-RPC methods, and CORS preflight do not. Such a call without a valid Bearer → HTTP 401 + `WWW-Authenticate` (`scope="drive.read"`, `resource_metadata` = origin `/.well-known/oauth-protected-resource`). `GET /mcp` → 405 with the same challenge. Only a `tools/list` answer is rewritten (to stamp `securitySchemes`); every other answer passes through unchanged |

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
| evidence carries provenance to the agent; answers cite the connector once | N/A (Retrieval Core) |
| partiality is visible | PASS — auth failures are classified errors, never empty success |
| compute is ephemeral | PASS — JWT access tokens verify on any instance; Google creds minted per request |
| no hidden persistent state exists | PASS — no token cache on disk; secrets from env; DCR is stateless (signed `client_id`); bounded in-memory CIMD records and `jti` maps are a documented Article III exception |
| authorization is independently enforced | PASS — chain is explicit, ordered, non-skippable |
| agent reasoning and retrieval mechanics stay separate | PASS — agent justification cannot satisfy any step |
| no RAG index is required for correctness | PASS — not used |

**Post-Phase 1 re-check:** Still PASS. Contracts expose only read-side errors and an OAuth 2.1-gated MCP surface. AUTH uses folder listings of the allow-list tree and metadata gets, not content I/O. No cache, no multi-tenant Google identities, no write tools.

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
│   └── retrieval_scope.py     # RetrievalScope, apply_allowed_folder, is_within_scope (walks),
│                              # folder_tree + is_inside_tree (chain allow-list check)
├── access_control/
│   ├── chain.py               # ordered evaluation, no Google types
│   ├── allowed_folder.py      # startup Drive check of DRIVE_ALLOWED_FOLDER_ID
│   ├── principal.py
│   └── decisions.py
├── infra/
│   ├── config.py              # Settings; require_allowed_folder
│   ├── logging.py
│   ├── mcp_auth/
│   │   ├── bearer.py          # extract Bearer; HMAC-compare MCP_AUTH_TOKEN on /consent only
│   │   ├── jwt.py             # HS256 encode/decode (alg=none rejected)
│   │   ├── tokens.py          # mint/verify access, refresh, code, consent ticket; signing key
│   │   ├── provider.py        # DCR/CIMD + auth-code + PKCE OAuthAuthorizationServerProvider
│   │   ├── dcr.py             # stateless DCR: signed client_id, derived secret, metadata limits
│   │   ├── consent.py         # GET/POST /consent: password page or paid Allow page
│   │   ├── cimd.py            # Client ID Metadata Documents (ChatGPT, Claude); bounded LRU
│   │   ├── chatgpt_compat.py  # mixed auth on /mcp, 401 + WWW-Authenticate, metadata routes
│   │   └── setup.py           # GET /setup connector page
│   └── google_auth/
│       └── refresh_token.py   # Drive credential adapter (readonly)
├── mcp/
│   ├── server.py              # composition root: AuthSettings, provider, /consent, mounts tools.py,
│   │                          # startup allow-list checks
│   ├── tools.py               # TOOL_ARGUMENTS, authentication before argument checks
│   ├── limits.py              # outermost: body caps (413), per-address OAuth rate limits (429)
│   └── middleware.py          # run chain before any tool
tests/
├── fakes/
│   └── fake_drive.py          # one in-memory Drive port + invocation counters
├── contract/
│   ├── test_auth_contract.py
│   ├── test_allowed_folder.py
│   ├── test_oauth_http.py
│   ├── test_streamable_http_auth.py
│   ├── test_tools_require_auth.py
│   └── test_subscription_http.py   # Allow page (owned by 004)
├── integration/
│   └── test_request_isolation.py
└── unit/
    └── access_control/        # includes test_oauth_jwt.py, test_chain.py
```

**Structure Decision**: Single Python package. Access control owns `access_control/` and MCP/Google auth adapters. Retrieval Core adds tools and Drive content adapters. Domain errors, Google error mapping, `RetrievalScope`, `is_within_scope`, and the allow-list tree helpers are shared in `domain/`. The chain uses `folder_tree` + `is_inside_tree` (fixed Drive calls); retrieval walks use `is_within_scope`. `mcp/server.py` is the only composition root: it wires OAuth 2.1 (`AuthSettings` + `DriveMcpOAuthProvider` + `/consent`) and mounts `mcp/tools.py`. Folder∩file_ids AUTH is proven with `evaluate_chain` (and Retrieval’s `drive_grep`). One fake Drive port (`tests/fakes/fake_drive.py`) is a counting wrapper over an in-memory store (metadata, subfolder-listing, and content counters); Retrieval Core populates the store.

## Complexity Tracking

> No constitution violations requiring justification.

**Deploy pipeline (2026-10-01):** Specified in [`specs/005-delivery-pipeline/`](../005-delivery-pipeline/spec.md), which now owns this work (001 T052, T053). CI deploys `main` to Cloud Run after the `test` and `image` jobs pass, through the GitHub environment `production` (`main` only; no approval click, by the owner's decision) and Workload Identity Federation (no stored key). The deploy identity `onto-kb-deployer` holds `run.admin` on the `onto-kb` service only, read-only Cloud Run and secret-metadata roles, Cloud Build, the source bucket, the image repository, the `DRIVE_ALLOWED_FOLDER_ID` secret, actAs on the runtime account, and a custom project role with only `storage.buckets.list` and `run.revisions.delete` (005 T023). Code it deploys runs as the runtime account, so the owner's review of what reaches `main` is the real control.
