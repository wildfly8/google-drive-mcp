# Research: Access Control Boundary

## Decision: Official MCP Python SDK 2.x over Streamable HTTP

**Rationale**: Constitution Article XIII requires tracking current MCP transport. The official `mcp` package (v2) is the protocol implementation; Streamable HTTP is the deployable transport for Cloud Run. Stdio remains optional for local inspector only.

**Alternatives considered**: FastMCP GoogleProvider (mixes Google user OAuth with MCP auth — would collapse chain steps 2 and 4). Homegrown JSON-RPC over Flask (reinvents the protocol).

## Decision: Split MCP authentication from Google authorization

**Rationale**: Clarify session: one Drive identity per deployment, but the MCP endpoint must not be anonymous (AC-FR-010). MCP auth is a shared bearer secret (`MCP_AUTH_TOKEN`). Google access uses a separate OAuth refresh token (`GOOGLE_REFRESH_TOKEN` + client id/secret) with scope `drive.readonly`. Every tool call: validate bearer → evaluate RetrievalScope → call Google; Google 404/403-as-404 maps to `FILE_NOT_FOUND`.

**Alternatives considered**: Google OAuth as the MCP login (FastMCP GoogleProvider) — couples agent login to Drive identity and invites multi-user Google tokens (MAJOR). Unauthenticated MCP on a private VPC — fails AC-FR-010 if the URL is reachable. mTLS-only — valid later; not required for v1 if bearer is present.

## Decision: Google user OAuth refresh token as a Cloud Run secret, not a service account

**Rationale**: v1 is a personal Drive. Service accounts do not see a user’s My Drive without Domain-Wide Delegation (Workspace-only, out of v1). A one-time local consent produces a refresh token stored in Secret Manager; the app never exposes it to the agent (AC-FR-011). Access tokens are minted per request (or short-lived in memory for that request only).

**Alternatives considered**: Service account + shared drive only (narrower than spec’s default whole-grant). Per-request interactive OAuth (not Cloud Run compatible). Token file on disk (`token.json`) — hidden persistent state (Art. III fail).

## Decision: Denial mapping is MCP-boundary vs Google-grant

**Rationale**: Clarify C. If the tool arguments name a `folder_id`/`file_id` outside that call’s `RetrievalScope`, stop at MCP authorization with `AUTHORIZATION_ERROR` (no Google call required). If Google does not grant the resource, return `FILE_NOT_FOUND` and do not include name/metadata/content. Prefer treating Google `404` and permission-denied-as-404 as not found; do not translate them to `AUTHORIZATION_ERROR`.

**Alternatives considered**: Always 403 (leaks existence). Always 404 including MCP scope violations (hides agent mistakes when they named a file they just listed under a tighter scope).

## Decision: Request-scoped credential objects, no process-wide Google client cache keyed by identity

**Rationale**: Cloud Run concurrency > 1. v1 has one identity, but leftover credential objects on a shared client must not appear in logs or error payloads. Build a Drive client per request from env secrets; do not log headers.

**Alternatives considered**: Global singleton Drive service (harder to prove no leak; acceptable only if proven request-safe — rejected to keep AC-FR-030 testable). Redis token cache (persistent state, MAJOR).

## Decision: Principal identifier in logs is a deployment label, not a Google email by default

**Rationale**: AC-FR-061 allows a non-secret principal id. Use a configured `MCP_PRINCIPAL_ID` (or `deployment`) string. Hashing vs raw email is unnecessary if we never log email.

**Alternatives considered**: Log Google `sub` email (identifying). HMAC of token (useless for ops).

## Decision: No mutating Google API methods in the dependency surface

**Rationale**: Article V is structural. The Google adapter module imports and calls only `files().list`, `files().get`, `files().export`, `files().get_media` (download). No `create`/`update`/`delete`/`permissions`. Tests grep the adapter for forbidden method names.

**Alternatives considered**: Relying on `drive.readonly` scope alone (necessary but not sufficient — still omit write methods).
