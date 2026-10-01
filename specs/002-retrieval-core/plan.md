# Implementation Plan: Retrieval Core

**Branch**: `main` (spec dir `002-retrieval-core`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-retrieval-core/spec.md`

**Upstream**: Access Control (`specs/001-access-control/`) — this feature never authenticates or authorizes; tools run only after `ALLOW`.

## Summary

Expose four read-only MCP tools — `drive_ls`, `drive_find`, `drive_read`, `drive_grep` — so an agent can iterate `discover → read → exact search` against live Google Drive. No RAG index, no persistent document copy. Candidates are not evidence; `DocumentContent` and `SearchMatch` with provenance play the evidence role (no separate Evidence class). Grep is deterministic over request-scoped bytes. Truncation and walk 429 are `PARTIAL`.

Technical approach: domain operations (discover/inspect/search) behind ports; Google Drive list/export/download, stdlib `re` (literal search) and the `regex` package (`regex=true`, matching with a timeout) are adapters (Article XII). Access Control rewrites an omitted `folder_id` to the required `DRIVE_ALLOWED_FOLDER_ID` (`kb`) before tools run (narrow-only) and refuses `RetrievalScope.default_whole_grant`, so every tool runs on a named folder or named files. No listing runs without a folder, and My Drive `root` is never listed. `find`/`grep` on a folder walk descendants breadth-first with `files.list`; named `file_ids` are checked with the shared `is_within_scope`. Wire `source_url` is `drive:{file_id}` (not `webViewLink`). Mixed-folder grep skips unsupported files (`PARTIAL`); single-id unsupported is a classified error.

Google 404/403-as-404 (and single-file 429 with no prefix) go through Access Control’s `map_google_error()`. Walk 429 is intercepted in list/grep as `PARTIAL` (`partial_reason: RATE_LIMITED`), not `ErrorEnvelope` `RATE_LIMITED`. AUTH folder∩file_ids on real `drive_grep` is replayed after the tool exists (Access Control already tested the same args on the stub).

## Technical Context

**Language/Version**: Python 3.12 (same package as Access Control)

**Primary Dependencies**: `mcp` 2.x; Google Drive v3 via `google-api-python-client` (adapter); stdlib `re` for literal search and the `regex` package for `regex=true` (its matching takes a timeout); `pydantic` for tool I/O

**Storage**: None persistent. Exports live in memory only and are dropped at the end of the tool call (no temp file: Cloud Run's `/tmp` is RAM, so a file would be one more copy).

**Testing**: pytest; contract tests from `contracts/`; integration tests against shared `tests/fakes/fake_drive.py`; AUTH replay on real `drive_grep`; `PARTIAL` including `max_execution_time`; optional live Drive smoke

**Target Platform**: Linux, Cloud Run Streamable HTTP MCP. Same process as Access Control.

**Project Type**: MCP web service (stateless)

**Performance Goals**: Correctness → retrieval quality → security → simplicity, then latency. Default budgets below; a usable prefix or partial listing is `PARTIAL`; a hard export refusal with no prefix is `RESOURCE_LIMIT`; a walk cut by 429 is `PARTIAL` (`partial_reason: RATE_LIMITED`). Never silent.

**Constraints**: Read-only adapter methods only. Google Workspace export is capped at 10 MB by Drive; downloaded text blobs (including `.mdx`) may be read up to 20 MB. No embeddings. Tool names/meanings must not depend on a single LLM vendor. `DRIVE_ALLOWED_FOLDER_ID` is required; the server refuses to start without it, with an alias such as `root` or a value that is not a plain id, or when Drive cannot read it or reports that it is not one folder below a Drive root (a file, a Drive root, or trashed). `scripts/deploy-cloud-run.sh` reads it from the Secret Manager secret `DRIVE_ALLOWED_FOLDER_ID` (never from the operator's shell or the repo) and refuses to deploy when it is missing or malformed. It names the My Drive folder `kb`. Omitted `drive_ls`, `drive_find`, and `drive_grep` use `kb`. A named `folder_id` or `file_id` that is not `kb` or a descendant is `AUTHORIZATION_ERROR`, whether it exists or not. Each tool accepts only the argument keys its body reads.

**Scale/Scope**: One Drive identity; iterative tool calls; tens of files per operation by default, not a corpus index.

### Default resource budgets (plan-level, spec FR-104)

| Budget | Default |
| --- | --- |
| `max_files` | 40 (`drive_ls` page, `drive_find`); `max_results` may lower it (1–40) |
| `max_files` for `drive_grep` | 200 (bytes and time caps still bound each call) |
| `drive_grep` download-ahead | 8 worker threads, at most 16 files and 8 MB ahead, files up to 2 MB with a known size |
| `max_bytes` per file / export | 20_000_000 (`drive_read` `max_bytes` may lower it) |
| `max_bytes` per operation | 20_000_000 |
| `max_matches` | 50 (also the highest value a caller may set) |
| `max_execution_time` | 25 seconds |
| `max_context_lines` | 2 (default `context_lines`; callers may set 0–10) |
| `max_export_size` | 20_000_000 |
| Large downloads (over 2 MB, or unknown size such as any Workspace export) | 2 at once per process; no slot within 10 s → `RATE_LIMITED` |
| Drive HTTP timeout | 20 seconds (Cloud Run request timeout is 60 s) |

Memory and response size (FR-106): a 20 MB result is about 20 MB on the wire. Only a `tools/list` answer is buffered and rewritten (to stamp `securitySchemes`, with `ensure_ascii=False`); every other answer streams through unchanged, so 19.5 MB of CJK text stays near 19.5 MB instead of about 39 MB of `\uXXXX` escapes, under Cloud Run's 32 MiB HTTP/1 response cap. One large read holds a few copies of its text at a time (download, decoded text, UTF-8 length check, JSON answer), roughly 100 MB at the cap; the two-slot bound and Cloud Run's 1 GiB instances with concurrency 10 (`scripts/deploy-cloud-run.sh`) keep an instance inside its memory.

Grep context: line-oriented text (Docs, Markdown, plain text) returns `context_lines` lines on each side of the matching line. Sheets, Slides, CSV and JSON are not line-oriented: up to 200 characters on each side of the hit.

### Listing and grep coverage

`drive_find` sends `name contains`, MIME, `modifiedTime`, and `trashed = false` in `files.list` (`pageSize` 1000). With a filter, the query also keeps subfolders (`mimeType = folder or (...)`) so the walk can descend; a subfolder is returned only if it matches. `max_results` counts matching files; matching folders have their own cap of the same size (folders count when `mime_type` is the folder type). Children of a listed folder are not `files.get`'d to walk parents. Every folder listing (ls, find, grep) drops a child whose returned `parents` do not include the listed folder, so a stale Drive search-index entry cannot surface a file outside it. `drive_ls` lists the whole folder (trashed children excluded) and pages it by `max_results`; `page_token` is the decimal offset from `next_page_token`. The Drive port has no whole-grant listing. Its `list_subfolders` (folders, trashed included, under the given parents; the client puts up to 40 parents in one query) serves Access Control's allow-list tree, not retrieval.

`drive_grep` on a folder sorts known-smaller files first. The 20 MB per-file cap stays, including for one named `file_id`. A known size that does not fit the remaining operation bytes is returned in `deferred_file_ids` and not downloaded. A call scans up to 200 files, downloading small files ahead on worker threads while matches are still taken in size order (FR-038a). After a `max_matches` stop the cursor is the file id, or `file_id:N` inside a file with more matches (FR-039a); `file_ids` calls take the same cursor. Results always include `files_scanned` and `bytes_scanned`. In line-oriented text a match is one line: repeat hits on that line raise `location.occurrences` instead of spending another `max_matches` slot (FR-039). `next_cursor` is set when the listing finished and more remains, or on a continuation whose listing was cut (the incoming cursor, unchanged) (FR-038a, FR-039a). A cut listing scans nothing. A byte-cap stop returns `deferred_file_ids`, not a cursor. After a finished listing the first file of a call is not time-bounded, so a time stop between files always makes progress. The same value is an input property named `next_cursor` (`cursor` is an alias). A `regex=true` search runs on the `regex` package with the call's remaining time (at least 0.5 s per file) as its timeout; running out stops the scan as `PARTIAL` `max_execution_time` with the matches finished and a cursor in that file. Patterns are capped at 512 characters, and a regex is accepted only in stdlib `re` syntax with counted repeats that unroll to at most 10,000 items, since the `regex` package writes out minimum repeats when it compiles (FR-033a). There is no persistent folder cache, ripgrep store, or BM25 index. This deployment’s omitted ls/find/grep uses `kb` via `DRIVE_ALLOWED_FOLDER_ID`.

### `content_format` (plan-level, spec FR-022)

Omitted → default MIME from the research export map (Docs/Slides `text/plain`, Sheets `text/csv`, text blobs as stored). If set, it MUST be a MIME that type can produce. Docs, Sheets and Slides accept only their default. Unknown or type-incompatible value, or any value on a type that cannot yield text → `INVALID_ARGUMENT`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Fitness line (Art. XV) | Gate |
| --- | --- |
| Drive is authoritative | PASS — read/export at call time; no MCP-owned replica |
| the server is read-only | PASS — four tools only; no write code paths |
| document content is untrusted | PASS — content cannot change tool control flow |
| retrieval can iterate | PASS — tools are primitives; agent owns the loop |
| exact search is deterministic | PASS — stdlib `re` (literal) or the `regex` package (regex, timed) over retrieved bytes in-request; a regex time stop is a visible `PARTIAL` |
| evidence carries provenance | PASS — `file_id` required on content-derived results |
| partiality is visible | PASS — `COMPLETE`/`PARTIAL`/`EMPTY`/`ERROR` |
| compute is ephemeral | PASS — discard exports after the operation |
| no hidden persistent state exists | PASS — no index, no cache |
| authorization is independently enforced | PASS — conformist; chain is upstream |
| agent reasoning and retrieval mechanics stay separate | PASS — no sufficiency/synthesis |
| no RAG index is required for correctness | PASS |

**Post-Phase 1 re-check:** Still PASS. Contracts are read/search/enumerate. Budgets and walk 429 emit `PARTIAL`. `map_google_error` is not used for walk 429. Export map is infrastructure, not a second source of truth. Evidence is a role, not a type.

## Project Structure

### Documentation (this feature)

```text
specs/002-retrieval-core/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/           # includes error-taxonomy.md pointer to Access Control
└── tasks.md
```

### Source Code (repository root)

```text
src/google_drive_mcp/
├── domain/
│   ├── errors.py
│   ├── google_errors.py     # shared mapper: 404/403-as-404; single-file 429; not walk 429
│   ├── budgets.py
│   ├── drive_file.py
│   ├── list_filter.py       # files.list predicates for drive_find
│   ├── provenance.py
│   ├── retrieval_scope.py   # is_within_scope (walks); folder_tree / is_inside_tree (Access Control allow-list); from Access Control T005
│   ├── candidates.py
│   ├── content.py
│   ├── matches.py
│   └── operation.py
├── retrieval/
│   ├── ports.py
│   ├── ls.py
│   ├── find.py
│   ├── read.py
│   └── grep.py
├── infra/
│   ├── google_drive/
│   │   ├── client.py        # Drive v3 get / list / export / get_media; one connection per thread
│   │   ├── list.py          # files.list / get metadata; uses is_within_scope
│   │   ├── query.py         # files.list q text and page size
│   │   └── export.py        # files.export / get_media
│   └── exact_search/
│       └── regex.py         # stdlib re for literals; regex package with a timeout for regex=true
├── mcp/
│   ├── server.py            # composition root (Access Control); input schemas; mounts tools.py
│   ├── tool_schema.py       # initialize instructions, tool descriptions
│   ├── validation.py        # id pattern and numeric bounds shared by schemas and checks
│   └── tools.py             # drive_ls, drive_find, drive_read, drive_grep
tests/
├── fakes/
│   └── fake_drive.py        # same port as Access Control; populate store here
├── contract/
├── integration/
└── unit/
    └── retrieval/
```

**Structure Decision**: Same single package as Access Control. Retrieval owns `retrieval/`, Drive content adapters, exact-search adapter, and MCP tool registration. Access-control middleware wraps every tool. `mcp/server.py` remains the composition root (do not start a second server). One fake Drive: `tests/fakes/fake_drive.py`. Do not fork `RetrievalScope` or add a descendant check outside `domain/retrieval_scope.py`. T040 scans `infra/google_drive` for write methods.

## Complexity Tracking

> No constitution violations requiring justification.
