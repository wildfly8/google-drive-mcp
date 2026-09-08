# Feature Specification: Access Control Boundary

**Feature Branch**: `001-access-control`

**Created**: 2026-09-08

**Status**: Draft

**Input**: User description: "Bounded context for who may act and on what authority over the Google Drive Agentic Retrieval MCP. Every call must pass an identical independently-enforced authorization chain before it reaches Drive. Document content is untrusted and cannot acquire authority. Retrieval Core is a conformist consumer of this context."

**Constitution**: Ratified v1.0.0 (Articles VI, VII, V, XIV). Source attachments cited Constitution v2.0.0; this spec conforms to the ratified v1.0.0 text in `.specify/memory/constitution.md`.

**Bounded Context**: Access Control / Authorization Boundary

**Relationship**: Upstream of Retrieval Core (`specs/002-retrieval-core/spec.md`). Retrieval Core never forms its own opinion about whether a call is authorized; it only executes calls this context has already cleared (Article VII).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every call must clear the same authority chain (Priority: P1)

An agent asks the MCP to discover, read, or search Drive content. Before any Drive resource is touched, the call is authenticated as a principal, authorized by the MCP for that operation and retrieval scope, then checked by Google's own authorization. A convincing prompt, a prior successful call, or text inside a document does not skip or satisfy any step. If any step fails, the call stops there.

**Why this priority**: Without an independently evaluated chain, every other retrieval guarantee is bypassable. Article VII is the security invariant this story encodes.

**Independent Test**: Issue an unauthenticated call and a call whose principal is not granted the requested resource. Confirm neither reaches Drive content, each failure is classified as authentication or authorization (never as empty retrieval), and authenticated-but-unauthorized is distinct from unauthenticated.

**Acceptance Scenarios**:

1. **Given** no authenticated principal, **When** any retrieval call is issued, **Then** the MCP refuses the call as `AUTHENTICATION_ERROR` before any Drive resource is accessed.
2. **Given** an authenticated principal whose Google grant does not include a requested file, **When** they ask to retrieve that file (however the request is phrased), **Then** the MCP denies the call as `AUTHORIZATION_ERROR` or `FILE_NOT_FOUND` without returning that file's content.
3. **Given** a prior successful retrieval by the same principal, **When** a later call is issued for a resource they are not granted, **Then** the prior success is not treated as a credential and the new call is evaluated from the first chain step.
4. **Given** a request that fails MCP authentication, **When** later chain steps would have passed, **Then** those later steps are never evaluated (no default-allow).

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

The MCP holds Google authorization material for a principal. The agent and any language-model context never see raw tokens. Logs and error messages never print them. Credential and authorization state for one principal is never reused for another, including when concurrent requests share compute. v1 deploys one Google identity, but isolation must still hold as a structural property.

**Why this priority**: Secret leakage or cross-principal reuse would violate Article VII even if the happy path looks correct. Independent of Retrieval Core tool semantics.

**Independent Test**: Inspect responses and logs for token material after success and failure paths. Drive two concurrent requests with distinct principal contexts (or simulated distinct contexts) and confirm neither observes the other's credential or scope state.

**Acceptance Scenarios**:

1. **Given** any successful or failed call, **When** the agent inspects the response, **Then** no OAuth refresh token, access token, or raw credential appears.
2. **Given** any error path, **When** logs are examined, **Then** they contain at most a non-secret principal identifier and never credential material.
3. **Given** two concurrent requests with different principals, **When** both are in flight on shared compute, **Then** neither request observes or reuses the other's credential, grant, or authorization context.
4. **Given** a compute instance that disappears after a request, **When** the next request arrives on another instance, **Then** authorization is re-derived for that request and does not depend on leftover instance state.

---

### Edge Cases

- Unauthenticated vs unauthorized vs not-found MUST remain distinct categories; an authorization denial MUST NOT be reported as empty retrieval (Article XI, X).
- On denial, the MCP MUST NOT leak resource existence, metadata, or content beyond what is required to return the correct non-leaking category (`AUTHORIZATION_ERROR` or `FILE_NOT_FOUND`).
- A request MUST NOT proceed to step N of the chain if step N-1 did not explicitly pass.
- MCP-level retrieval-scope confinement applies even if the underlying Google credential could technically reach further (the MCP MUST still refuse out-of-scope resources).
- Google's authorization is the final non-bypassable check; the MCP MUST NOT implement a parallel allow-list that could grant access Google would deny.
- Write, share, and permission-modification are not grantable here: this context only denies them, because Article V provides no mutating capability to authorize.

## Requirements *(mandatory)*

### Functional Requirements

#### Authorization chain

- **AC-FR-001**: Every call MUST be evaluated in this exact order, every time, with no step skippable: agent request → MCP authentication → MCP authorization → Google authorization → resource (Article VII).
- **AC-FR-002**: A request MUST NOT reach step N if step N-1 did not explicitly pass. There is no default-allow state.
- **AC-FR-003**: No agent-supplied justification, instruction, or prior successful call MAY be treated as satisfying any step in this chain. A convincing request is not a credential.

#### Authentication

- **AC-FR-010**: The MCP endpoint MUST require authentication; unauthenticated arbitrary access MUST NOT be possible.
- **AC-FR-011**: Raw Google refresh or access tokens MUST NOT be exposed to the agent or to language-model context. The MCP holds a dedicated credential representation for the principal.

#### Authorization and scope

- **AC-FR-020**: Google credentials MUST use the narrowest practical read-only Drive grant sufficient for discovery, content retrieval, and exact search.
- **AC-FR-021**: An operation MUST NOT access Drive resources outside its authorized `RetrievalScope` (defined in Retrieval Core), independent of whether the underlying credential could technically reach further.
- **AC-FR-022**: If the principal's Google authorization does not grant access to a requested resource, the MCP MUST deny it via Google's own check. The MCP MUST NOT implement a parallel authorization model that could diverge from Google's by granting access Google would deny.
- **AC-FR-023**: On denial, the MCP MUST NOT leak resource existence, metadata, or content beyond what is necessary to return `AUTHORIZATION_ERROR` or `FILE_NOT_FOUND` (whichever is the correct, non-leaking category).

#### Per-identity isolation

- **AC-FR-030**: Authenticated Drive access state (credentials, grants, in-flight authorization context) MUST NOT be reused or leaked across different principals, including across concurrent requests on shared compute.

#### Untrusted content / authority boundary

- **AC-FR-040**: Text retrieved from any document — however phrased, including direct imperatives aimed at the system — MUST NOT alter an `AuthorizationDecision`, grant a principal additional scope, or bypass any step in AC-FR-001 (Article VI).
- **AC-FR-041**: This boundary MUST hold structurally (no mutating capability to misuse, Article V) rather than by detecting or filtering adversarial phrasing. Detection, if present, is defense-in-depth, not the guarantee.

#### Failure classification (this context's categories)

- **AC-FR-050**: Authorization-originated failures MUST be classified as `AUTHENTICATION_ERROR` or `AUTHORIZATION_ERROR` and MUST NOT be silently treated as empty retrieval (Article XI). Remaining categories belong to Retrieval Core; both contexts share one flat taxonomy at the agent-visible level.

#### Secret hygiene and re-derivable state

- **AC-FR-060**: Logs and error responses MUST NOT contain OAuth refresh tokens, access tokens, or other credential material, under any error path.
- **AC-FR-061**: Logs MAY capture a non-secret principal identifier per request for audit, and MUST NOT capture the credential itself.
- **AC-FR-062**: Authorization state MUST be re-derivable per request and MUST NOT depend on which compute instance handles it (Article III).

### Key Entities

- **Principal**: The authenticated identity a request is executing as (non-secret identifier only).
- **Credential**: The MCP-held representation of Google authorization. Never exposed to the agent or language-model context in raw form.
- **AuthorizationDecision**: Outcome of evaluating a request against the chain — `ALLOW` or a specific denial category (`AUTHENTICATION_ERROR` or `AUTHORIZATION_ERROR`).
- **Grant / Scope**: The narrowest practical Google read-only grant associated with a principal.
- **RetrievalScope**: Resource boundary a specific operation is confined to. Defined in Retrieval Core; this context enforces that a request never exceeds it.

**Vocabulary note**: This context speaks in principal, credential, grant, scope, and authorization decision. Retrieval Core speaks in candidate, content, match, and evidence. That divergence is why these are separate features.

### Invariants

| ID | Statement | Constitution |
| --- | --- | --- |
| AI1 | Authorization is evaluated independently of agent reasoning | Article VII |
| AI2 | Document content cannot acquire authority over MCP policy or auth decisions | Article VI |
| AI3 | An operation never exceeds its authorized RetrievalScope | Article VII |
| AI4 | Per-principal credential and authorization state is isolated | Article VII |
| AI5 | Google's authorization is the final, non-bypassable check | Article VII |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of calls without an authenticated principal are refused before any Drive content or metadata for a specific resource is returned.
- **SC-002**: 100% of calls for a resource the principal's Google grant does not include are denied; the agent never receives that resource's content regardless of how the request is phrased.
- **SC-003**: In adversarial-document tests, retrieved instructions produce **zero** changes to any authorization decision (no extra grant, no skipped chain step, no policy change).
- **SC-004**: Two concurrent requests from different principals share **zero** credential, grant, or authorization-context observations.
- **SC-005**: Audit of responses, error bodies, and logs after success and failure paths finds **zero** raw token or credential material.
- **SC-006**: 100% of authorization denials are labeled `AUTHENTICATION_ERROR` or `AUTHORIZATION_ERROR` (or the non-leaking not-found category when that is the correct response) and never labeled as empty successful retrieval.

## Assumptions

- v1 is one authenticated Google identity per deployment (constitution preamble). Multi-tenant federation and cross-organization access are out of scope until a MAJOR Article XIV change. Isolation requirements still apply structurally.
- Concrete credential-issuance mechanics (token-exchange pattern, storage technology) are plan-level (Article XII) and MUST still satisfy AC-FR-011, AC-FR-060, and AC-FR-062.
- Whether principal identifiers in logs are hashed or used as-is is a plan-level choice bounded by AC-FR-061.
- Widening or narrowing the granted read-only OAuth scope over the feature lifecycle is a plan-level change; it MUST remain read-only (Article V) and as narrow as practical (AC-FR-020).
- Retrieval tool semantics (`drive_ls`, `drive_find`, `drive_read`, `drive_grep`) live in Retrieval Core. This spec does not define what a cleared call retrieves.
- `FILE_NOT_FOUND` as a non-leaking denial category is owned at the wire level by the shared taxonomy; this context may use it when revealing existence would leak authorization data (AC-FR-023).
- Write, share, and permission modification have nothing to grant here — only to deny — because Article V provides no mutating capability.

## Out of Scope

- What a cleared call is allowed to retrieve (Retrieval Core / `RetrievalScope` definition).
- Multi-tenant identity federation or cross-organization access models (MAJOR under Article XIV).
- Any write, share, or permission-modification capability.
- OAuth library, HTTP transport, and token-storage technology choices (plan.md; Article XII).

## Dependencies

- Downstream: Retrieval Core (`specs/002-retrieval-core/spec.md`) consumes this context as a conformist — it assumes every call has already cleared the chain.
- Google remains the authoritative permission store (Article I, VII). Nothing this MCP caches or infers is an authorization source of truth.
