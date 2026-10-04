# Feature Specification: Retrieval Core

**Branch**: `main`

**Spec directory**: `specs/002-retrieval-core`

**Created**: 2026-09-08

**Status**: Implemented (four read-only tools; only `kb` is readable; `DRIVE_ALLOWED_FOLDER_ID` is required, and `scripts/deploy-cloud-run.sh` reads it from Secret Manager; grep input `next_cursor`)

**Input**: User description: "Bounded context for discovery, inspection, and exact-match verification over live Google Drive content. Agent-controlled iterative retrieval with Drive as the sole persistent source of truth. No embedding index or application-owned document replica. Access Control is upstream; this spec never makes authorization decisions."

**Constitution**: v2.1.0 (amended 2026-10-04: Article VIII now has answers cite the connector once, with a link beside text quoted from Stack Exchange) (Articles I–V, VIII–XIII, XIV). Written against ratified v1.0.0; FR-050a and T082 carry the MAJOR amendment of Article VIII, the only article that changed.

**Bounded Context**: Retrieval Core (discovery, inspection, verification)

**Relationship**: Downstream / conformist consumer of Access Control (`specs/001-access-control/spec.md`). Every requirement below assumes a call has already cleared that authorization chain. This spec never restates or substitutes for that chain (Article VII).

## Clarifications

### Session 2026-09-08

- Q: In v1, who is the principal that every Drive call runs as, given the constitution allows only one Google identity per deployment? → A: One Drive identity per deployment. MCP authentication is still required so anonymous callers cannot use it. Concurrent requests share that identity; isolation is no leaked credential state, not multiple Google users. (Owned by Access Control; consumed here.)
- Q: When a call is denied, should the agent be told the file is forbidden, or only that it was not found? → A: Outside the call’s stated retrieval boundary → `AUTHORIZATION_ERROR`. Google does not grant the file → `FILE_NOT_FOUND` (no existence leak). (Owned by Access Control; consumed here.) For named ids this is superseded by Access Control Session 2026-09-29: an id not proven inside `kb` is `AUTHORIZATION_ERROR` whether or not Google grants it.
- Q: If the agent does not name a folder or file list, what may the call search? → A: `DRIVE_ALLOWED_FOLDER_ID` is required and names the Drive folder `kb`. Omitted `folder_id` on `drive_ls`, `drive_find`, and `drive_grep` is `kb`. A named `folder_id` or `file_id` that is not `kb` or a descendant is `AUTHORIZATION_ERROR`, whether it exists or not. There is no whole-Google-grant mode and no `DRIVE_DEFAULT_FOLDER_ID`. Without the allow-list the server does not start and every call is refused.
- Q: When the agent names a folder for find or exact search, does that include files in nested subfolders? → A: Find and grep on a folder include nested subfolders. List is immediate children only.
- Q: Which file kinds must v1 be able to read and exact-search, and what happens for everything else? → A: Required: Docs, Sheets, Slides. Also: other Drive files that yield usable text. Non-text/unreadable types → unsupported error (never empty success).

### Session 2026-09-13

- Q: When `folder_id` is omitted and the deployment sets `DRIVE_ALLOWED_FOLDER_ID`, does `drive_ls` still list My Drive `root`? → A: No. Access Control (AC-FR-021) rewrites an omitted folder to that allow-listed folder before retrieval runs — narrow-only, never wider than Google. `drive_ls` then lists that folder’s immediate children. Since 2026-09-29 the allow-list is required, so omitted-folder `ls` never lists My Drive `root`. Owned by Access Control; consumed here.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover candidates, then read current content (Priority: P1)

An agent needs an answer that may live in the user's Drive. It lists a folder or searches metadata to find *candidates* (not yet evidence), then retrieves the current content of a chosen file. Discovery returns topology and metadata only. A read returns content taken from Drive at call time, with provenance attached. The agent decides whether that is enough; the MCP does not.

**Why this priority**: This is the minimum viable retrieval loop (discover → read). Without it, later exact-search and iteration have nothing to operate on. Articles I, IV, V, VIII.

**Independent Test**: Place an accessible document with known text. Discover it without receiving body content, then read it and confirm the body matches Drive's current content and carries file id, name, and modified time.

**Acceptance Scenarios**:

1. **Given** an accessible folder, **When** the agent enumerates it with `drive_ls`, **Then** each child is returned with id, name, type, folder flag, modified time, and the `drive:{id}` locator (not a view link), and **no** document body is included.
2. **Given** accessible files whose names or types match a query, including files nested under a named folder, **When** the agent runs `drive_find` on that folder, **Then** it receives `SearchCandidate` records for matching descendants (not only immediate children) that are not labeled or treated as verified evidence. Non-matching siblings do not consume `max_results`.
3. **Given** a known `file_id` the principal may read, **When** the agent runs `drive_read`, **Then** it receives current `DocumentContent` sourced from Drive at call time, with provenance intact.
4. **Given** a Google Doc, Sheet, or Slide the principal may read, **When** the agent runs `drive_read`, **Then** it receives a usable text representation with provenance intact.
5. **Given** another Drive file that yields usable text, **When** the agent reads it, **Then** the text is returned with provenance.
6. **Given** a Drive file that cannot yield usable text, **When** the agent **reads** it or greps it **by `file_id` alone**, **Then** the call fails as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE`, not as empty success. **Given** a folder grep whose targets include some unsupported files and some searchable files, **When** the agent greps that scope, **Then** unsupported files are skipped, searchable files are searched, and status is `PARTIAL` with a reason (not a whole-call unsupported error). If **every** target is unsupported, the call fails as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE`.

---

### User Story 2 - Exact search turns retrieved bytes into evidence (Priority: P1)

The agent has candidates and wants to verify a specific claim. It runs exact-match search (`drive_grep`) over identified files or a folder. Hits include the matched text, location, and provenance. A hit is still only evidence after content has been retrieved and, when checking a claim, exactly matched (Article VIII). A finished slice with no match and nothing deferred returns an empty match list with status `EMPTY` — never a fabricated hit. Identical bytes and identical pattern produce identical results within the current request (Article IX).

**Why this priority**: Exact search is the verification primitive that makes retrieval trustworthy without a semantic index (Article II, IX).

**Independent Test**: Put a unique phrase in one accessible document. Grep for it and confirm the originating file, matched text, and provenance. Grep for a phrase that does not occur and confirm `matches: []` with status `EMPTY`. Repeat the same grep on the same retrieved bytes and confirm identical matches.

**Acceptance Scenarios**:

1. **Given** an accessible document containing a unique phrase, **When** the agent greps that phrase, **Then** the result identifies the file and includes matched text plus provenance (`file_id`, name, modified time at minimum).
2. **Given** identical retrieved bytes and identical search parameters within one request, **When** grep is repeated, **Then** the matches are identical.
3. **Given** no occurrence of the pattern in the searched bytes, **When** grep finishes that slice with nothing deferred and no budget cut, **Then** status is `EMPTY` with an empty match list — never a fabricated match.
4. **Given** `case_sensitive = false` versus `true`, **When** the same pattern is used, **Then** case-insensitive and exact-case modes are unambiguously different.
5. **Given** `regex = true` versus literal mode, **When** the same pattern string is used, **Then** regular-expression interpretation and literal interpretation are unambiguously distinguished.
6. **Given** a folder that holds a small file and a file whose known size does not fit the bytes left in the call, **When** the agent greps that folder, **Then** the small file is scanned, the large id is returned in `deferred_file_ids` without a download, and status is `PARTIAL`. A later call with one of those ids searches that file. When `next_cursor` is present, the same pattern, flags and scope with `cursor` continue from that point: after the last scanned file, or inside a file after a `max_matches` stop.

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
- `DRIVE_ALLOWED_FOLDER_ID` is required (`kb` on this deployment). Access Control rewrites an omitted `folder_id` on `drive_ls`, `drive_find`, and `drive_grep` to that folder before retrieval runs. `drive_ls` then lists `kb`’s immediate children; find and grep search `kb` and its descendants. A named `folder_id` or `file_id` that is not `kb` or a descendant is `AUTHORIZATION_ERROR`, whether it exists or not. Unspecified `RetrievalScope` (`default_whole_grant`) is refused, never widened to the whole Google grant, and no retrieval path lists Drive without a folder, so My Drive `root` is never listed.
- Folder listings (`drive_ls` children and find/grep walks) MUST drop a listed child whose `parents` do not include the folder that was listed. Drive answers `files.list` from its search index, and a stale entry must not surface a file outside that folder.
- `drive_ls` MUST NOT return document bodies.
- Discovery results MUST NOT be presented as verified evidence.
- Unsupported or non-exportable content: **single-id** read or grep → classified error (`UNSUPPORTED_MIME_TYPE` / `FILE_NOT_EXPORTABLE`), not empty success. **Folder grep** with mixed types → skip unsupported, search the rest, `PARTIAL`; if every target is unsupported → classified error. v1 required types are Google Docs, Sheets, and Slides; other Drive files are supported only when they yield usable text. Drive often labels Markdown/MDX as `application/octet-stream`; those blobs MUST still yield usable text when the filename has a known text extension (FR-021).
- Invalid arguments MUST be `INVALID_ARGUMENT`. Each tool accepts only the argument keys its body reads; any other key (for example `file_id` on `drive_ls`) is `INVALID_ARGUMENT` after MCP authentication and before the authorization chain makes any Drive call, so the chain and the tool body always see the same scope.
- Upstream Drive failures MUST be `DRIVE_API_ERROR` (or equivalent upstream-failure category) rather than a generic error (Article XI). Authentication and authorization errors are raised by Access Control, not this context. Every tool gets `AUTHORIZATION_ERROR` when Access Control’s allow-list (`DRIVE_ALLOWED_FOLDER_ID`) does not prove a named id is inside `kb`, including an id that Google does not grant or that does not exist. `FILE_NOT_FOUND` is left for an id already proven inside `kb` that Google then misses.
- Optional `max_bytes` on read: a usable prefix MUST surface as `PARTIAL` (`partial_reason: max_bytes`), not as complete content. A hard export refusal with **no** usable prefix MUST be `RESOURCE_LIMIT` (not `PARTIAL`).
- `context_lines` on grep, when set, SHOULD give enough surrounding text to interpret a match without a mandatory follow-up read; defaults for non-line-oriented formats (Sheets/Slides) are a plan-level choice.
- No write, delete, share, move, create, or permission-modification tool exists; there is no code path that could mutate Drive (Article V).

## Requirements *(mandatory)*

### Functional Requirements

#### Discovery — `drive_ls`

- **FR-001**: MUST enumerate the immediate children of a given `folder_id`, returning `id, name, mime_type, is_folder, modified_time, source_url` per child. `source_url` MUST be the non-dereferenceable locator `drive:{id}` (not Drive `webViewLink` and not any `http`/`https` URL). When `folder_id` is omitted, Access Control has already rewritten it to deployment `DRIVE_ALLOWED_FOLDER_ID` (AC-FR-021, narrow-only), so `drive_ls` MUST list that folder’s immediate children. `drive_ls` MUST NOT list My Drive `root` or run without a folder; a call that reaches it with no folder is `AUTHORIZATION_ERROR`. MUST drop a listed child whose `parents` do not include `folder_id`.
- **FR-002**: MUST NOT read or return document content — metadata and topology only (Article V).
- **FR-003**: MUST support `max_results` and `page_token` without silently truncating results while reporting completeness as `COMPLETE` (see result status). More children after a page is `PARTIAL` with `partial_reason: pagination` and `next_page_token`; the next call passes that value as `page_token`. A `page_token` is a decimal offset into the folder's children; one that is not an integer is `INVALID_ARGUMENT`.

#### Discovery — `drive_find`

- **FR-010**: MUST discover `SearchCandidate[]` using metadata and/or Drive-native discovery, filterable by `name_pattern, mime_type, folder_id, modified_after, modified_before, trashed, max_results`. `name_pattern` is a case-insensitive **filename substring**, not a glob and not file contents. Access Control rewrites an omitted `folder_id` to `DRIVE_ALLOWED_FOLDER_ID` (`kb`) before discovery runs; discovery never runs over the whole Google grant. When `folder_id` is named and Access Control allows it, discovery MUST include descendants of that folder, not only its immediate children. A named folder that is not `kb` or a descendant is `AUTHORIZATION_ERROR`, whether it exists or not.
- **FR-011**: MUST NOT represent returned candidates as verified evidence (Article VIII).
- **FR-012**: `drive_find` MUST push `name contains`, `mimeType`, `modifiedTime` bounds, and `trashed = false` (unless `trashed` is true) into the Drive `files.list` query. `max_results` counts matching files (folders only when `mime_type` is the folder type); matching folders are still returned under their own cap of the same size. The walk stops listing at the file cap, so a folder listed after it may be omitted from that `PARTIAL` result. The walk MUST NOT `files.get` each listed child to re-check parents; it checks the `parents` field the listing already returned and drops a child that does not name the listed folder. A finished scan with zero matches is `EMPTY`. Hitting the cap while more matching files remain is `PARTIAL` with `partial_reason: max_files`.

#### Inspection — `drive_read`

- **FR-020**: MUST retrieve current, authoritative `DocumentContent` for a given `file_id` directly from live Drive at call time — never from a prior MCP-owned copy (Articles I, IX).
- **FR-021**: MUST obtain a usable text representation appropriate to the file type. v1 MUST support Google Docs, Sheets, and Slides. v1 MUST also support other Drive files that yield usable text (for example plain text, Markdown/MDX, or similarly text-extractable files — including blobs Google labels `application/octet-stream` when the filename has a known text extension). How export versus download is implemented is infrastructure (Article XII).
- **FR-021a**: A type that cannot yield usable text MUST fail as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` when the operation’s target is that file alone (`drive_read`, or `drive_grep` with only `file_ids` and every named id unsupported) — never as empty successful retrieval or fabricated empty content. A folder id passed to `drive_read`, or named in `file_ids` without `folder_id`, counts as unsupported. Folder `drive_grep` follows FR-037.
- **FR-022**: MUST support optional `content_format` and `max_bytes`. Omitted `content_format` MUST use the plan-level export/download MIME for that Drive type (research export map). An unknown or type-incompatible `content_format` MUST be `INVALID_ARGUMENT`.
- **FR-023**: If the same file is re-read after being modified in Drive, the result MUST reflect the newer content when Drive itself makes it available.

#### Verification — `drive_grep`

- **FR-030**: MUST perform deterministic exact-content search over one or more files, identified by `file_ids` and/or `folder_id`, given `pattern, case_sensitive?, regex?, context_lines?, max_matches?, next_cursor?`. Access Control rewrites an omitted `folder_id` (and no `file_ids`) to `DRIVE_ALLOWED_FOLDER_ID` (`kb`) before grep runs; grep never runs over the whole Google grant. When `folder_id` is named and Access Control allows it, grep MUST search that folder’s descendants, not only its immediate children. A named folder or file that is not `kb` or a descendant is `AUTHORIZATION_ERROR`, whether it exists or not. The input properties `next_cursor` and `cursor` both accept the previous result’s `next_cursor` value and continue from that point. A cursor is a file id (continue after that file) or `file_id:N` (continue inside that file after its first N matches; N is 1 to 10 ASCII digits). With `file_ids`, the cursor MUST name one of them, else `INVALID_ARGUMENT`. A continuation id that is not in a finished listing is `INVALID_ARGUMENT`. `next_cursor` and `cursor` set to two different non-empty values is `INVALID_ARGUMENT`. An empty string starts at the first file.
- **FR-031**: For identical retrieved bytes and identical parameters, results MUST be identical (Article IX) within the current request. A changed Drive document MAY change results on a subsequent call.
- **FR-032**: When `case_sensitive = false`, matching MUST be case-insensitive; when `true`, case MUST be respected exactly.
- **FR-033**: When `regex = true`, `pattern` MUST be interpreted as a regular expression, not a literal string; literal and regex modes MUST be unambiguously distinguished.
- **FR-033a**: `pattern` MUST be at most 512 characters in both modes (the tool schema's `maxLength`, and `INVALID_ARGUMENT` from argument validation for callers that skip the schema). With `regex = true`, a pattern MUST be accepted only when stdlib `re` accepts it (the syntax stays what it was) and its counted repeats unroll to at most 10,000 items (the regex engine writes out minimum repeats when it compiles), else `INVALID_ARGUMENT`. Regex matching MUST be bounded by the time left in the call's `max_execution_time`, with a floor of 0.5 s per file (the first file of a call is searched even past the deadline). A regex that runs out of time MUST stop the scan as `PARTIAL` with `partial_reason: max_execution_time`, keep the matches finished before the stop (whole lines in line-oriented text), and return `next_cursor` in that file: `file_id:N` after N matches there, else the file handled before it (the incoming cursor when it was the call's first file; none on a fresh call's first file, where the host repeats the call). A regex too slow for one file stops at the same place again; hosts simplify the pattern. Literal patterns cannot backtrack and are not timed.
- **FR-034**: When `context_lines` is set, results SHOULD include enough surrounding content to interpret the match without a follow-up read.
- **FR-035**: MUST retrieve target content, search it, return matches with provenance, and discard the transient content after the operation completes (Article III).
- **FR-036**: On no match after the searched slice is finished (nothing deferred, no budget or rate-limit cut), MUST return `matches: []` and status `EMPTY` — MUST NOT fabricate a match. A slice that deferred files or stopped early MUST be `PARTIAL`, not `EMPTY`.
- **FR-037**: When `drive_grep` walks a `folder_id` and some files cannot yield usable text, MUST skip those files, search the rest, and return `PARTIAL` with a reason that unsupported files were skipped. If every target is unsupported, MUST fail as `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` (same categories as FR-021a).
- **FR-038**: A folder `drive_grep` MUST scan shallower files first (the folder's own files, then each level down) and known-smaller files first within a level (FR-038c), and MUST keep the per-file byte cap (a single named `file_id`, including a multi-megabyte export, is searched in that call and is never deferred). When the next file’s known size would exceed the bytes still left in the operation, MUST NOT download it; MUST return that id in `deferred_file_ids` and keep scanning later files that fit (once no operation bytes remain, every later searchable file is deferred) and status `PARTIAL` with `partial_reason: max_bytes`. Unknown size is not deferred solely because remaining bytes are under the per-file cap. Every grep result MUST include `files_scanned` and `bytes_scanned`. `next_cursor` is set when the listing finished and more remains (its forms are in FR-038a and FR-039a), or on a continuation whose listing was cut, where it is the incoming cursor unchanged. A listing cut short by time or HTTP 429 MUST NOT invent a cursor.
- **FR-039**: In a line-oriented representation (Docs, Markdown, plain text), `drive_grep` MUST return at most one match per (file, line). `matched_text` and `location.offset` are the first hit on that line, `location.occurrences` counts every hit on it, and `max_matches` counts lines, not hits. Representations without lines (Sheets, Slides, CSV, JSON) keep one match per hit with a character window.
- **FR-038c**: A folder's listed children MUST be ordered files first, then folders, each by name (case-insensitive, then exact name, then id), since Drive's `files.list` order is unspecified; `drive_ls` pages follow that order, so a `page_token` offset stays stable. `drive_find` MUST walk breadth-first so a folder's own files come before deeper files and a capped result keeps the shallowest matches. Owner decision (2026-10-04): the examined essays sit in `kb`'s root and must be searched and loaded before the archives in its subfolders.
- **FR-038a**: A multi-file `drive_grep` MAY download small files ahead of the scan on worker threads to fit more files in `max_execution_time`, but MUST keep the scan order, and therefore the matches, identical to a one-file-at-a-time scan (FR-031). Files fetched ahead MUST be bounded by count, files left and bytes, and MUST fit the bytes left in the operation. The operation is charged a blob's Drive size when known (the searched text's UTF-8 length otherwise), the same number the download-ahead plans with, so a file fetched ahead is never deferred and a deferred file is never downloaded. Unsupported files are skipped, never deferred. Files fetched ahead are limited to what the call can still use: before any file is searched, one more than the `max_matches` room; after that, the room divided by the hits per file seen so far (no limit while nothing has matched), so a `max_matches` stop wastes few downloads. `partial_reason: max_bytes` means a file was truncated or deferred; reaching the byte cap on the last searchable file finishes the slice. Repeated ids are searched once. A time or rate-limit stop before any file was scanned has no cursor (repeat the same call), except that a continuation returns its own cursor again; a byte-cap stop returns `deferred_file_ids`, not a cursor. After a finished listing every call MUST handle at least one file unless its first download is rate limited (the first wait is not time-bounded), so a time stop between files always makes progress (a regex too slow for one file can stop at the same place again, FR-033a). A Google 429 on a download after at least one file was handled MUST return `PARTIAL` `RATE_LIMITED` with `next_cursor`; a call whose listing is cut by 429 or time MUST scan nothing (no matches, no deferred ids, so repeating it returns nothing twice): a first call has no cursor, a continuation returns its own cursor. A single-file call reports a 429 on its download as the `RATE_LIMITED` error when fresh, and as `PARTIAL` `RATE_LIMITED` with its own cursor when it is a continuation. Drive's size counts only for blobs: Docs, Sheets and Slides report a storage size that is not their export length, so they sort, defer and are charged as unknown size, and a truncated file is charged the length of the searched prefix.
- **FR-039a**: When `drive_grep` stops at `max_matches`, it MUST return `next_cursor` whenever more matches may remain: `file_id:N` when that file has more matches after its first N, the file id when later files remain. Stopping at exactly `max_matches` with nothing searchable left MUST NOT return a cursor; if nothing else stopped the call it is `COMPLETE` (skipped unsupported files make it `PARTIAL` `unsupported_skipped`, FR-037). N counts matches for the same `pattern`, `case_sensitive` and `regex`, so a continuation MUST repeat them. A continuation slice whose remaining files are all unsupported is `PARTIAL` `unsupported_skipped`, not an error (FR-037). Deferred ids after the cursor are not returned, because the next call revisits them.

#### Result status (cross-cutting)

- **FR-040**: Every retrieval operation MUST report exactly one of `COMPLETE`, `PARTIAL`, `EMPTY`, `ERROR`.
- **FR-041**: `PARTIAL` MUST be returned whenever a resource or result-limit boundary (file count, byte size, execution time, match count, sustained rate-limiting) could plausibly have found more — it MUST NOT be reported as `EMPTY` or `COMPLETE` (Article X).
- **FR-042**: A truncated result MUST never claim completeness by omission.

#### Provenance (cross-cutting)

- **FR-050**: Every content-derived result MUST include, at minimum: `file_id, file_name, mime_type, modified_time, source_url, retrieved_at`. `source_url` MUST be `drive:{file_id}` — a locator, not a fetchable HTTP link — so hosts MUST NOT treat it as a downloadable Cited Source. A result missing `file_id` is invalid (Article VIII). `drive_grep` matches MUST also include `matched_text` and `location`. `drive_read` MUST NOT require match fields.
- **FR-050a**: The final answer MUST cite everything taken from these tools with exactly one line, `Source: onto-kb connector`, and MUST NOT list, number or link separate references (file names, file ids, `drive:` locators, URLs found in the documents, footnotes, bracketed markers or per-quote attributions), with one exception: text quoted word for word from Stack Exchange (CC BY-SA 4.0) MUST carry the link to its post beside the quote. The server instructions and every tool description MUST state this rule. Owner decisions, 2026-10-04 (constitution v2.1.0, Article VIII).
- **FR-051**: Provenance MUST remain intact end-to-end: Drive → search result → agent context. No step MAY drop it. Presentation in the final answer follows FR-050a.

#### Error domain (this context's categories)

- **FR-060**: Retrieval-originated errors MUST be classified by cause using the canonical enum in `specs/001-access-control/contracts/error-taxonomy.md` — at minimum the categories this context produces: `FILE_NOT_FOUND`, `FILE_NOT_EXPORTABLE`, `UNSUPPORTED_MIME_TYPE`, `DRIVE_API_ERROR`, `RATE_LIMITED`, `RESOURCE_LIMIT`, `TEMPORARY_STORAGE_ERROR`, `SEARCH_ERROR`, `INVALID_ARGUMENT` (Article XI). `AUTHENTICATION_ERROR` and `AUTHORIZATION_ERROR` belong to Access Control and are raised upstream. Access Control raises `AUTHORIZATION_ERROR` before this context for a named id it cannot prove is inside `kb`, including one Google does not grant, and `FILE_NOT_FOUND` only when an id already proven inside `kb` then misses; after a call is cleared, this context raises `FILE_NOT_FOUND` only for a resource that is genuinely missing or not visible after that check, via the same `map_google_error()` helper. Walks cut short by rate-limit are `PARTIAL` (FR-041), not `ErrorEnvelope` `RATE_LIMITED`.
- **FR-061**: Errors MUST NOT leak credential material in any form (defense-in-depth; primary guarantee owned by Access Control).

#### Untrusted content (content-handling half)

- **FR-080**: Text retrieved from any document MUST be treated exclusively as data by this context's tools — it MUST NOT alter tool behavior, output shape, or control flow within `drive_ls` / `drive_find` / `drive_read` / `drive_grep` (Article VI). Whether such content could improperly affect *authorization* is Access Control's guarantee (`AC-FR-040`), not this one.

#### Capability surface

- **FR-090**: The exposed surface is read/search/enumerate only: `drive_ls`, `drive_find`, `drive_read`, `drive_grep`. There MUST be no capability (and no code path) to write, delete, share, move, create, or modify permissions (Article V). Drive state after a valid call MUST equal Drive state before.
- **FR-091**: `tools/list` MUST advertise a non-empty description for each tool that states purpose, when to use, when not to use, and at least one positive and one negative call example. Input JSON Schema MUST include per-property descriptions and the same numeric / id-pattern bounds as validation. Descriptions MUST be host-agnostic (FR-102).
- **FR-092**: MCP initialize `instructions` MUST state that the host agent extracts search terms from the user question; the server MUST NOT parse natural language, MUST NOT run semantic search, and MUST NOT synthesize a final answer (Article IV).
- **FR-093**: Every tool MUST be annotated `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` and `openWorldHint: false` (the tools read one private folder, not the open web). The `instructions` MUST tell hosts never to pass tokens as tool arguments and MUST NOT name operator secrets such as `MCP_AUTH_TOKEN`.

#### Ephemerality, agnosticism, budgets

- **FR-100**: Exported or downloaded content MUST be processed as request-scoped working material and MUST NOT become persistent application state (Article III). Any exception MUST be an explicit, documented deviation and would be a MAJOR change (Article XIV).
- **FR-101**: The server MUST behave correctly regardless of which compute instance handles a given request, and MUST tolerate loss of local temporary storage between requests.
- **FR-102**: No tool's meaning or required call pattern MAY depend on a specific LLM vendor's prompting conventions (Article XIII).
- **FR-103**: Logs SHOULD capture `request_id, tool, file count, bytes processed, duration, result count, status, error category`. Each application log entry MUST be one JSON object per line on stdout with a `severity` (the Cloud Logging level), the event name as `message`, and only allow-listed fields, with bearer tokens redacted; a retrieval with status `ERROR` MUST log at `WARNING`. Logs MUST NOT contain full document content, API keys, or emails: the HTTP client library MUST NOT log outbound request URLs (they can carry an API key or a typed email), API keys MUST travel in headers rather than query strings, and the server MUST NOT write its own access log (query strings carry one-time codes; the platform's request log remains). Principal-identifier logging is owned by Access Control.
- **FR-104**: Every operation SHOULD have bounded consumption (`max_files, max_bytes` per file, `max_bytes` per operation, `max_matches, max_execution_time, max_context_lines, max_export_size`) and MUST surface a budget breach as `PARTIAL` with a reason when a usable prefix or partial listing exists. A hard export refusal with no usable prefix MUST be `RESOURCE_LIMIT`. Exact numeric defaults are plan-level.
- **FR-105**: Priority is correctness → retrieval quality → security → simplicity, before latency or cost optimization. No persistent index MAY be introduced for hypothetical performance gains alone (Articles II, XIV).
- **FR-106**: A result at the 20 MB content cap MUST fit the host transport: on the wire it stays near the UTF-8 size of its text (non-ASCII is never re-encoded as `\uXXXX` escapes, which would double CJK text), under Cloud Run's 32 MiB HTTP/1 response cap. Memory per instance MUST stay bounded: downloads stay in memory with no temp-file copy (Cloud Run's `/tmp` is RAM), and at most two downloads larger than about 2 MB or of unknown size (every Docs, Sheets or Slides export) run at once per process. A download that gets no slot within 10 s is `RATE_LIMITED`: the error for `drive_read` and a fresh single-file `drive_grep`, `PARTIAL` `RATE_LIMITED` with `next_cursor` elsewhere in `drive_grep` (FR-038a). A Drive HTTP call that stalls gives up after 20 s, before Cloud Run's 60 s request timeout, and is `DRIVE_API_ERROR`.
- **FR-107**: A `drive_read` result MUST fit Cloud Run's 32 MiB response cap after JSON escaping (content escaped twice on the wire): when the escaped size would pass 30 MiB the content is cut and the result is `PARTIAL` `max_bytes`. In a multi-file `drive_grep`, a file whose download stalls MUST be listed in `deferred_file_ids` and the scan MUST continue.

### Key Entities

- **DriveFile**: Domain fields `id, name, mime_type, parents[], modified_time, created_time, web_view_link, size?, owners?, trashed`. On the wire, `source_url` is `drive:{id}` (never `webViewLink` or an HTTP URL). Drive API camelCase is adapter-only. `web_view_link` is internal only and MUST NOT appear in tool JSON.
- **Folder**: A DriveFile acting as a container; hierarchy is a discovery signal, not a second source of truth.
- **DocumentContent**: Ephemeral, retrieval-time representation of a file's content: `file_id, mime_type, content, retrieved_at, representation`. Never persists beyond the operation (Article III).
- **SearchCandidate**: A DriveFile surfaced as possibly relevant: `file, reason, discovery_method`. `discovery_method` is `find` (`drive_ls` returns children, not candidates). **Not evidence.**
- **SearchMatch**: A deterministic exact match found in retrieved content: `file_id, file_name, pattern, matched_text, location, context`. A SearchMatch with provenance **is** evidence.
- **Evidence** (conceptual role, not a separate wire type or Python class): content returned to the agent to support reasoning. `DocumentContent` from `drive_read` and `SearchMatch` from `drive_grep` play this role when they carry provenance. `SearchCandidate` never does. Agent inference is not evidence.
- **RetrievalScope**: The bounded set of Drive resources an operation may touch. Field `default_whole_grant` is true when the call names no `folder_id` or `file_ids`. Access Control refuses such a scope (`whole_grant_refused`) and never widens it to the whole Google grant. `DRIVE_ALLOWED_FOLDER_ID` is required (`kb` on this deployment), and Access Control rewrites an omitted folder to that id before this context runs (narrow-only, AC-FR-021), so a cleared call always names a folder or files. A named folder or file that is not `kb` or a descendant is `AUTHORIZATION_ERROR`. Enforced by Access Control, which checks every named id against `kb`'s folder tree before this context runs.
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
| I9 | Omitted ls/find/grep use the required `DRIVE_ALLOWED_FOLDER_ID` (`kb`); a named resource not proven inside that folder is `AUTHORIZATION_ERROR`; no listing runs without a folder, and nothing outside `kb` is listed | Articles I, VII |

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
- Persistent document cache, folder cache, or offline mirror
- A local ripgrep store, BM25 index, or any semantic / vector retrieval
- Hiding export folders, or lowering the per-file cap below 20 MB
- Rewriting Drive activity logs whose bodies are import shells; that text lives in Drive
- Full-text indexing independent of live Drive content
- Authentication and authorization (see `specs/001-access-control/spec.md`)
- Architectural decision records, deployment instance lifecycle, and file/module layout (plan.md; Article XII)

## Dependencies

- Upstream: Access Control (`specs/001-access-control/spec.md`) clears every call. Retrieval Core is a conformist consumer.
- Google Drive is the sole persistent source of truth for content and permissions (Article I).
- Future capabilities (for example semantic retrieval) require a demonstrated need the baseline model cannot satisfy and a MAJOR-change specification pass (Articles II, XIV).
