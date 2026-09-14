# Feature Specification: Access Control Boundary

**Branch**: `main`

**Spec directory**: `specs/001-access-control`

**Created**: 2026-09-08

**Status**: Implemented (MCP OAuth 2.1 auth-code + PKCE; code is source of truth for this packet)

**Input**: User description: "Bounded context for who may act and on what authority over the Google Drive Agentic Retrieval MCP. Every call must pass an identical independently-enforced authorization chain before it reaches Drive. Document content is untrusted and cannot acquire authority. Retrieval Core is a conformist consumer of this context."

**Constitution**: Ratified v1.0.0 (Articles VI, VII, V, XIV). Source attachments cited Constitution v2.0.0; this spec conforms to the ratified v1.0.0 text in `.specify/memory/constitution.md`.

**Bounded Context**: Access Control / Authorization Boundary

**Relationship**: Upstream of Retrieval Core (`specs/002-retrieval-core/spec.md`). Retrieval Core never forms its own opinion about whether a call is authorized; it only executes calls this context has already cleared (Article VII).

## Clarifications

### Session 2026-09-08

- Q: In v1, who is the principal that every Drive call runs as, given the constitution allows only one Google identity per deployment? → A: One Drive identity per deployment. MCP authentication is still required so anonymous callers cannot use it. Concurrent requests share that identity; isolation is no leaked credential state, not multiple Google users.
- Q: When a call is denied, should the agent be told the file is forbidden, or only that it was not found? → A: Outside the call’s stated retrieval boundary → forbidden (`AUTHORIZATION_ERROR`). Google does not grant the file → not found (`FILE_NOT_FOUND`, no existence leak).
- Q: If the agent does not name a folder or file list, what may the call search? → A: Unspecified boundary = the whole Google grant for this deployment identity. Optional folder or file list narrows that one call.
- Q: When the agent names a folder for find or exact search, does that include files in nested subfolders? → A: Find and grep on a folder include nested subfolders. List is immediate children only. (Owned by Retrieval Core; Access Control enforces the resulting `RetrievalScope`.)
- Q: Which file kinds must v1 be able to read and exact-search, and what happens for everything else? → A: Required: Docs, Sheets, Slides. Also: other Drive files that yield usable text. Non-text/unreadable types → unsupported error. (Owned by Retrieval Core.)

### Session 2026-09-13

- Q: How do MCP hosts authenticate on Streamable HTTP, given v1 still has one Google identity? → A: This origin is both the OAuth 2.1 authorization server and the MCP resource server. Hosts use authorization code + PKCE S256, dynamic client registration, and RFC 9728 metadata. The `/mcp` Bearer is a short-lived access token issued here. `MCP_AUTH_TOKEN` is only the resource-owner consent password (and JWT signing input unless `MCP_OAUTH_SIGNING_KEY` is set). Google OAuth is the deployment Drive identity and MUST NOT be the MCP login.
- Q: May a public Claude connector skip the `/consent` password so users have fewer setup clicks? → A: Yes for this published Cloud Run URL. `MCP_OAUTH_AUTO_APPROVE` may be true so `/authorize` issues a code without `/consent`. `drive_*` still require a minted access token (AC-FR-010). Claude’s **Always allow** and per-chat enable prompts remain host UI and cannot be completed by this server. `GET /setup` documents the remaining steps.
- Q: May a host send `MCP_AUTH_TOKEN` as the `/mcp` `Authorization` Bearer? → A: No. Streamable HTTP MUST return HTTP 401. In-process calls MUST return `AUTHENTICATION_ERROR`. No Drive I/O.
- Q: After a Cloud Run instance disappears, can a previously issued access token still work, and must hosts re-register? → A: Access/refresh/authorization-code values are self-contained JWTs and MUST verify on any instance. DCR client records and used-code / revocation ids are in-memory protocol state (Article III exception); hosts re-register (RFC 7591).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every call must clear the same authority chain (Priority: P1)

An agent asks the MCP to discover, read, or search Drive content. Before any Drive **content** I/O, the call is authenticated as a principal, authorized by the MCP for that operation and retrieval scope, then checked by Google's own authorization (metadata `files.get` as needed). A convincing prompt, a prior successful call, or text inside a document does not skip or satisfy any step. If any step fails, the call stops there.

**Why this priority**: Without an independently evaluated chain, every other retrieval guarantee is bypassable. Article VII is the security invariant this story encodes.

**Independent Test**: Issue an unauthenticated HTTP call (401, no Drive I/O) and an in-process call without an access token (`AUTHENTICATION_ERROR`, no Drive I/O). Present `MCP_AUTH_TOKEN` as the `/mcp` Bearer (401 / `AUTHENTICATION_ERROR`, no Drive I/O). Complete DCR + auth-code + PKCE S256 and call `/mcp` with the issued access token. Issue a call for a Google-ungranted file id (`FILE_NOT_FOUND`, no content). Call `evaluate_chain` with both `folder_id` and a `file_ids` entry that Google grants but that is not in that folder (`AUTHORIZATION_ERROR`, metadata get allowed, no export). Confirm none return the target content — never empty successful retrieval. The agent-visible tool that uses this argument shape is `drive_grep` (Retrieval Core).

**Acceptance Scenarios**:

1. **Given** no authenticated principal, **When** any retrieval call is issued, **Then** the MCP refuses the call as HTTP 401 on Streamable HTTP (or `AUTHENTICATION_ERROR` in-process) before any Drive resource is accessed.
2. **Given** `MCP_AUTH_TOKEN` sent as `Authorization: Bearer` on `/mcp`, **When** any tool call is issued, **Then** the MCP refuses as HTTP 401 (or `AUTHENTICATION_ERROR` in-process) and MUST NOT treat the consent password as an access token.
3. **Given** an authenticated caller whose Google grant does not include a requested file, **When** they ask to retrieve that file (however the request is phrased), **Then** the MCP denies the call as `FILE_NOT_FOUND` without confirming that the file exists or returning its content.
4. **Given** an authenticated caller who passes **both** a `folder_id` and a `file_id` that Google grants but that is not that folder or a descendant (v1 agent-visible shape: `drive_grep`; Access Control tests this via `evaluate_chain` with the same arguments), **When** they request that resource, **Then** the MCP denies the call as `AUTHORIZATION_ERROR` without returning that resource’s content. Google misses on `drive_read` / `drive_ls` / `drive_find` are `FILE_NOT_FOUND`. Those tools emit `AUTHORIZATION_ERROR` in v1 only when a deployment `DRIVE_ALLOWED_FOLDER_ID` is set and Google grants a named resource outside that folder.
5. **Given** a prior successful retrieval by the same deployment identity, **When** a later call is issued for a resource Google does not grant, **Then** the prior success is not treated as a credential and the new call is evaluated from the first chain step.
6. **Given** a request that fails MCP authentication, **When** later chain steps would have passed, **Then** those later steps are never evaluated (no default-allow).

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
4. **Given** a compute instance that disappears after a request, **When** the next request arrives on another instance, **Then** a still-unexpired MCP access token MUST still verify (JWT), Google credentials are minted from env for that request, and DCR clients that existed only in the previous instance’s memory MUST re-register.

---

### Edge Cases

- Unauthenticated vs unauthorized vs not-found MUST remain distinct categories; an authorization denial MUST NOT be reported as empty retrieval (Article XI, X).
- MCP retrieval-boundary violations MUST return `AUTHORIZATION_ERROR` (v1 reachable case: `drive_grep` with both `folder_id` and `file_ids` when Google grants a named file that is not in that folder). Google grant failures MUST return `FILE_NOT_FOUND` and MUST NOT confirm that the inaccessible file exists.
- On denial, the MCP MUST NOT leak resource content. Metadata and existence MAY be implied only by `AUTHORIZATION_ERROR` for an out-of-boundary resource the caller already named; Google-denied resources MUST NOT leak existence.
- A request MUST NOT proceed to step N of the chain if step N-1 did not explicitly pass.
- MCP-level retrieval-scope confinement applies even if the underlying Google credential could technically reach further (the MCP MUST still refuse out-of-scope resources).
- Google's authorization is the final non-bypassable check; the MCP MUST NOT implement a parallel allow-list that could grant access Google would deny. Optional `DRIVE_ALLOWED_FOLDER_ID` MAY only **narrow** a call (never widen past Google).
- `MCP_AUTH_TOKEN` presented as a `/mcp` Bearer MUST fail authentication (HTTP 401 / `AUTHENTICATION_ERROR`), distinct from a missing header and from `AUTHORIZATION_ERROR`.
- Write, share, and permission-modification are not grantable here: this context only denies them, because Article V provides no mutating capability to authorize.

## Requirements *(mandatory)*

### Functional Requirements

#### Authorization chain

- **AC-FR-001**: Every call MUST be evaluated in this exact order, every time, with no step skippable: agent request → MCP authentication → MCP authorization → Google authorization → resource (Article VII). AC-FR-002 is the no-skip rule for this order.
- **AC-FR-002**: A request MUST NOT reach step N if step N-1 did not explicitly pass. There is no default-allow state. (This is the skip-prohibition for AC-FR-001; not a second chain.)
- **AC-FR-003**: No agent-supplied justification, instruction, or prior successful call MAY be treated as satisfying any step in this chain. A convincing request is not a credential.

#### Authentication

- **AC-FR-010**: The MCP endpoint MUST require authentication; unauthenticated arbitrary access MUST NOT be possible.
- **AC-FR-011**: Raw Google refresh or access tokens MUST NOT be exposed to the agent or to language-model context. The MCP holds a dedicated credential representation for the principal.
- **AC-FR-012**: Streamable HTTP callers MUST authenticate with an OAuth 2.1 access token issued by this origin (authorization code + PKCE S256, dynamic client registration, RFC 9728 protected-resource metadata). This origin is both authorization server and resource server. `MCP_AUTH_TOKEN` is the resource-owner consent password, compared only on consent, and MUST NOT be accepted as a `/mcp` Bearer value. Google OAuth remains a separate deployment-identity mechanism and MUST NOT be the MCP login. Encoding of the access token (JWT algorithm, TTLs, signing-key derivation) is plan-level (Article XII) and MUST still satisfy AC-FR-011, AC-FR-060, and AC-FR-062.

#### Authorization and scope

- **AC-FR-020**: Google credentials MUST use the narrowest practical read-only Drive grant sufficient for discovery, content retrieval, and exact search.
- **AC-FR-021**: An operation MUST NOT access Drive resources outside its authorized `RetrievalScope` (type defined in Retrieval Core; this context enforces it). Default `RetrievalScope` for a call that names no folder or file list is the entire Google grant for this deployment identity (`default_whole_grant`), optionally rewritten to deployment `DRIVE_ALLOWED_FOLDER_ID` when that env is set (narrow-only). A `folder_id` or `file_ids` argument narrows that call only. The MCP MUST still refuse out-of-scope resources even if the underlying credential could technically reach them. In v1, `AUTHORIZATION_ERROR` is returned when (1) a caller-named `file_id` lies outside a caller-named `folder_id` after Google grants metadata, or (2) a named folder or file lies outside `DRIVE_ALLOWED_FOLDER_ID` after Google grants metadata. Otherwise Google misses are `FILE_NOT_FOUND`. See `contracts/authorization-chain.md`.
- **AC-FR-022**: If the principal's Google authorization does not grant access to a requested resource, the MCP MUST deny it via Google's own check. The MCP MUST NOT implement a parallel authorization model that could diverge from Google's by granting access Google would deny.
- **AC-FR-023**: Denial categories MUST follow this split: (1) a resource outside this call’s stated `RetrievalScope` → `AUTHORIZATION_ERROR`; (2) Google’s grant does not include the resource → `FILE_NOT_FOUND`, and the MCP MUST NOT confirm that the file exists or return its content. The MCP MUST NOT leak content on either path.

#### Per-identity isolation

- **AC-FR-030**: v1 has exactly one Google Drive identity per deployment. Every authenticated MCP caller acts as that identity. Authenticated Drive access state (credentials, grants, in-flight authorization context) MUST be request-scoped and MUST NOT leak across concurrent or successive requests on shared compute. Multiple Google identities in one deployment are out of scope until a MAJOR Article XIV change.

#### Untrusted content / authority boundary

- **AC-FR-040**: Text retrieved from any document — however phrased, including direct imperatives aimed at the system — MUST NOT alter an `AuthorizationDecision`, grant a principal additional scope, or bypass any step in AC-FR-001 (Article VI).
- **AC-FR-041**: This boundary MUST hold structurally (no mutating capability to misuse, Article V) rather than by detecting or filtering adversarial phrasing. Detection, if present, is defense-in-depth, not the guarantee.

#### Failure classification (this context's categories)

- **AC-FR-050**: Failures this context raises MUST be classified as `AUTHENTICATION_ERROR`, `AUTHORIZATION_ERROR` (MCP retrieval-boundary), or `FILE_NOT_FOUND` (Google grant does not include the resource) and MUST NOT be silently treated as empty retrieval (Article XI). Remaining categories belong to Retrieval Core; both contexts share one flat taxonomy at the agent-visible level.

#### Secret hygiene and re-derivable state

- **AC-FR-060**: Logs and error responses MUST NOT contain MCP access tokens, refresh tokens, authorization codes, consent passwords, Google refresh or access tokens, or other credential material, under any error path.
- **AC-FR-061**: Logs MAY capture a non-secret principal identifier per request for audit, and MUST NOT capture the credential itself.
- **AC-FR-062**: MCP access-token verification and Google credential minting MUST be re-derivable on any instance (Article III). Access, refresh, and authorization-code values MUST be self-contained (verifiable without the instance that issued them). DCR client records and used-code / revocation identifiers MAY be in-memory auth protocol state discarded when the instance disappears; hosts re-register (RFC 7591). That protocol state is a documented Article III exception, not Drive content.

### Key Entities

- **Principal**: In v1, the deployment's single Google Drive identity. An MCP OAuth access token proves the caller may use this deployment; it does not select among Google users. The principal identifier in logs is a non-secret deployment/identity label, never a raw credential.
- **McpAccessToken**: Short-lived access token issued by this origin for `/mcp` (OAuth 2.1 auth-code + PKCE). Plan encoding: HS256 JWT (`aud` / resource = `{issuer}/mcp`, scope `drive.read`). Not a Google token. Never a tool argument.
- **ConsentPassword**: Resource-owner password (`MCP_AUTH_TOKEN`). Compared only on consent. MUST NOT succeed as a `/mcp` Bearer.
- **RegisteredClient**: RFC 7591 client record from DCR. In-memory protocol state; discarded on instance death; hosts re-register.
- **Credential**: The MCP-held representation of **Google** authorization for the deployment identity. Never exposed to the agent or language-model context in raw form. Distinct from `McpAccessToken`.
- **AuthorizationDecision**: Outcome of evaluating a request against the chain — `ALLOW`, `AUTHENTICATION_ERROR`, `AUTHORIZATION_ERROR` (MCP retrieval-boundary), or `FILE_NOT_FOUND` (Google grant denial; existence not confirmed).
- **Grant / Scope**: The narrowest practical Google read-only grant associated with a principal. MCP OAuth scope on the access token is a separate, non-Google value (`drive.read`).
- **RetrievalScope**: Resource boundary a specific operation is confined to. **Defined** in Retrieval Core (`specs/002-retrieval-core/data-model.md`, field `default_whole_grant`). **Enforced** here. Default (no folder or file list named) is the whole Google grant for this deployment identity, optionally narrowed by `DRIVE_ALLOWED_FOLDER_ID`; a named folder or file list narrows that call only. Shared implementation lives in `domain/retrieval_scope.py`.

**Vocabulary note**: This context speaks in principal, MCP access token, consent password, Google credential, grant, scope, and authorization decision. Retrieval Core speaks in candidate, content, match, and evidence. That divergence is why these are separate features.

### Invariants

| ID | Statement | Constitution |
| --- | --- | --- |
| AI1 | Authorization is evaluated independently of agent reasoning | Article VII |
| AI2 | Document content cannot acquire authority over MCP policy or auth decisions | Article VI |
| AI3 | An operation never exceeds its authorized RetrievalScope | Article VII |
| AI4 | Credential and authorization state is request-scoped and does not leak across requests (v1: one Drive identity per deployment) | Article VII |
| AI5 | Google's authorization is the final, non-bypassable check | Article VII |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of calls without an authenticated principal are refused before any Drive content or metadata for a specific resource is returned.
- **SC-002**: 100% of calls for a resource the principal's Google grant does not include are denied; the agent never receives that resource's content regardless of how the request is phrased.
- **SC-003**: In adversarial-document tests, retrieved instructions produce **zero** changes to any authorization decision (no extra grant, no skipped chain step, no policy change).
- **SC-004**: Two concurrent requests against the same deployment identity share **zero** leftover credential, grant, or authorization-context observations.
- **SC-005**: Audit of responses, error bodies, and logs after success and failure paths finds **zero** raw token or credential material.
- **SC-006**: 100% of MCP retrieval-boundary denials (v1: granted named `file_id` outside named `folder_id`, or granted named resource outside `DRIVE_ALLOWED_FOLDER_ID`) are labeled `AUTHORIZATION_ERROR`. 100% of Google-grant denials are labeled `FILE_NOT_FOUND` (existence not confirmed). Neither path is labeled as empty successful retrieval. `drive_read` Google misses are `FILE_NOT_FOUND`.
- **SC-007**: 100% of Streamable HTTP `/mcp` calls that present `MCP_AUTH_TOKEN` as Bearer are refused as HTTP 401 before Drive I/O. 100% of successful `/mcp` Bearer values are access tokens issued by this origin’s auth-code + PKCE flow (or a test helper that mints the same token type).

## Assumptions

- v1 is one authenticated Google identity per deployment (constitution preamble; clarified 2026-09-08). MCP authentication is still mandatory so unauthenticated callers cannot use the deployment. Isolation means request-scoped credentials and no leftover auth state — not multiple Google users. Multi-tenant federation and cross-organization access are out of scope until a MAJOR Article XIV change.
- MCP caller authentication **protocol** (auth-code + PKCE S256, DCR, RFC 9728, consent password vs access token, split from Google OAuth) is specified here (AC-FR-012). Token encoding, TTLs, signing-key derivation, and in-memory DCR storage are plan-level (Article XII) and MUST still satisfy AC-FR-011, AC-FR-060, and AC-FR-062.
- Whether principal identifiers in logs are hashed or used as-is is a plan-level choice bounded by AC-FR-061.
- Widening or narrowing the granted read-only OAuth scope over the feature lifecycle is a plan-level change; it MUST remain read-only (Article V) and as narrow as practical (AC-FR-020).
- Retrieval tool semantics (`drive_ls`, `drive_find`, `drive_read`, `drive_grep`) live in Retrieval Core. This spec does not define what a cleared call retrieves.
- `FILE_NOT_FOUND` is the Google-grant denial category (no existence leak). `AUTHORIZATION_ERROR` is the MCP retrieval-boundary denial category (v1: granted `file_id` outside named `folder_id` on `drive_grep`, or granted resource outside `DRIVE_ALLOWED_FOLDER_ID`). Both are part of the shared agent-visible taxonomy; Retrieval Core also raises `FILE_NOT_FOUND` for genuinely missing files after authorization has cleared, using the same `map_google_error()` helper.
- Write, share, and permission modification have nothing to grant here — only to deny — because Article V provides no mutating capability.

## Out of Scope

- What a cleared call is allowed to retrieve (Retrieval Core tool semantics). `RetrievalScope` **fields** are defined in Retrieval Core; this context still specifies and implements **enforcement**.
- Multi-tenant identity federation or cross-organization access models (MAJOR under Article XIV).
- Any write, share, or permission-modification capability.
- OAuth library, HTTP transport, JWT codec, and DCR storage technology choices (plan.md; Article XII). The OAuth 2.1 **protocol** itself is in scope (AC-FR-012).

## Dependencies

- Downstream: Retrieval Core (`specs/002-retrieval-core/spec.md`) consumes this context as a conformist — it assumes every call has already cleared the chain.
- Google remains the authoritative permission store (Article I, VII). Nothing this MCP caches or infers is an authorization source of truth.
