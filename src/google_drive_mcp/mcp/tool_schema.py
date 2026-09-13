"""MCP initialize instructions and per-tool descriptions advertised on tools/list.

Host-agnostic (FR-102 / Article XIII): no vendor-specific prompting. The host
model extracts keywords; this server does not parse natural language.
"""

from __future__ import annotations

from mcp_types import ToolAnnotations

from google_drive_mcp import __version__

SERVER_NAME = "google-drive-mcp"
SERVER_TITLE = "Google Drive read-only retrieval"
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

Authentication is MCP OAuth 2.1 (authorization code + PKCE, dynamic client
registration). Hosts discover metadata on this origin, then send
`Authorization: Bearer <access_token>` on `/mcp`. Never pass tokens, OAuth
codes, or Google credentials as tool arguments. `MCP_AUTH_TOKEN` is the
resource-owner consent password, not an API bearer.

Loop (repeat with different terms if needed):
1. drive_ls or drive_find → file ids (candidates, not evidence)
2. drive_grep with a short exact phrase taken from the question, preferably on file_ids
3. drive_read for the full text of one file_id
4. If status is PARTIAL, continue; do not treat the result as exhaustive
5. If status is EMPTY, change the phrase or scope — do not invent hits

Hard rules:
- Do not pass the full user question as name_pattern or pattern.
- drive_find name_pattern is a case-insensitive substring of the *filename*, not glob, not contents.
- drive_grep pattern matches exported file *bytes* (literal, or regex if regex=true). Not Drive fullText.
- drive_ls is immediate children only; drive_find / drive_grep on a folder include descendants.
- Omit folder_id to use the deployment default scope (whole grant, or a configured allow-listed folder).
- Candidates from drive_find are not quotes. Evidence is drive_read content or drive_grep matches with provenance.
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
- Orient: what folders/files sit directly under a known folder_id (or the default scope).
- Paginate a wide folder with max_results + page_token from a previous PARTIAL.

When not to use:
- You need nested descendants (use drive_find).
- You need text inside files (use drive_grep or drive_read).
- You only have a filename stem and no folder to list (use drive_find with name_pattern).

Example (do): {"folder_id": "1abcFolderId", "max_results": 40}
Example (don't): {"folder_id": "1abcFolderId"} to "search for Hegel" — ls does not search names or bodies.

Returns: status (COMPLETE | PARTIAL | EMPTY), children[{id,name,mime_type,is_folder,modified_time,source_url}], optional next_page_token / partial_reason. Never includes content.
"""

DRIVE_FIND_TITLE = "Find files by name or type"
DRIVE_FIND_DESCRIPTION = """\
Recursive metadata discovery. Returns SearchCandidate records (file + reason). Not evidence.

When to use:
- Locate files whose *filename* contains a short stem (name_pattern is a case-insensitive substring).
- Filter by mime_type, modified_after / modified_before (ISO-8601), or trashed.
- Walk descendants of a folder_id (unlike drive_ls, which is one level).

When not to use:
- Searching file *contents* (use drive_grep).
- Reading a file you already have an id for (use drive_read).
- Treating hits as verified quotes — candidates have no matched_text.

name_pattern is NOT a glob: "activity" matches activity-2025.mdx; "*activity*" looks for a literal asterisk and usually misses.

Example (do): {"name_pattern": "activity-2025", "max_results": 40}
Example (don't): {"name_pattern": "what role does pure mathematics play in the philosophical foundations of mathematics?"} — that is a question, not a filename.

Returns: status, candidates[{file, reason, discovery_method}]. file has id/name/mime/modified_time/source_url, never content. Hitting max_files while more remain → PARTIAL.
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
Optional max_bytes: 1..5000000; truncation → PARTIAL (prefix returned).

Returns: status, file_id, file_name, mime_type, modified_time, source_url, retrieved_at, content, optional representation / partial_reason. Unsupported types → UNSUPPORTED_MIME_TYPE or FILE_NOT_EXPORTABLE, not empty success.
"""

DRIVE_GREP_TITLE = "Exact-search file contents"
DRIVE_GREP_DESCRIPTION = """\
Deterministic exact match over bytes exported in this call. Not Drive fullText, not embeddings, not keyword-ranking.

When to use:
- Verify a claim with a short distinctive phrase, identifier, title, or term of art taken from the user question.
- Search known file_ids (preferred) or all descendants of a folder_id.
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
Folder walks that hit time/byte/match limits return PARTIAL (possibly with some matches). EMPTY means a complete search with zero hits — never a fabricated match.

Returns: status, matches[{file_id,file_name,mime_type,modified_time,source_url,retrieved_at,pattern,matched_text,location,context}].
"""
