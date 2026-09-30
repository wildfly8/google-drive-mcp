"""MCP initialize instructions and per-tool descriptions advertised on tools/list.

Host-agnostic (FR-102 / Article XIII): no vendor-specific prompting. The host
model extracts keywords; this server does not parse natural language.
"""

from __future__ import annotations

from mcp_types import ToolAnnotations

from google_drive_mcp import __version__

SERVER_NAME = "onto-kb"
SERVER_TITLE = "onto-kb"
SERVER_VERSION = __version__
SERVER_DESCRIPTION = (
    "Read-only MCP tools to list, find, read, and exact-search live Google Drive "
    "files. The host agent chooses tools and search terms. This server does not "
    "parse natural-language questions, run semantic/RAG search, or synthesize answers."
)

SERVER_INSTRUCTIONS = """\
Read-only Google Drive retrieval. You (the host agent) turn the user's question
into structured tool calls. This server never extracts keywords and never writes
the final answer.

Authentication is MCP OAuth 2.1 (authorization code + PKCE). Hosts may call
`initialize` and `tools/list` without a Bearer so they can advertise tools.
Every `drive_*` call requires `Authorization: Bearer <access_token>` issued by
this origin. Never pass tokens, OAuth codes, or Google credentials as tool
arguments. `MCP_AUTH_TOKEN` is the resource-owner consent password, not an API
bearer.

Loop (repeat with different terms if needed):
1. drive_ls or drive_find → file ids (candidates, not evidence)
2. drive_grep with a short exact phrase taken from the question, preferably on file_ids
3. drive_read for the full text of one file_id
4. If status is PARTIAL, continue; do not treat the result as exhaustive.
   drive_grep may include next_cursor and deferred_file_ids.
   - next_cursor: call drive_grep again with that exact value in the next_cursor argument (cursor is an alias). Same pattern, case_sensitive and regex. Same folder_id (or omit it again), or the same file_ids. The value is a file id, or file_id:N to continue inside that file after a max_matches stop.
   - deferred_file_ids: those files were not downloaded. Call drive_grep once per id (a single file_id is never deferred; each call still stops at 20 MB).
5. If status is EMPTY, that slice finished with zero hits — change the phrase or scope. Do not invent hits. Do not treat EMPTY as covering deferred_file_ids; a deferral is PARTIAL.

Hard rules:
- Do not pass the full user question as name_pattern or pattern.
- drive_find name_pattern is a case-insensitive substring of the *filename*, not glob, not contents.
- drive_grep pattern matches exported file *bytes* (literal, or regex if regex=true). Not Drive fullText.
- drive_ls is immediate children only; drive_find / drive_grep on a folder include descendants.
- The only folder this server may read is kb and its descendants. Omit folder_id to list or search kb. A folder_id or file_id outside kb, or one that does not exist, is AUTHORIZATION_ERROR; nothing outside kb is listed or read. Do not request My Drive root or any other top-level folder.
- One drive_grep or drive_read returns at most 20 MB. A file at or under that size is complete when you pass that one file_id. A folder grep scans smaller files first. A known size that does not fit the remaining bytes is listed in deferred_file_ids and is not downloaded.
- Candidates from drive_find are not quotes. Evidence is drive_read content or drive_grep matches with provenance.
- source_url is the locator drive:{file_id}, not an HTTP URL. Do not present it as a download or Cited Source link.
- No write/delete/share tools exist. Do not ask for them.
"""

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

DRIVE_LS_TITLE = "List immediate folder children"
DRIVE_LS_DESCRIPTION = """\
List the immediate children of one Drive folder. Metadata only — no file bodies.

When to use:
- Orient: what folders/files sit directly under kb, or under a folder_id inside kb.
- Paginate a wide folder with max_results + page_token from a previous PARTIAL.

When not to use:
- You need nested descendants (use drive_find).
- You need text inside files (use drive_grep or drive_read).
- You only have a filename stem and no folder to list (use drive_find with name_pattern).

Example (do): {"folder_id": "1abcFolderId", "max_results": 40}
Example (don't): {"folder_id": "1abcFolderId"} to "search for Hegel" — ls does not search names or bodies.

Returns: status (COMPLETE | PARTIAL | EMPTY), children[{id,name,mime_type,is_folder,modified_time,source_url}], optional next_page_token / partial_reason. source_url is drive:{id} (not http). Never includes content.
"""

DRIVE_FIND_TITLE = "Find files by name or type"
DRIVE_FIND_DESCRIPTION = """\
Recursive metadata discovery. Returns SearchCandidate records (file + reason). Not evidence.

When to use:
- Locate files whose *filename* contains a short stem (name_pattern is a case-insensitive substring).
- Filter by mime_type, modified_after / modified_before (ISO-8601), or trashed.
- Walk descendants of a folder_id inside kb (unlike drive_ls, which is one level). Omit folder_id to search kb. A folder outside kb is AUTHORIZATION_ERROR.

When not to use:
- Searching file *contents* (use drive_grep).
- Reading a file you already have an id for (use drive_read).
- Treating hits as verified quotes — candidates have no matched_text.

name_pattern is NOT a glob: "activity" matches activity-2025.mdx; "*activity*" looks for a literal asterisk and usually misses. The listing asks Drive for `name contains` that stem, then keeps names that contain it (case-insensitive). max_results counts matching files only.

Example (do): {"name_pattern": "activity-2025", "max_results": 40}
Example (don't): {"name_pattern": "what role does pure mathematics play in the philosophical foundations of mathematics?"} — that is a question, not a filename.

Returns: status, candidates[{file, reason, discovery_method}]. file has id/name/mime/modified_time/source_url (drive:{id}, not http), never content. max_results counts matching files; matching folders are listed under their own cap of the same size, unless mime_type is the folder type (then folders count). Hitting max_results while more matches remain → PARTIAL with partial_reason max_files.
"""

DRIVE_READ_TITLE = "Read current file text"
DRIVE_READ_DESCRIPTION = """\
Export live text for one file_id from Drive at call time. Evidence with provenance.

When to use:
- You already have a file_id from ls/find/grep and need the body (or more than grep context).
- Re-read after Drive changed; there is no MCP cache.

When not to use:
- You do not have a file_id (discover first).
- You only need whether a short phrase occurs (drive_grep is cheaper across many files).
- The target is a folder_id (folders are not readable as documents).

Example (do): {"file_id": "1abcFileId"}
Example (don't): {"file_id": "activity-2025.mdx"} — names are not ids. Example (don't): pass a user question; this tool does not search.

Optional content_format: omit for the default export (Docs/Slides text/plain, Sheets csv, text blobs as stored). Unknown or incompatible format → INVALID_ARGUMENT.
Optional max_bytes: 1..20000000; truncation → PARTIAL (prefix returned).

Returns: status, file_id, file_name, mime_type, modified_time, source_url (drive:{file_id}, not http), retrieved_at, content, optional representation / partial_reason. Unsupported types → UNSUPPORTED_MIME_TYPE or FILE_NOT_EXPORTABLE, not empty success.
"""

DRIVE_GREP_TITLE = "Exact-search file contents"
DRIVE_GREP_DESCRIPTION = """\
Deterministic exact match over bytes exported in this call. Not Drive fullText, not embeddings, not keyword-ranking.

When to use:
- Verify a claim with a short distinctive phrase, identifier, title, or term of art taken from the user question.
- Search known file_ids inside kb (preferred) or all descendants of a folder_id inside kb. Omit folder_id to search kb. A folder or file outside kb is AUTHORIZATION_ERROR. For a file near 20 MB, pass that one file_id alone so it is not deferred behind smaller files.
- Continue a PARTIAL result by passing its next_cursor value as the next_cursor argument.
- Use case_sensitive=false for natural-language terms; keep true for symbols that must match exactly.
- Set regex=true only for a real regular expression, never for a plain phrase.

When not to use:
- Finding files by filename (use drive_find).
- Listing a folder (use drive_ls).
- Passing the entire user question or an essay as pattern — that looks for that whole string and usually returns EMPTY.
- Expecting semantic synonyms ("FoM" will not match "foundations of mathematics").

Example (do): {"pattern": "Vicious Circle Principle", "file_ids": ["1abcFileId"], "case_sensitive": false, "context_lines": 3, "max_matches": 20}
Example (don't): {"pattern": "Assuming I understand the function of Foundations of Mathematics, what role does pure mathematics play..."} — not an exact phrase in any file.

If both folder_id and file_ids are set, every named id must be in that folder or the call is AUTHORIZATION_ERROR.
Folder walks scan known-smaller files first and keep the 20 MB per-file cap. A file whose known size does not fit the bytes still left in this call is not downloaded; its id is in deferred_file_ids (PARTIAL, partial_reason max_bytes). Grep each deferred id on its own. One call scans up to 200 files. A single file_id is never deferred.

Continuing: when a call stops early and the listing finished, the result has next_cursor. Pass it back unchanged as the next_cursor argument (cursor is the same argument) with the same pattern, case_sensitive, regex and scope (same folder_id, or the same file_ids). After the file cap, the time cap or a Google rate limit it is the last file id scanned; after max_matches it is that file id when later files remain, or file_id:N to continue inside that file after its first N matches. Stopping at exactly max_matches with nothing left is COMPLETE, not PARTIAL.

One match per matching line: location.line and location.offset give the first hit on that line, location.occurrences counts every hit on it, and the context holds the whole line. max_matches counts lines, not hits. Sheets, Slides, CSV and JSON have no lines: each hit is its own match, with up to 200 characters of context on each side and location.offset only.

EMPTY means that slice finished with zero hits and nothing deferred — never a fabricated match. files_scanned and bytes_scanned are always present.

Returns: status, files_scanned, bytes_scanned, optional partial_reason / next_cursor / deferred_file_ids, matches[{file_id,file_name,mime_type,modified_time,source_url,retrieved_at,pattern,matched_text,location,context}]. source_url is drive:{file_id}, not an HTTP download link.
"""
