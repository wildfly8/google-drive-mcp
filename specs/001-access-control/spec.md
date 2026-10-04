# Feature Specification: Access Control Boundary

**Branch**: `main`

**Spec directory**: `specs/001-access-control`

**Created**: 2026-09-08

**Status**: Implemented (MCP OAuth 2.1 auth-code + PKCE; code is source of truth for this packet)

**Input**: User description: "Bounded context for who may act and on what authority over the Google Drive Agentic Retrieval MCP. Every call must pass an identical independently-enforced authorization chain before it reaches Drive. Document content is untrusted and cannot acquire authority. Retrieval Core is a conformist consumer of this context."

**Constitution**: v2.1.0 (amended 2026-10-04: Article VIII now has answers cite the connector once, with a link beside text quoted from Stack Exchange) (Articles VI, VII, V, XIV). Written against ratified v1.0.0; the amendment changed only Article VIII, which this spec does not own. Text in `.specify/memory/constitution.md`.

**Bounded Context**: Access Control / Authorization Boundary

**Relationship**: Upstream of Retrieval Core (`specs/002-retrieval-core/spec.md`). Retrieval Core never forms its own opinion about whether a call is authorized; it only executes calls this context has already cleared (Article VII).

## Clarifications

### Session 2026-09-08

- Q: In v1, who is the principal that every Drive call runs as, given the constitution allows only one Google identity per deployment? → A: One Drive identity per deployment. MCP authentication is still required so anonymous callers cannot use it. Concurrent requests share that identity; isolation is no leaked credential state, not multiple Google users.
- Q: When a call is denied, should the agent be told the file is forbidden, or only that it was not found? → A: Outside the call’s stated retrieval boundary → forbidden (`AUTHORIZATION_ERROR`). Google does not grant the file → not found (`FILE_NOT_FOUND`, no existence leak). For named ids this is superseded by Session 2026-09-29: an id not proven inside `kb` is `AUTHORIZATION_ERROR` whether or not Google grants it.
- Q: If the agent does not name a folder or file list, what may the call search? → A: `DRIVE_ALLOWED_FOLDER_ID` is required and names the `kb` folder. An omitted folder on `drive_ls`, `drive_find`, and `drive_grep` is rewritten to `kb` before the chain runs. A caller-named folder or file that is not `kb` or a descendant is `AUTHORIZATION_ERROR` (`outside_allowed_folder`). The allow-list only narrows the Google grant. There is no whole-Google-grant boundary (Session 2026-09-29). A named folder or file list narrows that one call.
- Q: When the agent names a folder for find or exact search, does that include files in nested subfolders? → A: Find and grep on a folder include nested subfolders. List is immediate children only. (Owned by Retrieval Core; Access Control enforces the resulting `RetrievalScope`.)
- Q: Which file kinds must v1 be able to read and exact-search, and what happens for everything else? → A: Required: Docs, Sheets, Slides. Also: other Drive files that yield usable text. Non-text/unreadable types → unsupported error. (Owned by Retrieval Core.)

### Session 2026-09-13

- Q: How do MCP hosts authenticate on Streamable HTTP, given v1 still has one Google identity? → A: This origin is both the OAuth 2.1 authorization server and the MCP resource server. Hosts use authorization code + PKCE S256, dynamic client registration, and RFC 9728 metadata. The `/mcp` Bearer is a short-lived access token issued here. `MCP_AUTH_TOKEN` is only the resource-owner consent password (and JWT signing input unless `MCP_OAUTH_SIGNING_KEY` is set). Google OAuth is the deployment Drive identity and MUST NOT be the MCP login.
- Q: May a public Claude connector skip the `/consent` password so users have fewer setup clicks? → A: Yes for this published Cloud Run URL. `MCP_OAUTH_AUTO_APPROVE` may be true so `/authorize` issues a code without `/consent`. `drive_*` still require a minted access token (AC-FR-010). Claude’s **Always allow** and per-chat enable prompts remain host UI and cannot be completed by this server. `GET /setup` documents the remaining steps. Superseded in part by Session 2026-10-01: with the paywall on, auto-approve is ignored and every Connect shows an Allow page.
- Q: May a host send `MCP_AUTH_TOKEN` as the `/mcp` `Authorization` Bearer? → A: No. Streamable HTTP MUST return HTTP 401. In-process calls MUST return `AUTHENTICATION_ERROR`. No Drive I/O.
- Q: After a Cloud Run instance disappears, can a previously issued access token still work, and must hosts re-register? → A: Access/refresh/authorization-code values are self-contained JWTs and MUST verify on any instance. DCR client records and used-code / revocation ids are in-memory protocol state (Article III exception); hosts re-register (RFC 7591). Superseded in part by Session 2026-10-01: a DCR `client_id` is a signed record and resolves on any instance, so hosts do not re-register.

### Session 2026-09-29

- Q: May anything outside `kb` be listed or read, even names, ids, or metadata? → A: No. `DRIVE_ALLOWED_FOLDER_ID` is required and names the `kb` folder. The server refuses to start without it, and the chain refuses every call when it is missing (`no_allowed_folder`) before any Google call. There is no whole-Google-grant mode: a call that names no folder or file after the rewrite is refused (`whole_grant_refused`). `DRIVE_DEFAULT_FOLDER_ID` is removed.
- Q: Should a named id outside `kb` and an id that does not exist get different replies? → A: No. Any named id not proven to be `kb` or a descendant is `AUTHORIZATION_ERROR`, whether it lies outside `kb`, does not exist, or Google does not grant it. The reply does not reveal whether it exists. `FILE_NOT_FOUND` is left for an id already proven inside `kb` that then disappears, and for misses after authorization.
- Q: May the time a denial takes reveal whether an id exists? → A: No. The check lists the `kb` folder tree from the top down, then makes one metadata get per named id and decides membership in memory. An id outside `kb`, a missing id, and an ungranted id make the same Drive calls. The check never looks up a folder outside `kb`.
- Q: Is a well-formed `DRIVE_ALLOWED_FOLDER_ID` enough to start? → A: No. At startup the server also reads that id from Drive. It refuses to serve unless the id is a readable folder below a Drive root: not the My Drive root (by alias or real id), not a shared-drive root, not a file, and not in the trash.

### Session 2026-10-01

- Q: With the paywall on (`specs/004-paid-subscription/`), may `/authorize` issue a code without a click on this origin? → A: No. Any site can register a client and send a subscriber’s browser to `/authorize`. A paid Connect always shows an Allow page with the client’s self-declared name and the host the browser returns to, marked as a known AI chat app address or not. There is no password on that page. The code is issued only when the Allow click comes from the browser whose entitlement cookie names the same subscriber as the consent ticket, while the processor reports that subscription active. `MCP_OAUTH_AUTO_APPROVE` applies only when the paywall is off. Consent pages cannot be framed by another site.
- Q: Must a host that registered by DCR (Cursor, Inspector) register again after scale-to-zero, a deploy, or when its next request reaches another instance? → A: No. The DCR `client_id` is a signed record of the registration (redirect URIs, name, grant and response types, token auth method, scope), and any instance resolves it by verifying the signature. A client secret, when the auth method needs one, is derived from the `client_id` with the signing key, so nothing is stored.
- Q: May a caller without a token make this origin hold unbounded memory? → A: No. DCR metadata has size limits (`invalid_client_metadata`), a CIMD `client_id` over 512 characters is refused, fetched CIMD records are a bounded per-instance cache (a synthesized fallback is kept only briefly), used-code and revoked ids are dropped once their tokens expire, request bodies are capped (HTTP 413), and `/register`, `/token`, and `/authorize` are rate-limited per client address (HTTP 429).
- Q: May the `/consent?ticket=` URL carry the Stripe customer id? → A: No. That URL lands in request logs. The ticket carries a keyed hash of the subscriber; `POST /consent` compares it with the hash of the browser’s own entitlement and issues the code for that browser’s subscriber.
- Q: Is a loopback return address (`localhost`, `127.0.0.1`) a known AI chat app address? → A: No. Any program on the subscriber’s computer can listen there. The Allow page labels it as a program on this computer (for example Claude Code or Codex), in the warning style, to allow only when the subscriber just started Connect from it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every call must clear the same authority chain (Priority: P1)

An agent asks the MCP to discover, read, or search Drive content. Before any Drive **content** I/O, the call is authenticated as a principal, authorized by the MCP for that operation and retrieval scope, then checked by Google's own authorization (a folder-only listing of the allow-list tree and metadata `files.get` on named ids, as needed). A convincing prompt, a prior successful call, or text inside a document does not skip or satisfy any step. If any step fails, the call stops there.

**Why this priority**: Without an independently evaluated chain, every other retrieval guarantee is bypassable. Article VII is the security invariant this story encodes.

**Independent Test**: Issue an unauthenticated HTTP `drive_*` tool call (401, no Drive I/O) and an in-process call without an access token (`AUTHENTICATION_ERROR`, no Drive I/O). Present `MCP_AUTH_TOKEN` as the `/mcp` Bearer (401 / `AUTHENTICATION_ERROR`, no Drive I/O). Complete DCR + auth-code + PKCE S256 and call `/mcp` with the issued access token. Issue a call for a Google-ungranted file id (`AUTHORIZATION_ERROR`, the same reply as an id outside `kb`, no content). Run the chain with no `DRIVE_ALLOWED_FOLDER_ID` (`AUTHORIZATION_ERROR`, no Google call) and start the server without it (refuses to start). Call `evaluate_chain` with both `folder_id` and a `file_ids` entry that Google grants but that is not in that folder (`AUTHORIZATION_ERROR`, metadata get allowed, no export). Confirm none return the target content — never empty successful retrieval. The agent-visible tool that uses this argument shape is `drive_grep` (Retrieval Core). Confirm an id outside `kb`, a missing id, and an ungranted id make the same Drive calls. With the paywall on, start Connect from an entitled browser: it lands on the Allow page, and no code is issued until Allow is clicked in that same browser.

**Acceptance Scenarios**:

1. **Given** no authenticated principal, **When** any retrieval call is issued, **Then** the MCP refuses the call as HTTP 401 on Streamable HTTP (or `AUTHENTICATION_ERROR` in-process) before any Drive resource is accessed.
2. **Given** `MCP_AUTH_TOKEN` sent as `Authorization: Bearer` on `/mcp`, **When** any tool call is issued, **Then** the MCP refuses as HTTP 401 (or `AUTHENTICATION_ERROR` in-process) and MUST NOT treat the consent password as an access token.
3. **Given** an authenticated caller whose Google grant does not include a requested file, **When** they ask to retrieve that file (however the request is phrased), **Then** the MCP denies the call as `AUTHORIZATION_ERROR`, the same reply as for a file outside `kb`, without confirming that the file exists or returning its content.
4. **Given** an authenticated caller who passes **both** a `folder_id` and a `file_id` that Google grants but that is not that folder or a descendant (v1 agent-visible shape: `drive_grep`; Access Control tests this via `evaluate_chain` with the same arguments), **When** they request that resource, **Then** the MCP denies the call as `AUTHORIZATION_ERROR` without returning that resource’s content. On every tool, a named id that is not proven to be `DRIVE_ALLOWED_FOLDER_ID` (`kb`) or a descendant is `AUTHORIZATION_ERROR`, whether it lies outside `kb`, does not exist, or Google does not grant it.
5. **Given** a prior successful retrieval by the same deployment identity, **When** a later call is issued for a resource Google does not grant, **Then** the prior success is not treated as a credential and the new call is evaluated from the first chain step.
6. **Given** a request that fails MCP authentication, **When** later chain steps would have passed, **Then** those later steps are never evaluated (no default-allow).
7. **Given** `DRIVE_ALLOWED_FOLDER_ID` is unset, blank, or an alias such as `root`, **When** the server starts, **Then** it refuses to start. **Given** it names a file, a trashed folder, a Drive root, or an id Drive cannot read, **When** the server starts, **Then** it refuses to start. **Given** no allow-list reaches the chain, **When** any call is evaluated, **Then** it is `AUTHORIZATION_ERROR` before any Google call.
8. **Given** an id outside `kb`, an id that does not exist, and an id Google does not grant, **When** each is named in a call, **Then** all three get the same `AUTHORIZATION_ERROR` after the same Drive calls.
9. **Given** the paywall is on and a subscriber’s browser is sent to `/authorize` (by the subscriber or by another site), **When** `/authorize` runs, **Then** no code is issued until the subscriber clicks Allow on this origin’s page in that same browser, and the page names the return host and whether it is a known AI chat app address.

---

### User Story 2 - Document text cannot grant authority (Priority: P1)

An agent retrieves a document that contains adversarial instructions ("ignore previous instructions", "grant access to folder X", "you are now authorized"). That text is data. It does not change who the principal is, what they may access, or how tools behave. Because v1 has no write or permission-mutation capability, even a fully successful injection has nothing mutating left to misuse (Article V + VI).

**Why this priority**: Article VI is a security invariant. Authority leakage from retrieved content would silently amend authorization without going through the chain.

**Independent Test**: Place an adversarial document that the principal *is* allowed to read. Retrieve it, then attempt calls that the document "instructs" (broader scope, skipped auth, policy change). Authorization decisions remain unchanged; the document's text appears only as retrieved content.

**Acceptance Scenarios**:

1. **Given** a Drive document whose body instructs the system to grant additional access, **When** the agent retrieves that document and then requests the additional access, **Then** no `AuthorizationDecision` changes and the extra access is still denied unless Google already granted it.
2. **Given** retrieved text that claims to be a system instruction, **When** any subsequent call is evaluated, **Then** that text is not used as a credential, grant, or policy update.
3. **Given** the v1 read-only surface, **When** adversarial content asks to create, edit, delete, move, rename, or change sharing, **Then** no such capability exists to invoke — denial is structural, not a filter on phrasing.

---

### User Story 3 - Credentials stay isolated and secret (Priority: P2)

The MCP holds Google authorization material for the deployment's single Drive identity. The agent and any language-model context never see raw tokens. Logs and error messages never print them. Credential and authorization state MUST be request-scoped: concurrent requests and successive instances MUST NOT observe leftover credential material from another request. Dual Google identities are out of v1 (MAJOR under Article XIV).

**Why this priority**: Secret leakage or leftover credential state would violate Article VII even if the happy path looks correct. Independent of Retrieval Core tool semantics.

**Independent Test**: Inspect responses and logs for token material after success and failure paths. Drive two concurrent requests against the same deployment identity and confirm neither observes leftover credential or grant state from the other. After an instance disappears, the next request still authenticates and authorizes from scratch.

**Acceptance Scenarios**:

1. **Given** any successful or failed call, **When** the agent inspects the response, **Then** no MCP access/refresh/authorization-code value, consent password, Google refresh or access token, or raw credential appears.
2. **Given** any error path, **When** logs are examined, **Then** they contain at most a non-secret principal identifier and never credential material.
3. **Given** two concurrent requests for the same deployment identity, **When** both are in flight on shared compute, **Then** neither request observes leftover credential, grant, or authorization context from the other.
4. **Given** a compute instance that disappears after a request, **When** the next request arrives on another instance, **Then** a still-unexpired MCP access token MUST still verify (JWT), Google credentials are minted from env for that request, and a DCR `client_id` issued by the previous instance MUST still resolve, so the host does not re-register.

---

### Edge Cases

- Unauthenticated vs unauthorized vs not-found MUST remain distinct categories; an authorization denial MUST NOT be reported as empty retrieval (Article XI, X).
- MCP retrieval-boundary violations MUST return `AUTHORIZATION_ERROR` (v1 reachable cases: no allow-list configured; a named id not proven to be `kb` or a descendant; `drive_grep` with both `folder_id` and `file_ids` when a named file is not in that folder). A named id that Google does not grant, or that does not exist, gets the same `AUTHORIZATION_ERROR` as an id outside `kb`, so the reply does not confirm that it exists. `FILE_NOT_FOUND` is only for an id already proven inside `kb` that Google then misses.
- On denial, the MCP MUST NOT leak resource content. Nothing outside `kb` is listed, and no reply confirms that an id outside `kb` exists. Existence MAY be implied only for ids inside `kb` that the caller already named (for example the folder ∩ file_ids `AUTHORIZATION_ERROR`).
- The Drive calls a denial makes MUST NOT depend on whether the named id exists or is granted, so timing does not reveal existence either.
- A tool argument the tool body does not read MUST NOT reach the chain: it is `INVALID_ARGUMENT` (Retrieval Core) after MCP authentication and before step 3, so the chain and the tool body always see the same scope. An unauthenticated call gets `AUTHENTICATION_ERROR`, not `INVALID_ARGUMENT`. A blank id does not count as a named resource.
- A link to `/authorize` that the subscriber did not start (another site’s client) MUST NOT yield a code without the subscriber’s Allow click on this origin. The Allow page shows the return host and flags an unknown one. A loopback return host is flagged as a program on this computer, never as a known AI chat app address.
- Endpoints that need no access token (`/register`, `/authorize`, `/token`, `/consent`, `/mcp` discovery) MUST NOT let a caller grow this origin’s memory without bound (AC-FR-063).
- A request MUST NOT proceed to step N of the chain if step N-1 did not explicitly pass.
- MCP-level retrieval-scope confinement applies even if the underlying Google credential could technically reach further (the MCP MUST still refuse out-of-scope resources).
- Google's authorization is the final non-bypassable check; the MCP MUST NOT implement a parallel allow-list that could grant access Google would deny. Required `DRIVE_ALLOWED_FOLDER_ID` only **narrows** a call (never widens past Google).
- `MCP_AUTH_TOKEN` presented as a `/mcp` Bearer on a `drive_*` tool call MUST fail authentication (HTTP 401 / `AUTHENTICATION_ERROR`), distinct from a missing header and from `AUTHORIZATION_ERROR`.
- `initialize`, `tools/list`, and CORS preflight on `/mcp` need no access token, so hosts can list the tools before Connect. They reach no Drive data.
- Write, share, and permission-modification are not grantable here: this context only denies them, because Article V provides no mutating capability to authorize.

## Requirements *(mandatory)*

### Functional Requirements

#### Authorization chain

- **AC-FR-001**: Every call MUST be evaluated in this exact order, every time, with no step skippable: agent request → MCP authentication → MCP authorization → Google authorization → resource (Article VII). AC-FR-002 is the no-skip rule for this order.
- **AC-FR-002**: A request MUST NOT reach step N if step N-1 did not explicitly pass. There is no default-allow state. (This is the skip-prohibition for AC-FR-001; not a second chain.)
- **AC-FR-003**: No agent-supplied justification, instruction, or prior successful call MAY be treated as satisfying any step in this chain. A convincing request is not a credential.

#### Authentication

- **AC-FR-010**: The MCP endpoint MUST require authentication; unauthenticated arbitrary access MUST NOT be possible. The server MUST refuse to start when its token-signing material (`MCP_OAUTH_SIGNING_KEY`, or else `MCP_AUTH_TOKEN`) is shorter than 32 characters, since the code that derives the key is public.
- **AC-FR-011**: Raw Google refresh or access tokens MUST NOT be exposed to the agent or to language-model context. The MCP holds a dedicated credential representation for the principal.
- **AC-FR-012**: Streamable HTTP callers MUST authenticate with an OAuth 2.1 access token issued by this origin (authorization code + PKCE S256, dynamic client registration or Client ID Metadata Documents, RFC 9728 protected-resource metadata). This origin is both authorization server and resource server. Every `drive_*` tool call needs that token; `initialize` and `tools/list` MAY run without one. `MCP_AUTH_TOKEN` is the resource-owner consent password, compared only on consent, and MUST NOT be accepted as a `/mcp` Bearer value. Google OAuth remains a separate deployment-identity mechanism and MUST NOT be the MCP login. Encoding of the access token (JWT algorithm, TTLs, signing-key derivation) is plan-level (Article XII) and MUST still satisfy AC-FR-011, AC-FR-060, and AC-FR-062.
- **AC-FR-013**: When the paywall (`specs/004-paid-subscription/`) is on, `/authorize` MUST NOT issue an authorization code without an Allow click on this origin. The click MUST come from the browser whose entitlement names the same subscriber as the pending request, while the processor reports that subscription active. The Allow page MUST show the return host and whether it is a known AI chat app address, a program on this computer (a loopback host, flagged as a warning), or neither, and MUST NOT ask for a password. The consent ticket MUST name the subscriber by a keyed hash only, never the processor’s customer id, because its URL lands in request logs. `MCP_OAUTH_AUTO_APPROVE` MUST be ignored while the paywall is on. Consent pages MUST NOT be frameable by another site.

#### Authorization and scope

- **AC-FR-020**: Google credentials MUST use the narrowest practical read-only Drive grant sufficient for discovery, content retrieval, and exact search.
- **AC-FR-021**: An operation MUST NOT access Drive resources outside its authorized `RetrievalScope` (type defined in Retrieval Core; this context enforces it). A call that names no folder or file list is rewritten to deployment `DRIVE_ALLOWED_FOLDER_ID` (narrow-only). A call that still names none (`default_whole_grant`) is refused; there is no whole-Google-grant scope. A `folder_id` or `file_ids` argument narrows that call only. The MCP MUST still refuse out-of-scope resources even if the underlying credential could technically reach them. In v1, `AUTHORIZATION_ERROR` is returned when (1) no allow-list is configured, (2) a named folder or file is not proven to be `DRIVE_ALLOWED_FOLDER_ID` or a descendant, whether it lies outside that folder, does not exist, or Google does not grant it, or (3) a caller-named `file_id` inside the allow-list folder lies outside a caller-named `folder_id`. `FILE_NOT_FOUND` is left for an id already proven inside the allow-list folder that Google then misses. See `contracts/authorization-chain.md`.
- **AC-FR-022**: If the principal's Google authorization does not grant access to a requested resource, the MCP MUST deny it via Google's own check. The MCP MUST NOT implement a parallel authorization model that could diverge from Google's by granting access Google would deny.
- **AC-FR-023**: Denial categories MUST follow this split: (1) a resource outside this call’s stated `RetrievalScope` or not proven inside `DRIVE_ALLOWED_FOLDER_ID`, including a named id Google does not grant or that does not exist → `AUTHORIZATION_ERROR`, one reply for all of these so the MCP does not confirm that the file exists; (2) an id already proven inside the allow-list folder that Google then misses → `FILE_NOT_FOUND`. The MCP MUST NOT leak content on either path, and MUST NOT leak names, ids, or metadata of anything outside the allow-list folder.
- **AC-FR-024**: The deployment MUST set `DRIVE_ALLOWED_FOLDER_ID` to one Drive folder id (`kb` on this deployment). The server MUST refuse to start when it is unset, blank, a Drive alias such as `root` or `appDataFolder`, or not a plain id. It MUST also refuse to start unless Drive reports that id as a readable folder below a Drive root: not the My Drive root (by alias or real id), not a shared-drive root, not a file, and not in the trash. The chain MUST also return `AUTHORIZATION_ERROR` (`no_allowed_folder`) for every call when no allow-list reaches it, before any Google call (fail closed).
- **AC-FR-025**: The allow-list check MUST make the same Drive calls for an id outside `DRIVE_ALLOWED_FOLDER_ID`, an id that does not exist, and an id Google does not grant, so neither the reply nor its timing reveals existence. It MUST NOT look up any folder outside the allow-list folder.

#### Per-identity isolation

- **AC-FR-030**: v1 has exactly one Google Drive identity per deployment. Every authenticated MCP caller acts as that identity. Authenticated Drive access state (credentials, grants, in-flight authorization context) MUST be request-scoped and MUST NOT leak across concurrent or successive requests on shared compute. Multiple Google identities in one deployment are out of scope until a MAJOR Article XIV change.

#### Untrusted content / authority boundary

- **AC-FR-040**: Text retrieved from any document — however phrased, including direct imperatives aimed at the system — MUST NOT alter an `AuthorizationDecision`, grant a principal additional scope, or bypass any step in AC-FR-001 (Article VI).
- **AC-FR-041**: This boundary MUST hold structurally (no mutating capability to misuse, Article V) rather than by detecting or filtering adversarial phrasing. Detection, if present, is defense-in-depth, not the guarantee.

#### Failure classification (this context's categories)

- **AC-FR-050**: Failures this context raises MUST be classified as `AUTHENTICATION_ERROR`, `AUTHORIZATION_ERROR` (MCP retrieval-boundary, including ids not proven inside the allow-list folder), or `FILE_NOT_FOUND` (an id proven inside the allow-list folder that Google then misses) and MUST NOT be silently treated as empty retrieval (Article XI). Remaining categories belong to Retrieval Core; both contexts share one flat taxonomy at the agent-visible level.

#### Secret hygiene and re-derivable state

- **AC-FR-060**: Logs and error responses MUST NOT contain MCP access tokens, refresh tokens, authorization codes, consent passwords, Google refresh or access tokens, or other credential material, under any error path.
- **AC-FR-061**: Logs MAY capture a non-secret principal identifier per request for audit, and MUST NOT capture the credential itself.
- **AC-FR-062**: MCP access-token verification and Google credential minting MUST be re-derivable on any instance (Article III). Access, refresh, and authorization-code values and DCR `client_id` values MUST be self-contained (verifiable without the instance that issued them), so a host registered by DCR MUST NOT have to re-register after scale-to-zero, a deploy, or when a request reaches another instance (stateless DCR). Used-code / revocation identifiers and fetched CIMD records MAY be in-memory auth protocol state discarded when the instance disappears. That protocol state is a documented Article III exception, not Drive content.
- **AC-FR-063**: What a caller without an access token can make this origin hold MUST be bounded. DCR metadata over its limits (client name over 200 characters, more than 5 redirect URIs or one over 512 characters, more than 5 contacts or one over 254 characters, over 16 KB in all) MUST be refused with `invalid_client_metadata`. A CIMD `client_id` over 512 characters MUST be refused. Cached CIMD records, used-code ids, and revoked ids MUST be bounded or expire. Request bodies over 4 MiB on `/mcp`, 1 MiB on the processor webhook, or 64 KB elsewhere MUST get HTTP 413 before any route reads them. `/register`, `/token`, and `/authorize` MUST be rate-limited per client address (HTTP 429 with `Retry-After`).

### Key Entities

- **Principal**: In v1, the deployment's single Google Drive identity. An MCP OAuth access token proves the caller may use this deployment; it does not select among Google users. The principal identifier in logs is a non-secret deployment/identity label, never a raw credential.
- **McpAccessToken**: Short-lived access token issued by this origin for `/mcp` (OAuth 2.1 auth-code + PKCE). Plan encoding: HS256 JWT (`aud` / resource = `{issuer}/mcp`, scope `drive.read`). Not a Google token. Never a tool argument.
- **ConsentPassword**: Resource-owner password (`MCP_AUTH_TOKEN`). Compared only on the password consent page, which is shown only when the paywall is off. MUST NOT succeed as a `/mcp` Bearer.
- **ConsentTicket**: Short-lived signed record of one pending `/authorize` request. It carries a keyed hash of the paying subscriber when the paywall is on, so the Allow click can be tied to that subscriber’s browser without the customer id appearing in the URL.
- **RegisteredClient**: RFC 7591 client record from DCR, or a client record fetched from a ChatGPT or Claude Client ID Metadata Document. A DCR record is signed into its own `client_id` and resolves on any instance (stateless DCR). CIMD records are a bounded per-instance cache, fetched again after instance death. Its name is self-declared and not trusted.
- **Credential**: The MCP-held representation of **Google** authorization for the deployment identity. Never exposed to the agent or language-model context in raw form. Distinct from `McpAccessToken`.
- **AuthorizationDecision**: Outcome of evaluating a request against the chain — `ALLOW`, `AUTHENTICATION_ERROR`, `AUTHORIZATION_ERROR` (MCP retrieval-boundary; also any named id not proven inside the allow-list folder, so existence is not confirmed), or `FILE_NOT_FOUND` (an id proven inside the allow-list folder that Google then misses).
- **Grant / Scope**: The narrowest practical Google read-only grant associated with a principal. MCP OAuth scope on the access token is a separate, non-Google value (`drive.read`).
- **RetrievalScope**: Resource boundary a specific operation is confined to. **Defined** in Retrieval Core (`specs/002-retrieval-core/data-model.md`, field `default_whole_grant`). **Enforced** here. A call that names no folder or file list is rewritten to the required `DRIVE_ALLOWED_FOLDER_ID`; there is no whole-Google-grant scope. A named folder or file list narrows that call only. Shared implementation lives in `domain/retrieval_scope.py`.

**Vocabulary note**: This context speaks in principal, MCP access token, consent password, Google credential, grant, scope, and authorization decision. Retrieval Core speaks in candidate, content, match, and evidence. That divergence is why these are separate features.

### Invariants

| ID | Statement | Constitution |
| --- | --- | --- |
| AI1 | Authorization is evaluated independently of agent reasoning | Article VII |
| AI2 | Document content cannot acquire authority over MCP policy or auth decisions | Article VI |
| AI3 | An operation never exceeds its authorized RetrievalScope | Article VII |
| AI4 | Credential and authorization state is request-scoped and does not leak across requests (v1: one Drive identity per deployment) | Article VII |
| AI5 | Google's authorization is the final, non-bypassable check | Article VII |
| AI6 | Nothing outside `DRIVE_ALLOWED_FOLDER_ID` is listed, read, or confirmed to exist (by reply or by the Drive calls a denial makes); without that folder nothing is readable | Article VII |
| AI7 | With the paywall on, no authorization code is issued without the subscriber’s Allow click in the same entitled browser | Article VII |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of calls without an authenticated principal are refused before any Drive content or metadata for a specific resource is returned.
- **SC-002**: 100% of calls for a resource the principal's Google grant does not include are denied; the agent never receives that resource's content regardless of how the request is phrased.
- **SC-003**: In adversarial-document tests, retrieved instructions produce **zero** changes to any authorization decision (no extra grant, no skipped chain step, no policy change).
- **SC-004**: Two concurrent requests against the same deployment identity share **zero** leftover credential, grant, or authorization-context observations.
- **SC-005**: Audit of responses, error bodies, and logs after success and failure paths finds **zero** raw token or credential material.
- **SC-006**: 100% of MCP retrieval-boundary denials (v1: no allow-list; a named resource not proven inside `DRIVE_ALLOWED_FOLDER_ID`, including one that does not exist or that Google does not grant; a granted named `file_id` outside a named `folder_id`) are labeled `AUTHORIZATION_ERROR`, and an id outside `kb` gets the same reply as a missing id. 100% of misses on an id already proven inside the allow-list folder are labeled `FILE_NOT_FOUND`. Neither path is labeled as empty successful retrieval.
- **SC-007**: 100% of Streamable HTTP `/mcp` `drive_*` tool calls that present `MCP_AUTH_TOKEN` as Bearer are refused as HTTP 401 before Drive I/O. 100% of successful `/mcp` Bearer values are access tokens issued by this origin’s auth-code + PKCE flow (or a test helper that mints the same token type).
- **SC-008**: With the paywall on, 100% of authorization codes follow an Allow click from the browser whose entitlement names the subscriber in the ticket. A click with no entitlement cookie, another subscriber’s cookie, or a lapsed subscription issues no code.
- **SC-009**: For an id outside the allow-list folder, a missing id, and an ungranted id, the sequence of Drive calls and the reply are identical.

## Assumptions

- v1 is one authenticated Google identity per deployment (constitution preamble; clarified 2026-09-08). MCP authentication is still mandatory so unauthenticated callers cannot use the deployment. Isolation means request-scoped credentials and no leftover auth state — not multiple Google users. Multi-tenant federation and cross-organization access are out of scope until a MAJOR Article XIV change.
- MCP caller authentication **protocol** (auth-code + PKCE S256, DCR, RFC 9728, consent password vs access token, split from Google OAuth) is specified here (AC-FR-012). Token encoding, TTLs, signing-key derivation, and the DCR `client_id` encoding are plan-level (Article XII) and MUST still satisfy AC-FR-011, AC-FR-060, and AC-FR-062.
- Whether principal identifiers in logs are hashed or used as-is is a plan-level choice bounded by AC-FR-061.
- Widening or narrowing the granted read-only OAuth scope over the feature lifecycle is a plan-level change; it MUST remain read-only (Article V) and as narrow as practical (AC-FR-020).
- Retrieval tool semantics (`drive_ls`, `drive_find`, `drive_read`, `drive_grep`) live in Retrieval Core. This spec does not define what a cleared call retrieves.
- `AUTHORIZATION_ERROR` is the MCP retrieval-boundary denial category (v1: no allow-list; a named id not proven inside `DRIVE_ALLOWED_FOLDER_ID`, whether outside it, missing, or not granted; a granted `file_id` outside a named `folder_id` on `drive_grep`). `FILE_NOT_FOUND` is for an id already proven inside the allow-list folder that Google then misses, so no reply leaks existence outside that folder. Both are part of the shared agent-visible taxonomy; Retrieval Core also raises `FILE_NOT_FOUND` for genuinely missing files after authorization has cleared, using the same `map_google_error()` helper.
- Write, share, and permission modification have nothing to grant here — only to deny — because Article V provides no mutating capability.

## Out of Scope

- What a cleared call is allowed to retrieve (Retrieval Core tool semantics). `RetrievalScope` **fields** are defined in Retrieval Core; this context still specifies and implements **enforcement**.
- Multi-tenant identity federation or cross-organization access models (MAJOR under Article XIV).
- Any write, share, or permission-modification capability.
- OAuth library, HTTP transport, JWT codec, and DCR storage technology choices (plan.md; Article XII). The OAuth 2.1 **protocol** itself is in scope (AC-FR-012).

## Dependencies

- Downstream: Retrieval Core (`specs/002-retrieval-core/spec.md`) consumes this context as a conformist — it assumes every call has already cleared the chain.
- Paid subscription (`specs/004-paid-subscription/spec.md`) gates code issuance and refresh on top of AC-FR-012. This context owns the Allow page rule (AC-FR-013); 004 owns entitlement, checkout, and processor checks.
- Google remains the authoritative permission store (Article I, VII). Nothing this MCP caches or infers is an authorization source of truth.
