# Research: Retrieval Core

## Decision: Hexagonal ports — Drive and regex are adapters

**Rationale**: Article XII. Domain operations speak `DriveFile`, `DocumentContent`, `SearchMatch`. `googleapiclient.discovery.build("drive", "v3")` and `re.compile` live behind ports so export path or regex engine can change without changing tool meaning.

**Alternatives considered**: Calling Drive types from tool handlers (couples domain to API). ripgrep subprocess (extra binary on Cloud Run; harder to bound).

## Decision: Workspace export map (usable text)

**Rationale**: Clarify A. Drive `files.export` (Workspace) vs `files.get_media` (binary/text blobs). Default representations:

| Drive MIME | Method | Export/download MIME |
| --- | --- | --- |
| `application/vnd.google-apps.document` | export | `text/plain` |
| `application/vnd.google-apps.spreadsheet` | export | `text/csv` |
| `application/vnd.google-apps.presentation` | export | `text/plain` |
| `text/*`, `application/json`, `application/csv`, markdown | download | as stored |
| `application/octet-stream` (or empty MIME) whose filename has a known text extension (`.md`, `.mdx`, `.txt`, `.json`, `.csv`, `.yml`, `.yaml`, `.rst`) | download | mapped text MIME (e.g. `.mdx` → `text/markdown`) |
| other | fail | `UNSUPPORTED_MIME_TYPE` / `FILE_NOT_EXPORTABLE` |

Omitted `content_format` uses this table. A caller-supplied `content_format` MUST be a MIME that type can produce; unknown or incompatible → `INVALID_ARGUMENT`.

Google Workspace export is capped at 10 MB by Drive. Downloaded text blobs use `max_export_size` and per-file `max_bytes` of 20_000_000, equal to the per-operation byte budget, so one file at that size is a complete read and a second large file in the same call is `PARTIAL` (`partial_reason: max_bytes`). A usable prefix within the cap is `PARTIAL`. A hard refusal with **no** prefix is `RESOURCE_LIMIT`. PDF is not required in v1 (not reliably “usable text” without extra libraries); treat as unsupported unless a later MINOR adds a text extractor.

Wire field `source_url` is the locator `drive:{file_id}`, not Drive `webViewLink`. HTTP view links MUST NOT appear in tool JSON (hosts offer them as downloadable Cited Sources).

**Alternatives considered**: Docs API / Sheets API structural reads (more faithful layout, more APIs — rejected for v1; Drive export is enough for exact search). Always markdown for Docs (fine later via `content_format`).

## Decision: `files.list` with `q` for find; recursive folder as `'{id}' in parents` walk or `fullText` not used for exact grep

**Rationale**: `drive_find` is metadata/native discovery (name, mime, dates, trashed, folder). Recursion: walk descendants with list queries (or paginated `'{folderId}' in parents` BFS) until `max_files` then `PARTIAL`. Do **not** use Drive `fullText` as `drive_grep` — grep is local exact match on retrieved bytes (Art. IX).

**Alternatives considered**: Drive `fullText` contains for grep (not deterministic over “already retrieved bytes”, not request-scoped local computation). Single recursive `q` with all descendants via Drive search `parents` — Drive does not list all descendants in one metadata query reliably; BFS walk is explicit and can report `PARTIAL`.

## Decision: Default scope = whole grant; ls root = My Drive root (`root`)

**Superseded (2026-09-29)**: there is no whole-grant scope, and `drive_ls` never lists My Drive `root`. See “Fail closed; nothing outside kb is listed” below. The text in this section is the original v1 rule.

**Rationale**: Clarify A. Omitted `folder_id` on `drive_ls` lists immediate children of My Drive `root` — a **projection** of `default_whole_grant`, not a second source of truth. Omitted folder/file list on find/grep searches the whole grant subject to budgets (`PARTIAL` likely on large drives — required by Art. X). Shared-with-me and other corpora MAY appear in find/grep and MUST NOT be assumed present in omitted-folder `ls`.

Descendant checks use domain `is_within_scope` (same helper as Access Control). Do not implement a second parent walk in `list.py`.

**Alternatives considered**: Require folder always (rejected in clarify). Shared-with-me as a second ls root — rejected; do not special-case a second source of truth. Treating omitted-folder ls and find as the same universe (false; would hide the projection).

## Decision: This deployment allows only the kb folder (2026-09-28)

**Rationale**: A whole-grant grep sorted smallest-first spent `max_files` on tiny files outside `kb` and never reached that folder. A later default (`DRIVE_DEFAULT_FOLDER_ID`) pointed omitted find/grep at `kb` and still left every other granted folder reachable, including My Drive root via omitted `drive_ls`. This deployment sets `DRIVE_ALLOWED_FOLDER_ID` to the My Drive folder named `kb`; `DRIVE_DEFAULT_FOLDER_ID` was later removed (T064). Omitted `drive_ls`, `drive_find`, and `drive_grep` run in `kb`. A named `folder_id` or `file_id` outside `kb` is `AUTHORIZATION_ERROR` (`outside_allowed_folder`). Descendants of `kb` stay readable. The grep input property `next_cursor` (alias `cursor`) accepts the previous result field of the same name.

**Alternatives considered**: Keep `DRIVE_DEFAULT_FOLDER_ID` as a non-deny default (rejected: other top-level folders stayed reachable). A persistent folder cache or BM25 index (rejected: Article III and Article XIV).

## Decision: Fail closed; nothing outside kb is listed (2026-09-29)

**Rationale**: The owner requires that only `kb` and its descendants are readable, and that nothing outside `kb` can even be listed (no names, ids, or metadata). An optional allow-list, a default folder, and omitted `drive_ls` on My Drive `root` each left a path open. `DRIVE_ALLOWED_FOLDER_ID` is now required: the server does not start when it is unset, blank, an alias such as `root` or `appDataFolder`, or not a plain id, and the chain refuses every call without it. `DRIVE_DEFAULT_FOLDER_ID` and `apply_default_search_folder` are deleted. A call that names no folder or file after the rewrite is refused. `list_all` is gone, `walk_files` never lists the whole grant, and `drive_ls` without a folder is `AUTHORIZATION_ERROR`. The allow-list check runs first for every named id, so an id outside `kb`, a missing id, and an ungranted id get the same `AUTHORIZATION_ERROR`. Each tool accepts only the argument keys its body reads, so a key the body would ignore cannot pass the chain. Folder listings drop a child whose `parents` do not include the listed folder, because `files.list` is answered from Drive’s search index; that is one membership check on data the listing already returned, not a second parent walk. Deploy pins the `kb` folder id, routes all traffic to the newest revision, checks it carries the allow-list, and deletes older revisions without it, because a rollback to one of them would serve the whole Drive.

**Alternatives considered**: Keep the allow-list optional (rejected: one missing env var re-opened the whole Drive). Trust `files.list` children without checking `parents` (rejected: a stale index entry could list a file outside the folder). Leave old Cloud Run revisions in place for rollback (rejected: they carry no allow-list).

## Decision: Stdlib `re` with explicit literal vs regex modes

**Rationale**: Literal mode uses `re.escape(pattern)`. Regex mode compiles the pattern and fails `INVALID_ARGUMENT` on bad regex. `case_sensitive=false` adds `re.IGNORECASE`. Same bytes + same flags → same matches (Art. IX).

**Alternatives considered**: Python `str.find` only (no regex FR-033). Third-party engines (unnecessary).

## Decision: Result status enum on every tool result

**Rationale**: FR-040 / Article X. `EMPTY` is a successful scan with zero hits/children. `PARTIAL` if any budget, mixed unsupported skips, or sustained rate-limit cut a **walk** short.

Rate-limit split (locked):

- Walk (ls/find/grep) cut by Google 429, even with zero items: `status: PARTIAL`, `partial_reason: RATE_LIMITED`. Never `EMPTY`/`COMPLETE`. Never `ErrorEnvelope.category = RATE_LIMITED`.
- Single-file read/export 429 with no prefix: `ErrorEnvelope` `RATE_LIMITED`.

Prefix vs hard cap: usable prefix → `PARTIAL`; no prefix → `RESOURCE_LIMIT`.

Google 404 after `ALLOW` uses Access Control’s `map_google_error()` — do not fork a second mapper. Walk 429 is intercepted in list/grep (T036) **before** the mapper; only single-file 429 with no prefix goes through `map_google_error` as `RATE_LIMITED`.

**Alternatives considered**: HTTP 429 only (agent cannot tell coverage). Silent retry until timeout (Art. X forbid). Always `ERROR`/`RATE_LIMITED` for walks (collapses “not fully searched” into failure and invites EMPTY-shaped handling).

## Decision: No document cache, including in-memory across tools

**Rationale**: Art. III / I. `drive_read` then `drive_grep` on the same id in a later MCP call must re-fetch. Within a **single** `drive_grep` invocation, bytes are fetched, searched, discarded — that is request-scoped, not a cache.

**Alternatives considered**: LRU of exports (MAJOR, needs freshness model).
