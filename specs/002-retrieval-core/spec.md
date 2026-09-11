# Feature Specification: Retrieval Core

**Branch**: `main`

**Spec directory**: `specs/002-retrieval-core`

**Created**: 2026-09-08

**Status**: Ready for implementation

**Input**: User description: "Bounded context for discovery, inspection, and exact-match verification over live Google Drive content. Agent-controlled iterative retrieval with Drive as the sole persistent source of truth. No embedding index or application-owned document replica. Access Control is upstream; this spec never makes authorization decisions."

**Constitution**: Ratified v1.0.0 (Articles I–V, VIII–XIII, XIV). Source attachments cited Constitution v2.0.0; this spec conforms to the ratified v1.0.0 text in `.specify/memory/constitution.md`.

**Bounded Context**: Retrieval Core (discovery, inspection, verification)

**Relationship**: Downstream / conformist consumer of Access Control (`specs/001-access-control/spec.md`). Every requirement below assumes a call has already cleared that authorization chain. This spec never restates or substitutes for that chain (Article VII).

## Clarifications

### Session 2026-09-08

- Q: In v1, who is the principal that every Drive call runs as, given the constitution allows only one Google identity per deployment? → A: One Drive identity per deployment. MCP authentication is still required so anonymous callers cannot use it. Concurrent requests share that identity; isolation is no leaked credential state, not multiple Google users. (Owned by Access Control; consumed here.)
- Q: When a call is denied, should the agent be told the file is forbidden, or only that it was not found? → A: Outside the call’s stated retrieval boundary → `AUTHORIZATION_ERROR`. Google does not grant the file → `FILE_NOT_FOUND` (no existence leak). (Owned by Access Control; consumed here.)
- Q: If the agent does not name a folder or file list, what may the call search? → A: Unspecified boundary = the whole Google grant for this deployment identity. Optional folder or file list narrows that one call.
- Q: When the agent names a folder for find or exact search, does that include files in nested subfolders? → A: Find and grep on a folder include nested subfolders. List is immediate children only.
- Q: Which file kinds must v1 be able to read and exact-search, and what happens for everything else? → A: Required: Docs, Sheets, Slides. Also: other Drive files that yield usable text. Non-text/unreadable types → unsupported error (never empty success).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover candidates, then read current content (Priority: P1)

An agent needs an answer that may live in the user's Drive. It lists a folder or searches metadata to find *candidates* (not yet evidence), then retrieves the current content of a chosen file. Discovery returns topology and metadata only. A read returns content taken from Drive at call time, with provenance attached. The agent decides whether that is enough; the MCP does not.

**Why this priority**: This is the minimum viable retrieval loop (discover → read). Without it, later exact-search and iteration have nothing to operate on. Articles I, IV, V, VIII.

**Independent Test**: Place an accessible document with known text. Discover it without receiving body content, then read it and confirm the body matches Drive's current content and carries file id, name, and modified time.

**Acceptance Scenarios**:

1. **Given** an accessible folder, **When** the agent enumerates it with `drive_ls`, **Then** each child is returned with id, name, type, folder flag, modified time, and view link, and **no** document body is included.
2. **Given** accessible files whose names or types match a query, including files nested under a named folder, **When** the agent runs `drive_find` on that folder, **Then** it receives `SearchCandidate` records for matching descendants (not only immediate children) that are not labeled or treated as verified evidence.
3. **Given** a known `file_id` the principal may read, **When** the agent runs `drive_read`, **Then** it receives current `DocumentContent` sourced from Drive at call time, with provenance intact.
4. **Given** a Google Doc, Sheet, or Slide the principal may read, **When** the agent runs `drive_read`, **Then** it receives a usable text representation with provenance intact.
5. **Given** another Drive file that yields usable text, **When** the agent reads it, **Then** the text is returned with provenance.
6. **Given** a Drive file that cannot yield usable text, **When** the agent **reads** it or greps it **by `file_id` alone**, **Then** the call fails as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE`, not as empty success. **Given** a folder or whole-grant grep whose targets include some unsupported files and some searchable files, **When** the agent greps that scope, **Then** unsupported files are skipped, searchable files are searched, and status is `PARTIAL` with a reason (not a whole-call unsupported error). If **every** target is unsupported, the call fails as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE`.

---

### User Story 2 - Exact search turns retrieved bytes into evidence (Priority: P1)

The agent has candidates and wants to verify a specific claim. It runs exact-match search (`drive_grep`) over identified files or a folder. Hits include the matched text, location, and provenance. A hit is still only evidence after content has been retrieved and, when checking a claim, exactly matched (Article VIII). No match returns an empty match list with status `EMPTY` — never a fabricated hit. Identical bytes and identical pattern produce identical results within the current request (Article IX).

**Why this priority**: Exact search is the verification primitive that makes retrieval trustworthy without a semantic index (Article II, IX).

**Independent Test**: Put a unique phrase in one accessible document. Grep for it and confirm the originating file, matched text, and provenance. Grep for a phrase that does not occur and confirm `matches: []` with status `EMPTY`. Repeat the same grep on the same retrieved bytes and confirm identical matches.

**Acceptance Scenarios**:

1. **Given** an accessible document containing a unique phrase, **When** the agent greps that phrase, **Then** the result identifies the file and includes matched text plus provenance (`file_id`, name, modified time at minimum).
2. **Given** identical retrieved bytes and identical search parameters within one request, **When** grep is repeated, **Then** the matches are identical.
3. **Given** no occurrence of the pattern in the searched bytes, **When** grep completes within its limits, **Then** status is `EMPTY` with an empty match list — never a fabricated match.
4. **Given** `case_sensitive = false` versus `true`, **When** the same pattern is used, **Then** case-insensitive and exact-case modes are unambiguously different.
5. **Given** `regex = true` versus literal mode, **When** the same pattern string is used, **Then** regular-expression interpretation and literal interpretation are unambiguously distinguished.

---

### User Story 3 - Iterate without a RAG index (Priority: P1)

A single query is not assumed sufficient. The agent chains find → read → grep → read → grep, possibly changing terms as it reasons (for example "idempotency" then "deduplication key"). The MCP never decides sufficiency and never synthesizes the final answer (Article IV). No embedding store, vector index, or application-owned replica is required for correctness (Article II). After the operation, exported bytes are gone (Article III).

**Why this priority**: This is the constitutional retrieval model. Shipping an index "because RAG is conventional" would be non-conforming.

**Independent Test**: Run a multi-step chain against live Drive with no persistent retrieval index configured. Confirm each step returns candidates, content, or matches with provenance, and that temporary exports do not remain as application-owned storage afterward.

**Acceptance Scenarios**:

1. **Given** a question whose answer spans more than one document, **When** the agent chains `drive_find` → `drive_read` → `drive_grep` → `drive_read` → `drive_grep`, **Then** each step succeeds using live Drive content and no persistent retrieval index.
2. **Given** completed operations, **When** application-owned storage is inspected, **Then** exported or downloaded document bytes from those operations are absent.
3. **Given** two consecutive requests handled independently (including on different compute instances), **When** the same authorized reads are issued, **Then** each request is correct on its own and does not depend on leftover local files from the other.

---

### User Story 4 - Freshness and visible completeness (Priority: P2)

Drive is the only source of truth. After a document changes in Drive, a later read reflects the newer content once Drive itself exposes it. If a search or listing hits a resource limit (file count, bytes, time, match count, sustained rate-limiting), the agent is told coverage was `PARTIAL` — never `EMPTY` or `COMPLETE` by omission. "Nothing found" and "not fully searched" are different outcomes (Article X).

**Why this priority**: Stale copies and silent truncation would make the agent over-trust incomplete evidence.

**Independent Test**: Modify an accessible document, then re-read it and confirm the update. Run a grep or find with a limit smaller than the corpus and confirm status `PARTIAL` with an explicit reason.

**Acceptance Scenarios**:

1. **Given** a document the agent already read, **When** that document is modified in Drive and the agent reads it again, **Then** the new content is returned once Drive itself reflects the change — never a stale MCP-owned copy.
2. **Given** a search or listing that hits a configured limit while more results could exist, **When** the operation finishes, **Then** status is `PARTIAL` with a reason, never `EMPTY` or `COMPLETE`.
3. **Given** sustained rate-limiting that cuts a search or listing walk short, **When** the operation returns, **Then** that is reported as completeness: `status: PARTIAL` with `partial_reason: RATE_LIMITED` (even if zero items were collected). It MUST NOT be `EMPTY` or `COMPLETE`, and MUST NOT be swallowed by a silent retry that claims completeness. A single-file read/export blocked by HTTP 429 with no usable prefix is `ErrorEnvelope` category `RATE_LIMITED` instead.

---

### Edge Cases

- Pagination (`max_results`, `page_token`) MUST NOT report `COMPLETE` when results were silently truncated (FR-003, FR-041).
- `drive_ls` enumerates immediate children only; `drive_find` and `drive_grep` on a `folder_id` include nested descendants. A recursive search that hits a limit MUST report `PARTIAL`, not a silent miss.
- Unspecified `RetrievalScope` (`default_whole_grant`) means the whole Google grant. `drive_ls` **projects** that grant onto the immediate children of My Drive `root`. `drive_find` / `drive_grep` with no folder or file list search the whole grant (subject to budgets). Agents MUST NOT assume omitted-folder `ls` and omitted-folder `find` return the same universe.
- `drive_ls` MUST NOT return document bodies.
- Discovery results MUST NOT be presented as verified evidence.
- Unsupported or non-exportable content: **single-id** read or grep → classified error (`UNSUPPORTED_MIME_TYPE` / `FILE_NOT_EXPORTABLE`), not empty success. **Folder or whole-grant grep** with mixed types → skip unsupported, search the rest, `PARTIAL`; if every target is unsupported → classified error. v1 required types are Google Docs, Sheets, and Slides; other Drive files are supported only when they yield usable text. Drive often labels Markdown/MDX as `application/octet-stream`; those blobs MUST still yield usable text when the filename has a known text extension (FR-021).
- Invalid arguments MUST be `INVALID_ARGUMENT`.
- Upstream Drive failures MUST be `DRIVE_API_ERROR` (or equivalent upstream-failure category) rather than a generic error (Article XI). Authentication and authorization errors are raised by Access Control, not this context. `drive_read` / `drive_ls` / `drive_find` never emit `AUTHORIZATION_ERROR` in v1.
- Optional `max_bytes` on read: a usable prefix MUST surface as `PARTIAL` (`partial_reason: max_bytes`), not as complete content. A hard export refusal with **no** usable prefix MUST be `RESOURCE_LIMIT` (not `PARTIAL`).
- `context_lines` on grep, when set, SHOULD give enough surrounding text to interpret a match without a mandatory follow-up read; defaults for non-line-oriented formats (Sheets/Slides) are a plan-level choice.
- No write, delete, share, move, create, or permission-modification tool exists; there is no code path that could mutate Drive (Article V).

## Requirements *(mandatory)*

### Functional Requirements

#### Discovery — `drive_ls`

- **FR-001**: MUST enumerate the immediate children of a given `folder_id`, returning `id, name, mime_type, is_folder, modified_time, source_url` per child (`source_url` maps from Drive `webViewLink`). When `folder_id` is omitted, MUST enumerate the immediate children of My Drive `root` (a projection of `default_whole_grant`, not a second source of truth).
- **FR-002**: MUST NOT read or return document content — metadata and topology only (Article V).
- **FR-003**: MUST support `max_results` and `page_token` without silently truncating results while reporting completeness as `COMPLETE` (see result status).

#### Discovery — `drive_find`

- **FR-010**: MUST discover `SearchCandidate[]` using metadata and/or Drive-native discovery, filterable by `name_pattern, mime_type, folder_id, modified_after, modified_before, trashed, max_results`. When `folder_id` is omitted, discovery runs within the default `RetrievalScope` (the whole Google grant for this deployment identity). When `folder_id` is named, discovery MUST include descendants of that folder, not only its immediate children.
- **FR-011**: MUST NOT represent returned candidates as verified evidence (Article VIII).

#### Inspection — `drive_read`

- **FR-020**: MUST retrieve current, authoritative `DocumentContent` for a given `file_id` directly from live Drive at call time — never from a prior MCP-owned copy (Articles I, IX).
- **FR-021**: MUST obtain a usable text representation appropriate to the file type. v1 MUST support Google Docs, Sheets, and Slides. v1 MUST also support other Drive files that yield usable text (for example plain text, Markdown/MDX, or similarly text-extractable files — including blobs Google labels `application/octet-stream` when the filename has a known text extension). How export versus download is implemented is infrastructure (Article XII).
- **FR-021a**: A type that cannot yield usable text MUST fail as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` when the operation’s target is that file alone (`drive_read`, or `drive_grep` with only `file_ids` and every named id unsupported) — never as empty successful retrieval or fabricated empty content. Folder or whole-grant `drive_grep` follows FR-037.
- **FR-022**: MUST support optional `content_format` and `max_bytes`. Omitted `content_format` MUST use the plan-level export/download MIME for that Drive type (research export map). An unknown or type-incompatible `content_format` MUST be `INVALID_ARGUMENT`.
- **FR-023**: If the same file is re-read after being modified in Drive, the result MUST reflect the newer content when Drive itself makes it available.

#### Verification — `drive_grep`

- **FR-030**: MUST perform deterministic exact-content search over one or more files, identified by `file_ids` and/or `folder_id`, given `pattern, case_sensitive?, regex?, context_lines?, max_matches?`. When neither `file_ids` nor `folder_id` is named, grep runs within the default `RetrievalScope` (the whole Google grant for this deployment identity), subject to resource limits and `PARTIAL` completeness (FR-041). When `folder_id` is named, grep MUST search that folder’s descendants, not only its immediate children.
- **FR-031**: For identical retrieved bytes and identical parameters, results MUST be identical (Article IX) within the current request. A changed Drive document MAY change results on a subsequent call.
- **FR-032**: When `case_sensitive = false`, matching MUST be case-insensitive; when `true`, case MUST be respected exactly.
- **FR-033**: When `regex = true`, `pattern` MUST be interpreted as a regular expression, not a literal string; literal and regex modes MUST be unambiguously distinguished.
- **FR-034**: When `context_lines` is set, results SHOULD include enough surrounding content to interpret the match without a follow-up read.
- **FR-035**: MUST retrieve target content, search it, return matches with provenance, and discard the transient content after the operation completes (Article III).
- **FR-036**: On no match, MUST return `matches: []` and status `EMPTY` — MUST NOT fabricate a match.
- **FR-037**: When `drive_grep` walks a `folder_id` or `default_whole_grant` and some files cannot yield usable text, MUST skip those files, search the rest, and return `PARTIAL` with a reason that unsupported files were skipped. If every target is unsupported, MUST fail as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` (same categories as FR-021a).

#### Result status (cross-cutting)

- **FR-040**: Every retrieval operation MUST report exactly one of `COMPLETE`, `PARTIAL`, `EMPTY`, `ERROR`.
- **FR-041**: `PARTIAL` MUST be returned whenever a resource or result-limit boundary (file count, byte size, execution time, match count, sustained rate-limiting) could plausibly have found more — it MUST NOT be reported as `EMPTY` or `COMPLETE` (Article X).
- **FR-042**: A truncated result MUST never claim completeness by omission.

#### Provenance (cross-cutting)

- **FR-050**: Every content-derived result MUST include, at minimum: `file_id, file_name, mime_type, modified_time, source_url, retrieved_at`. A result missing `file_id` is invalid (Article VIII). `drive_grep` matches MUST also include `matched_text` and `location`. `drive_read` MUST NOT require match fields.
- **FR-051**: Provenance MUST remain intact end-to-end: Drive → search result → agent context. No step MAY drop it.

#### Error domain (this context's categories)

- **FR-060**: Retrieval-originated errors MUST be classified by cause using the canonical enum in `specs/001-access-control/contracts/error-taxonomy.md` — at minimum the categories this context produces: `FILE_NOT_FOUND`, `FILE_NOT_EXPORTABLE`, `UNSUPPORTED_MIME_TYPE`, `DRIVE_API_ERROR`, `RATE_LIMITED`, `RESOURCE_LIMIT`, `TEMPORARY_STORAGE_ERROR`, `SEARCH_ERROR`, `INVALID_ARGUMENT` (Article XI). `AUTHENTICATION_ERROR` and `AUTHORIZATION_ERROR` belong to Access Control and are raised upstream. Access Control also raises `FILE_NOT_FOUND` before this context when Google’s grant does not include the resource; after a call is cleared, this context raises `FILE_NOT_FOUND` only for a resource that is genuinely missing or not visible after that check, via the same `map_google_error()` helper. Walks cut short by rate-limit are `PARTIAL` (FR-041), not `ErrorEnvelope` `RATE_LIMITED`.
- **FR-061**: Errors MUST NOT leak credential material in any form (defense-in-depth; primary guarantee owned by Access Control).

#### Untrusted content (content-handling half)

- **FR-080**: Text retrieved from any document MUST be treated exclusively as data by this context's tools — it MUST NOT alter tool behavior, output shape, or control flow within `drive_ls` / `drive_find` / `drive_read` / `drive_grep` (Article VI). Whether such content could improperly affect *authorization* is Access Control's guarantee (`AC-FR-040`), not this one.

#### Capability surface

- **FR-090**: The exposed surface is read/search/enumerate only: `drive_ls`, `drive_find`, `drive_read`, `drive_grep`. There MUST be no capability (and no code path) to write, delete, share, move, create, or modify permissions (Article V). Drive state after a valid call MUST equal Drive state before.

#### Ephemerality, agnosticism, budgets

- **FR-100**: Exported or downloaded content MUST be processed as request-scoped working material and MUST NOT become persistent application state (Article III). Any exception MUST be an explicit, documented deviation and would be a MAJOR change (Article XIV).
- **FR-101**: The server MUST behave correctly regardless of which compute instance handles a given request, and MUST tolerate loss of local temporary storage between requests.
- **FR-102**: No tool's meaning or required call pattern MAY depend on a specific LLM vendor's prompting conventions (Article XIII).
- **FR-103**: Logs SHOULD capture `request_id, tool, file count, bytes processed, duration, result count, status, error category`. Logs MUST NOT contain full document content. Principal-identifier logging is owned by Access Control.
- **FR-104**: Every operation SHOULD have bounded consumption (`max_files, max_bytes` per file, `max_bytes` per operation, `max_matches, max_execution_time, max_context_lines, max_export_size`) and MUST surface a budget breach as `PARTIAL` with a reason when a usable prefix or partial listing exists. A hard export refusal with no usable prefix MUST be `RESOURCE_LIMIT`. Exact numeric defaults are plan-level.
- **FR-105**: Priority is correctness → retrieval quality → security → simplicity, before latency or cost optimization. No persistent index MAY be introduced for hypothetical performance gains alone (Articles II, XIV).

### Key Entities

- **DriveFile**: Domain fields `id, name, mime_type, parents[], modified_time, created_time, web_view_link, size?, owners?, trashed`. On the wire, the view link is `source_url` (mapped from Drive `webViewLink`). Drive API camelCase is adapter-only.
- **Folder**: A DriveFile acting as a container; hierarchy is a discovery signal, not a second source of truth.
- **DocumentContent**: Ephemeral, retrieval-time representation of a file's content: `file_id, mime_type, content, retrieved_at, representation`. Never persists beyond the operation (Article III).
- **SearchCandidate**: A DriveFile surfaced as possibly relevant: `file, reason, discovery_method`. `discovery_method` is `find` (`drive_ls` returns children, not candidates). **Not evidence.**
- **SearchMatch**: A deterministic exact match found in retrieved content: `file_id, file_name, pattern, matched_text, location, context`. A SearchMatch with provenance **is** evidence.
- **Evidence** (conceptual role, not a separate wire type or Python class): content returned to the agent to support reasoning. `DocumentContent` from `drive_read` and `SearchMatch` from `drive_grep` play this role when they carry provenance. `SearchCandidate` never does. Agent inference is not evidence.
- **RetrievalScope**: The bounded set of Drive resources an operation may touch. Field `default_whole_grant` is true when the call names no `folder_id` or `file_ids` (everything the deployment’s Google grant already allows). A named folder or file list narrows that call only. Enforced by Access Control (`AC-FR-021`) via `is_within_scope`. `drive_ls` with `default_whole_grant` lists immediate children of My Drive `root` only.
- **RetrievalOperation**: One MCP invocation: `operation_id, tool, scope, query/pattern, start_time, end_time, result_count, status`.

Domain relationships that MUST hold:

- DriveFile ≠ Evidence
- SearchCandidate ≠ Evidence
- DocumentContent (with provenance) plays Evidence
- SearchMatch (with provenance) plays Evidence
- DocumentContent ≠ persistent cache
- Agent inference ≠ Evidence

### Invariants

| ID | Statement | Constitution |
| --- | --- | --- |
| I1 | Drive state after any operation equals Drive state before | Article V |
| I2 | No persistent document content by default | Article III |
| I3 | Every content-derived result identifies its source file | Article VIII |
| I4 | No fabricated matches — a SearchMatch corresponds to real retrieved content | Articles VIII, VI |
| I5 | Temporary content does not survive beyond its operation | Article III |
| I6 | Deterministic grep for identical bytes and parameters, within a request | Article IX |
| I7 | A new read or grep never relies on a stale persistent copy | Articles I, IX |
| I8 | Discovery results are never represented as verified evidence | Article VIII |
| I9 | Unspecified scope is the whole grant; `drive_ls` projects that onto My Drive `root` children | Articles I, VII |

Scope enforcement and credential use are Access Control invariants AI3/AI4, not retrieval invariants.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Given an accessible document containing known target text, an agent can locate it by discovery and retrieve that text on the first authorized attempt, with the originating file identified.
- **SC-002**: Exact-match search for a phrase that exists in retrieved content returns the matching document and matched excerpt with provenance in 100% of such cases (no fabricated hits when the phrase is absent).
- **SC-003**: An agent can complete a multi-step find → read → grep → read → grep chain with **zero** persistent retrieval index involved, and still produce cited evidence.
- **SC-004**: After a document is updated in Drive, a subsequent read returns the updated content once Drive itself reflects the change (0 uses of an MCP-owned stale copy).
- **SC-005**: When a search or listing hits a configured limit while more coverage was possible, 100% of those outcomes are reported as `PARTIAL` (including rate-limited walks via `partial_reason: RATE_LIMITED`), never as empty or complete.
- **SC-006**: After any operation completes, 100% of exported or downloaded bytes from that operation are absent from persistent application storage.
- **SC-007**: Correctness holds when two consecutive requests are handled independently (including on different compute instances): 0 reliance on leftover local working material.
- **SC-008**: 100% of content-derived results include a correct originating `file_id`.
- **SC-009**: 100% of reads of accessible Google Docs, Sheets, and Slides return a usable text representation with originating `file_id`. Accessible Drive files that yield usable text also succeed. Types that cannot yield text fail as unsupported/non-exportable in 100% of those cases — never as empty success.

## Assumptions

- Calls reaching these tools have already cleared Access Control. This spec does not re-implement authentication or authorization.
- Exact numeric resource-budget defaults (`max_files`, `max_bytes`, `max_matches`, `max_execution_time`, `max_context_lines`, `max_export_size`) are fixed during planning; the requirement is that bounds exist and breaches are visible as `PARTIAL`.
- Whether grep context defaults to line-based or character-offset windows for non-line-oriented formats (Sheets/Slides) is a plan-level decision; both MUST still carry provenance.
- Matching-engine choice (regex library, etc.) is infrastructure (Article XII) and MUST preserve FR-031 determinism.
- Concrete growth process for error taxonomy categories is specification-level and MAY grow without amending the constitution (Article XI).
- v1 is one Google identity per deployment; permission isolation and dual-identity tests live in Access Control and are out of this context. Retrieval tools always run as that single Drive identity after Access Control has cleared the call.
- Semantic or vector retrieval is out of scope until a demonstrated need and a MAJOR Article XIV specification.
- Opaque binary types that cannot yield usable text are out of v1 retrieval/search except as classified unsupported errors.

## Out of Scope

- Drive synchronization or change-tracking service
- Document management or editing
- Vector database, semantic search, or reranking
- Persistent document cache or offline mirror
- Full-text indexing independent of live Drive content
- Authentication and authorization (see `specs/001-access-control/spec.md`)
- Architectural decision records, deployment instance lifecycle, and file/module layout (plan.md; Article XII)

## Dependencies

- Upstream: Access Control (`specs/001-access-control/spec.md`) clears every call. Retrieval Core is a conformist consumer.
- Google Drive is the sole persistent source of truth for content and permissions (Article I).
- Future capabilities (for example semantic retrieval) require a demonstrated need the baseline model cannot satisfy and a MAJOR-change specification pass (Articles II, XIV).
