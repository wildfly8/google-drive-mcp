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
| other | fail | `UNSUPPORTED_MIME_TYPE` / `FILE_NOT_EXPORTABLE` |

Google export is capped at 10 MB; we fail at 5 MB (`max_export_size`) as `PARTIAL` or `RESOURCE_LIMIT`. PDF is not required in v1 (not reliably “usable text” without extra libraries); treat as unsupported unless a later MINOR adds a text extractor.

**Alternatives considered**: Docs API / Sheets API structural reads (more faithful layout, more APIs — rejected for v1; Drive export is enough for exact search). Always markdown for Docs (fine later via `content_format`).

## Decision: `files.list` with `q` for find; recursive folder as `'{id}' in parents` walk or `fullText` not used for exact grep

**Rationale**: `drive_find` is metadata/native discovery (name, mime, dates, trashed, folder). Recursion: walk descendants with list queries (or paginated `'{folderId}' in parents` BFS) until `max_files` then `PARTIAL`. Do **not** use Drive `fullText` as `drive_grep` — grep is local exact match on retrieved bytes (Art. IX).

**Alternatives considered**: Drive `fullText` contains for grep (not deterministic over “already retrieved bytes”, not request-scoped local computation). Single recursive `q` with all descendants via Drive search `parents` — Drive does not list all descendants in one metadata query reliably; BFS walk is explicit and can report `PARTIAL`.

## Decision: Default scope = whole grant; ls root = My Drive root (`root`)

**Rationale**: Clarify A. Omitted `folder_id` on `drive_ls` lists immediate children of `root`. Omitted folder/file list on find/grep searches the grant subject to budgets (`PARTIAL` likely on large drives — required by Art. X).

**Alternatives considered**: Require folder always (rejected in clarify). Shared-with-me as a second root — include only if `files.list` corpora default already returns them under the grant; do not special-case a second source of truth.

## Decision: Stdlib `re` with explicit literal vs regex modes

**Rationale**: Literal mode uses `re.escape(pattern)`. Regex mode compiles the pattern and fails `INVALID_ARGUMENT` on bad regex. `case_sensitive=false` adds `re.IGNORECASE`. Same bytes + same flags → same matches (Art. IX).

**Alternatives considered**: Python `str.find` only (no regex FR-033). Third-party engines (unnecessary).

## Decision: Result status enum on every tool result

**Rationale**: FR-040. `EMPTY` is a successful scan with zero hits/children. `PARTIAL` if any budget or sustained rate-limit cut work short (map Google 403 rate limit that stops a walk to `PARTIAL` + `RATE_LIMITED` category when the operation errors vs partial results — if some results exist and more were possible, `PARTIAL`; if none and rate-limited to a stop, `ERROR`/`RATE_LIMITED` or `PARTIAL` with empty list **and** explicit incomplete flag — spec says rate-limit that cuts search short is completeness, so prefer `PARTIAL` with `reason=RATE_LIMITED` rather than swallowing retries).

**Alternatives considered**: HTTP 429 only (agent cannot tell coverage). Silent retry until timeout (Art. X forbid).

## Decision: No document cache, including in-memory across tools

**Rationale**: Art. III / I. `drive_read` then `drive_grep` on the same id in a later MCP call must re-fetch. Within a **single** `drive_grep` invocation, bytes are fetched, searched, discarded — that is request-scoped, not a cache.

**Alternatives considered**: LRU of exports (MAJOR, needs freshness model).
