# Research: Access Control Boundary

## Decision: Official MCP Python SDK 2.x over Streamable HTTP

**Rationale**: Constitution Article XIII requires tracking current MCP transport. The official `mcp` package (v2) is the protocol implementation; Streamable HTTP is the deployable transport for Cloud Run. Stdio remains optional for local inspector only.

**Alternatives considered**: FastMCP GoogleProvider (mixes Google user OAuth with MCP auth — would collapse chain steps 2 and 4). Homegrown JSON-RPC over Flask (reinvents the protocol).

## Decision: MCP OAuth 2.1 on this origin, split from Google authorization

**Rationale**: Clarify session: one Drive identity per deployment, but the MCP endpoint must not be anonymous (AC-FR-010). MCP callers authenticate with OAuth 2.1 access tokens issued by this Cloud Run origin (authorization code + PKCE S256, DCR, RFC 9728). `MCP_AUTH_TOKEN` is the resource-owner consent password, not a long-lived `/mcp` Bearer. Google access uses a separate OAuth refresh token (`GOOGLE_REFRESH_TOKEN` + client id/secret with scope `drive.readonly`, or authorized-user JSON with the scopes on the blob; see below). Every tool call: validate access token → evaluate RetrievalScope → call Google; Google 404/403-as-404 maps to `FILE_NOT_FOUND` once an id is proven inside the allow-list folder (see the 2026-09-29 decision below).

Hosts identify by DCR (`POST /register`) or by Client ID Metadata Documents (CIMD). ChatGPT and Claude send an HTTPS `client_id` on `chatgpt.com`, `claude.ai`, or `claude.com`; the server fetches that document on demand, so scale-to-zero does not lose the registration. Other hosts are not fetched, so `client_id` cannot be used for SSRF.

**Alternatives considered**: Long-lived shared secret compared in-process as `/mcp` Bearer — cannot complete ChatGPT/Claude connector redirects against this origin. Google OAuth as the MCP login (FastMCP GoogleProvider) — couples agent login to Drive identity and invites multi-user Google tokens (MAJOR). Unauthenticated MCP on a private VPC — fails AC-FR-010 if the URL is reachable. mTLS-only — valid later; not required when OAuth 2.1 is present. Separate authorization server process — extra deploy surface; MCP hosts need `/authorize` `/token` `/register` on this origin.

## Decision: Google user OAuth refresh token as a Cloud Run secret, not a service account

**Rationale**: v1 is a personal Drive. Service accounts do not see a user’s My Drive without Domain-Wide Delegation (Workspace-only, out of v1). A one-time local consent produces a refresh token stored in Secret Manager; the app never exposes it to the agent (AC-FR-011). Access tokens are minted per request (or short-lived in memory for that request only).

`GOOGLE_AUTHORIZED_USER_JSON` (a gcloud authorized-user blob) is preferred when set. It keeps the scopes already on the blob, because the Cloud SDK OAuth client rejects `drive.readonly` on refresh. On that path, read-only rests on the adapter having no write methods, and the operator must keep the grant behind the blob read-only. The three-field mint (`GOOGLE_REFRESH_TOKEN` + client id/secret) always asks for `drive.readonly`.

**Alternatives considered**: Service account + shared drive only (cannot see the user’s My Drive, where `kb` lives). Per-request interactive OAuth (not Cloud Run compatible). Token file on disk (`token.json`) — hidden persistent state (Art. III fail).

## Decision: Denial mapping is MCP-boundary vs Google-grant

**Superseded in part (2026-09-29)**: for named ids, see “Fail closed; outside and missing ids get one reply” below. Step 3 can now refuse a call (`no_allowed_folder`, `whole_grant_refused`), and every tool can return `AUTHORIZATION_ERROR` for an id outside `kb`. The text in this section is the original v1 rule.

**Rationale**: Clarify C. If Google does not grant the resource, return `FILE_NOT_FOUND` and do not include name/metadata/content. Prefer treating Google `404` and permission-denied-as-404 as not found; do not translate them to `AUTHORIZATION_ERROR`.

`AUTHORIZATION_ERROR` is **not** a Drive-free guess that `file_id ≠ folder_id`. Parentage is a Drive fact. v1 reachable case: the caller names **both** `folder_id` and `file_ids` (`drive_grep`). Step 3 (no Drive I/O) always passes for v1 tools. Step 4 metadata `files.get` then `is_within_scope`: granted-but-outside-folder → `AUTHORIZATION_ERROR` (caller already named both ids); no grant → `FILE_NOT_FOUND`. Content export MUST NOT run. `drive_read` / `drive_ls` / `drive_find` never emit `AUTHORIZATION_ERROR` in v1.

Single domain helper `is_within_scope` (parent-lookup port) is shared with Retrieval Core walks so chain and BFS cannot disagree. Superseded for the chain on 2026-09-29: the chain now uses `folder_tree` + `is_inside_tree` (see “Allow-list check lists the kb tree top down” below). Retrieval walks still use `is_within_scope`.

**Alternatives considered**: Always 403 (leaks existence). Always 404 including MCP scope violations (hides agent mistakes when they named a file they just listed under a tighter folder). Treating any `file_id ≠ folder_id` as `AUTHORIZATION_ERROR` without a parent walk (breaks legitimate child reads). Requiring Drive **content** count = 0 *and* zero metadata get for the AUTH case (unimplementable without a persistent tree, forbidden by Art. III).

## Decision: Fail closed; outside and missing ids get one reply (2026-09-29)

**Rationale**: The owner requires that only the `kb` folder and its descendants are readable, and that nothing outside `kb` can be listed, not even names or ids. `DRIVE_ALLOWED_FOLDER_ID` is now required. The server does not start when it is unset, blank, an alias such as `root` / `appDataFolder`, or not a plain id. Step 3 refuses every call when it is missing (`no_allowed_folder`), before any Google call. There is no whole-grant scope: a call that still names no folder or file after the rewrite is refused (`whole_grant_refused`). Step 4 checks the allow-list first for every named id. A Google 404/403 on the named id counts as not proven (first through `parent_lookup`; since the tree check below, through the one metadata get), so an id outside `kb`, a missing id, and an ungranted id all fail the same check and get the same `AUTHORIZATION_ERROR`. That reply does not reveal whether the id exists. `FILE_NOT_FOUND` is left for an id already proven inside `kb` that then misses. Each tool accepts only the argument keys its body reads, so the chain and the tool body see the same scope.

**Alternatives considered**: Keep `FILE_NOT_FOUND` for Google misses on named ids (rejected: a granted id outside `kb` got `AUTHORIZATION_ERROR` and a missing id got `FILE_NOT_FOUND`, so the reply confirmed existence outside `kb`). Keep the allow-list optional (rejected: one missing env var re-opened the whole Drive).

## Decision: Allow-list check lists the kb tree top down (2026-09-29)

**Rationale**: The first fail-closed check climbed parents with `files.get` from the named id. A missing id stopped after one 404, while an id outside `kb` climbed until it reached a Drive root. The replies matched, but the time and the number of Drive calls did not, so timing revealed existence. The climb also looked up folders outside `kb`. The chain now lists the subfolders of `DRIVE_ALLOWED_FOLDER_ID` level by level (`folder_tree` over `list_subfolders`: folders only, trashed included, up to 40 parent ids per query), makes one metadata `files.get` per named id, and decides membership in memory (`is_inside_tree`, which only follows folders in that tree). The calls depend only on the `kb` tree and the number of named ids, never on whether an id exists. When the only named id is `kb` itself, the tree is not listed. In the chain, `FILE_NOT_FOUND` now only arises when listing `kb`’s own tree gets 404/403 (the folder was removed or unshared after startup).

**Alternatives considered**: Pad denials with a sleep (rejected: fragile, and still climbs outside `kb`). Cache the tree across requests (rejected: hidden persistent state, Article III). Cap the parent climb depth (rejected: still leaks within the cap).

## Decision: Startup reads the allow-list folder from Drive (2026-09-29)

**Rationale**: A well-formed id can still name the real My Drive root, a shared-drive root, a file, or a trashed folder. Each would widen or break the allow-list. `main()` now mints credentials once and calls `check_allowed_folder`: the id must be readable, a folder, have a parent (roots have none), differ from the id Drive returns for `root`, and not be trashed. Otherwise the server exits. The deploy script also reads the id from Secret Manager rather than the operator’s shell, and keeps only the newest revision, which must carry it.

**Alternatives considered**: Format check only (rejected: the real root id is a plain id). Check on every request (rejected: extra Drive calls; the per-call check already refuses ids outside the folder).

## Decision: Paid Connect always shows an Allow page (2026-10-01)

**Rationale**: With open DCR and `MCP_OAUTH_AUTO_APPROVE=true`, any site could register a client with its own redirect URI and send a subscriber’s browser to `/authorize`. The browser carried the entitlement cookie, so a code went to that site with no click, and its holder could use the subscriber’s access without paying. Now, with the paywall on, `/authorize` always mints a consent ticket that names the subscriber (`scid`) and shows an Allow page. The page shows the client’s self-declared name and the return host, marked as a known AI chat app address or not. `POST /consent` issues the code only when the browser’s entitlement cookie names the same subscriber and the processor reports it active. Consent pages send `X-Frame-Options: DENY` and `frame-ancestors 'none'`, so another site cannot frame the Allow button. Auto-approve still applies when the paywall is off.

**Alternatives considered**: Keep auto-approve and allow only known redirect hosts (rejected: breaks Inspector and other DCR hosts, and a known host is not proof the subscriber started Connect). Ask subscribers for `MCP_AUTH_TOKEN` (rejected: that is the operator’s password). Trust the client name (rejected: it is self-declared; the return host is the signal shown).

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

**History (2026-09-30)**: Temporary `kb` write tools (`drive_write`, `drive_trash`, then `drive_replace`) were added behind `DRIVE_WRITE_ENABLED` with a separate `drive`-scope credential, then removed the same day. The server registers only `drive_ls`, `drive_find`, `drive_read`, and `drive_grep` again, and `DRIVE_WRITE_ENABLED` is no longer read.
