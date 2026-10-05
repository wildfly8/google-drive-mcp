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
| `application/octet-stream`, `application/x-octet-stream`, `binary/octet-stream` (or empty MIME) whose filename has a known text extension (`.md`, `.mdx`, `.txt`, `.text`, `.rst`, `.json`, `.csv`, `.yml`, `.yaml`) | download | mapped text MIME (e.g. `.mdx` → `text/markdown`) |
| other, including folders | fail | `UNSUPPORTED_MIME_TYPE` / `FILE_NOT_EXPORTABLE` |

Omitted `content_format` uses this table. A caller-supplied `content_format` MUST be a MIME that type can produce; unknown or incompatible → `INVALID_ARGUMENT`. Docs, Sheets and Slides accept only their default.

Google Workspace export is capped at 10 MB by Drive. Downloaded text blobs use `max_export_size` and per-file `max_bytes` of 20_000_000, equal to the per-operation byte budget, so one file at that size is a complete read and a second large file in the same call is `PARTIAL` (`partial_reason: max_bytes`). A usable prefix within the cap is `PARTIAL`. A hard refusal with **no** prefix is `RESOURCE_LIMIT`. PDF is not required in v1 (not reliably “usable text” without extra libraries); treat as unsupported unless a later MINOR adds a text extractor.

**Citation in answers (2026-10-04)**: the owner chose one citation line per answer, `Source: onto-kb connector`, with no separate references. Tool results keep full provenance so the agent can verify and chain calls; only the presentation in the final answer collapses to that line (constitution v2.0.0, Article VIII; FR-050a). Alternative rejected by the owner: listing each file or Stack Exchange link as a reference.

**Where the citation rule sits (2026-10-05)**: after the rule shipped, a connected AI app still ended an answer with `Sources from your corpus: file.md (drive:…)`. The rule was the last paragraph of each tool description (at 79–96% of the text; character 4,432 of `drive_grep`'s 4,637) and in the middle of the instructions. Claude Code showed `drive_grep`'s description cut at 4,096 characters, which removed both the rule and the result format — from the tool whose results carry the file names and `drive:` locators. What the owner's app does with the text cannot be seen from here. Fix: the rule is the second paragraph of every description and the first section of the instructions, `drive_grep`'s description is 3,980 characters, and a test keeps both properties (T085). Results still carry `file_name` and `source_url` (FR-050, FR-051), so a host that never receives the rule, or follows the user's own request for sources instead, can still list them: the server advises, it cannot enforce. Alternatives not taken: dropping `source_url` from results (breaks FR-050 and FR-051 and the agent's own tracking), and telling the host how to cite inside tool results (hosts treat instructions in tool results as untrusted).

**Stack Exchange quotes keep their link (2026-10-04)**: the kb's Stack Exchange files carry other users' question titles and short quotes of their comments, licensed CC BY-SA 4.0, which requires attribution. A one-line connector citation would strip it, so an answer that quotes Stack Exchange text word for word puts the post's link beside the quote (constitution v2.1.0). Paraphrase and every other source still cite the connector once.

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

## Decision: Same Drive calls for every named id; kb id kept out of the repo (2026-09-29, 2026-10-01)

**Rationale**: The check above gave an id outside `kb`, a missing id and an ungranted id the same reply, but it climbed each id's parents, so the number of Drive calls, and the time, depended on the id. Access Control now lists `kb`'s folder tree top down (`folder_tree`, through the Drive port's `list_subfolders`), makes one metadata get per named id, and decides membership in memory (`is_inside_tree`). The three cases take the same Drive calls, and no lookup climbs into folders outside `kb`. At startup the server reads the allow-list folder from Drive and refuses an id Drive cannot read, a file, a Drive root (by alias or by real id), or a trashed folder. Deploy checks that the newest revision carries the allow-list, routes all traffic to the latest revision, clears traffic tags, and deletes every other revision; a rollback is a redeploy of an older commit. Since 2026-10-01 the `kb` folder id lives in the Secret Manager secret `DRIVE_ALLOWED_FOLDER_ID`. The deploy script reads it from there (never from the operator's shell), refuses a missing or malformed value, and does not print it. The repo, `.env.example` and tests hold placeholder ids only.

**Alternatives considered**: Keep climbing parents per named id (rejected: the call count depended on the id). Keep the folder id in the deploy script (rejected: the repo is public).

## Decision: Stdlib `re` with explicit literal vs regex modes

**Rationale**: Literal mode uses `re.escape(pattern)`. Regex mode compiles the pattern and fails `INVALID_ARGUMENT` on bad regex. `case_sensitive=false` adds `re.IGNORECASE`. Same bytes + same flags → same matches (Art. IX).

**Alternatives considered**: Python `str.find` only (no regex FR-033). Third-party engines (unnecessary).

## Decision: Result status enum on every tool result

**Rationale**: FR-040 / Article X. `EMPTY` is a successful scan with zero hits/children. `PARTIAL` if any budget, mixed unsupported skips, or sustained rate-limit cut a **walk** short.

Rate-limit split (locked):

- Walk (ls/find/grep) cut by Google 429, even with zero items: `status: PARTIAL`, `partial_reason: RATE_LIMITED`. Never `EMPTY`/`COMPLETE`. Never `ErrorEnvelope.category = RATE_LIMITED`.
- Single-file read/export 429 with no prefix: `ErrorEnvelope` `RATE_LIMITED`. A `drive_grep` continuation on a single file is the exception: it returns `PARTIAL` `RATE_LIMITED` with its own cursor so its place is kept (FR-038a).

Prefix vs hard cap: usable prefix → `PARTIAL`; no prefix → `RESOURCE_LIMIT`.

Google 404 after `ALLOW` uses Access Control’s `map_google_error()` — do not fork a second mapper. Walk 429 is intercepted in list/grep (T036) **before** the mapper; only single-file 429 with no prefix goes through `map_google_error` as `RATE_LIMITED`.

**Alternatives considered**: HTTP 429 only (agent cannot tell coverage). Silent retry until timeout (Art. X forbid). Always `ERROR`/`RATE_LIMITED` for walks (collapses “not fully searched” into failure and invites EMPTY-shaped handling).

## Decision: No document cache, including in-memory across tools

**Rationale**: Art. III / I. `drive_read` then `drive_grep` on the same id in a later MCP call must re-fetch. Within a **single** `drive_grep` invocation, bytes are fetched, searched, discarded — that is request-scoped, not a cache.

**Alternatives considered**: LRU of exports (MAJOR, needs freshness model).

## Decision: Stay read-only; temporary write tools removed (2026-09-30)

**Rationale**: For a short time `drive_write`, `drive_trash` and `drive_replace` existed behind `DRIVE_WRITE_ENABLED`, with their own Drive writer and a credential with the full `drive` scope. They broke FR-090 and Article V, so they were removed the same day. The server again registers only `drive_ls`, `drive_find`, `drive_read` and `drive_grep`, `DRIVE_WRITE_ENABLED` is no longer read, and the separate writer and its `drive`-scope credential are gone.

**Alternatives considered**: Keep the write tools behind the flag (rejected: FR-090 allows no write code path, flag or not).

## Decision: One grep match per line; 200 files per grep call (2026-09-30)

**Rationale**: In line-oriented text the context already holds the whole line, so a second hit on the same line spent another `max_matches` slot on text the caller had. A match is now one (file, line): `matched_text` and `location.offset` are the first hit and `location.occurrences` counts every hit on it. Sheets, Slides, CSV and JSON have no lines and keep one match per hit, with up to 200 characters of context on each side. A folder grep scans up to 200 files per call instead of 40, so a whole-`kb` sweep takes fewer calls; the 20 MB and 25 s caps still bound each call. `drive_ls` and `drive_find` keep 40.

**Alternatives considered**: Keep one match per hit (rejected: repeat hits spent slots on a line already shown). Keep 40 files per grep call (rejected: a whole-`kb` sweep took many more calls).

## Decision: Download small files ahead in `drive_grep`; resumable cursor after `max_matches` (2026-09-30)

**Rationale**: A live whole-`kb` grep stopped on the 25 s time cap after 42–68 small files (about 0.5 s per `get_media`), long before the 200-file or 20 MB caps. The cost is per-request latency, not bytes, so downloads overlap: up to 8 worker threads fetch the next small files (known size up to 2 MB, at most 16 files and 8 MB ahead, never more than the operation's remaining bytes) while the scan still takes files one at a time in size order. Results therefore match a sequential scan exactly (FR-031), a deferred file is never downloaded, and memory stays near a one-file scan on the 512 MiB instance. Each thread uses its own authorized `httplib2` connection because `httplib2.Http` is not thread-safe. A wait on a download fetched ahead is bounded by the time left once the call has handled a file (after a finished listing the first wait is not, so every call that is not rate limited makes progress and a cursor chain cannot loop on the time cap), so one slow small file ends the call with a cursor instead of running past the cap; larger files are still fetched on the request thread as before. The operation is charged a blob's Drive size, which is also what the download-ahead plans with (Docs, Sheets and Slides report a storage size unrelated to their export, so they count as unknown size), so invalid UTF-8 that grows when decoded cannot make a fetched file look too big later. Skipped matches behind a `file_id:N` cursor are counted, not built, so a deep cursor costs time, not memory. Look-ahead is sized by the `max_matches` room left and the hits per file seen so far, because files fetched ahead past a `max_matches` stop are thrown away and fetched again by the next call (a `max_matches=1` chain over 60 one-hit files went from about 520 downloads to about 60 with this bound). Separately, a folder grep that stopped on `max_matches` had no cursor, so later hits were unreachable, and a single file with more than 50 matching lines could not be finished. The cursor now also encodes a position inside a file (`file_id:N`, skip the first N matches; deterministic for identical bytes) and is accepted with `file_ids`. A one-match look-ahead tells whether anything remains, so an exact fill with nothing left is `COMPLETE`.

**Alternatives considered**: Raise the per-operation byte cap (rejected: bytes were not the limit, and larger files in memory risk the 512 MiB instance). Prefetch every file regardless of size (rejected: several 12–19 MB exports at once could exhaust memory). Process results as downloads finish (rejected: match order would depend on timing, breaking FR-031). A cursor that re-scans the stopped file from its start (rejected: returns the same matches twice).

## Decision: A folder's own files first; kb's examined essays lead (2026-10-04)

**Rationale**: The owner moved the 27 examined essays (current theses) to `kb`'s root and the archives (about 440 files of ~100 KB) into subfolders, and asked that the essays be searched and loaded first. Size-only grep order interleaved essays with indexes and small archive files, and the breadth-first find walk reached `chatgpt/` before the essays when they sat two levels deep. Grep now sorts by depth, then size; listed children are files first, then by name. Drive's `files.list` order is unspecified, so the sort also keeps `drive_ls` offset paging stable. The rule names no folder, so it holds for any layout.

**Alternatives considered**: A priority folder setting by name or id (rejected: deployment-specific configuration for what layout already expresses). Size-only order with the essays kept the smallest files (rejected: fragile; one long essay or a short index breaks it).
