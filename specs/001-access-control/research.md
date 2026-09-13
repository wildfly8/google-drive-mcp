# Research: Access Control Boundary

## Decision: Official MCP Python SDK 2.x over Streamable HTTP

**Rationale**: Constitution Article XIII requires tracking current MCP transport. The official `mcp` package (v2) is the protocol implementation; Streamable HTTP is the deployable transport for Cloud Run. Stdio remains optional for local inspector only.

**Alternatives considered**: FastMCP GoogleProvider (mixes Google user OAuth with MCP auth — would collapse chain steps 2 and 4). Homegrown JSON-RPC over Flask (reinvents the protocol).

## Decision: MCP OAuth 2.1 on this origin, split from Google authorization

**Rationale**: Clarify session: one Drive identity per deployment, but the MCP endpoint must not be anonymous (AC-FR-010). MCP callers authenticate with OAuth 2.1 access tokens issued by this Cloud Run origin (authorization code + PKCE S256, DCR, RFC 9728). `MCP_AUTH_TOKEN` is the resource-owner consent password, not a long-lived `/mcp` Bearer. Google access uses a separate OAuth refresh token (`GOOGLE_REFRESH_TOKEN` + client id/secret, or authorized-user JSON) with scope `drive.readonly`. Every tool call: validate access token → evaluate RetrievalScope → call Google; Google 404/403-as-404 maps to `FILE_NOT_FOUND`.

**Alternatives considered**: Long-lived shared secret compared in-process as `/mcp` Bearer — cannot complete ChatGPT/Claude connector redirects against this origin. Google OAuth as the MCP login (FastMCP GoogleProvider) — couples agent login to Drive identity and invites multi-user Google tokens (MAJOR). Unauthenticated MCP on a private VPC — fails AC-FR-010 if the URL is reachable. mTLS-only — valid later; not required when OAuth 2.1 is present. Separate authorization server process — extra deploy surface; MCP hosts need `/authorize` `/token` `/register` on this origin.

## Decision: Google user OAuth refresh token as a Cloud Run secret, not a service account

**Rationale**: v1 is a personal Drive. Service accounts do not see a user’s My Drive without Domain-Wide Delegation (Workspace-only, out of v1). A one-time local consent produces a refresh token stored in Secret Manager; the app never exposes it to the agent (AC-FR-011). Access tokens are minted per request (or short-lived in memory for that request only).

**Alternatives considered**: Service account + shared drive only (narrower than spec’s default whole-grant). Per-request interactive OAuth (not Cloud Run compatible). Token file on disk (`token.json`) — hidden persistent state (Art. III fail).

## Decision: Denial mapping is MCP-boundary vs Google-grant

**Rationale**: Clarify C. If Google does not grant the resource, return `FILE_NOT_FOUND` and do not include name/metadata/content. Prefer treating Google `404` and permission-denied-as-404 as not found; do not translate them to `AUTHORIZATION_ERROR`.

`AUTHORIZATION_ERROR` is **not** a Drive-free guess that `file_id ≠ folder_id`. Parentage is a Drive fact. v1 reachable case: the caller names **both** `folder_id` and `file_ids` (`drive_grep`). Step 3 (no Drive I/O) always passes for v1 tools. Step 4 metadata `files.get` then `is_within_scope`: granted-but-outside-folder → `AUTHORIZATION_ERROR` (caller already named both ids); no grant → `FILE_NOT_FOUND`. Content export MUST NOT run. `drive_read` / `drive_ls` / `drive_find` never emit `AUTHORIZATION_ERROR` in v1.

Single domain helper `is_within_scope` (parent-lookup port) is shared with Retrieval Core walks so chain and BFS cannot disagree.

**Alternatives considered**: Always 403 (leaks existence). Always 404 including MCP scope violations (hides agent mistakes when they named a file they just listed under a tighter folder). Treating any `file_id ≠ folder_id` as `AUTHORIZATION_ERROR` without a parent walk (breaks legitimate child reads). Requiring Drive **content** count = 0 *and* zero metadata get for the AUTH case (unimplementable without a persistent tree, forbidden by Art. III).

## Decision: Request-scoped credential objects, no process-wide Google client cache keyed by identity

**Rationale**: Cloud Run concurrency > 1. v1 has one identity, but leftover credential objects on a shared client must not appear in logs or error payloads. Build a Drive client per request from env secrets; do not log headers.

**Alternatives considered**: Global singleton Drive service (harder to prove no leak; acceptable only if proven request-safe — rejected to keep AC-FR-030 testable). Redis token cache (persistent state, MAJOR).

## Decision: Principal identifier in logs is a deployment label, not a Google email by default

**Rationale**: AC-FR-061 allows a non-secret principal id. Use a configured `MCP_PRINCIPAL_ID` (or `deployment`) string. Hashing vs raw email is unnecessary if we never log email.

**Alternatives considered**: Log Google `sub` email (identifying). HMAC of token (useless for ops).

## Decision: One fake Drive port; composition root is `mcp/server.py`

**Rationale**: Analyze 2026-09-08. Access Control and Retrieval Core share one in-memory Drive port (`tests/fakes/fake_drive.py`) with separate metadata vs content counters. Retrieval populates the store; the chain spies on the same object. `mcp/server.py` mounts `mcp/tools.py`; do not start a second HTTP server.

**Alternatives considered**: `fake_google_drive.py` plus `fake_drive_store.py` (auth tests can pass while tools talk to a different graph).

## Decision: No mutating Google API methods in the dependency surface

**Rationale**: Article V is structural. Access Control tests scan `infra/google_auth` and MCP registration for mutating capability (no write tools, readonly OAuth scope). Retrieval Core tests scan `infra/google_drive` for `files().create/update/delete/permissions`. Neither scan substitutes for the other.

**Alternatives considered**: Relying on `drive.readonly` scope alone (necessary but not sufficient — still omit write methods). One combined grep before the Drive adapter exists (Access Control US2 would wait on Retrieval Core).
