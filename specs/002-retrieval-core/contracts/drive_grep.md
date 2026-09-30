# Contract: `drive_grep`

Deterministic exact search over bytes retrieved **in this call**. Folder scope is recursive. Not Drive `fullText`.

Must run Access Control chain first.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["pattern"],
  "properties": {
    "pattern": { "type": "string", "minLength": 1, "description": "Exact phrase in exported bytes (literal unless regex=true). Short term of art, not the whole user question. Not Drive fullText." },
    "file_ids": { "type": "array", "items": { "type": "string" } },
    "folder_id": { "type": "string", "description": "Omit to search DRIVE_ALLOWED_FOLDER_ID (kb on this deployment). A named id outside kb, or one that does not exist, is AUTHORIZATION_ERROR." },
    "next_cursor": { "type": "string", "description": "Previous result field next_cursor, unchanged: a file id (continue after it) or file_id:N (continue inside it after its first N matches). Empty starts at the first file. Alias: cursor." },
    "cursor": { "type": "string", "description": "Alias of next_cursor." },
    "case_sensitive": { "type": "boolean", "default": true },
    "regex": { "type": "boolean", "default": false },
    "context_lines": { "type": "integer", "minimum": 0, "maximum": 10, "default": 2 },
    "max_matches": { "type": "integer", "minimum": 1, "maximum": 50 }
  }
}
```

If both `file_ids` and `folder_id` are omitted (blank ids count as omitted), grep searches the required `DRIVE_ALLOWED_FOLDER_ID` (`kb` on this deployment). There is no whole-grant grep. A named folder or file that is not `kb` or a descendant is `AUTHORIZATION_ERROR`, whether it exists or not. `regex=false` → literal (`re.escape`). Invalid regex, out-of-range budgets, an argument not in this schema, a cursor that names a file not in `file_ids` (when `file_ids` is set), a malformed `file_id:N` (N must be a positive integer), or a continuation id that is not a file id in a finished listing → `INVALID_ARGUMENT`. An empty `next_cursor` starts at the first file. Runtime engine failure after a valid compile → `SEARCH_ERROR`.

A folder call scans known-smaller files first, up to 200 files per call (then `PARTIAL`, `partial_reason: max_files`, with `next_cursor`). The folder walk drops a listed child whose `parents` do not include the folder being listed. The per-file cap stays 20 MB, so one named `file_id` (including a ~19 MB `.mdx`) is exported in that call and is never placed in `deferred_file_ids`. A known size that does not fit the bytes left in the operation is not downloaded; that id and the larger tail are `deferred_file_ids`. Unknown size is not deferred only because remaining bytes are below 20 MB.

When **both** `folder_id` and `file_ids` are set: Access Control step 4 first checks that each named id is inside `kb`, then metadata-checks it. A file outside `kb`, missing, or not granted → `AUTHORIZATION_ERROR`. A granted file inside `kb` but outside the named folder → `AUTHORIZATION_ERROR`. A file proven inside `kb` that then misses → `FILE_NOT_FOUND`.

## Output (success)

```json
{
  "type": "object",
  "required": ["status", "matches", "files_scanned", "bytes_scanned"],
  "properties": {
    "status": { "enum": ["COMPLETE", "PARTIAL", "EMPTY"] },
    "partial_reason": { "type": "string" },
    "files_scanned": { "type": "integer" },
    "bytes_scanned": { "type": "integer" },
    "next_cursor": { "type": "string", "description": "Set when the listing finished and more remains: the last file id scanned (file cap, time cap, download 429), the file id where max_matches stopped when later files remain, or file_id:N to continue inside that file" },
    "deferred_file_ids": { "type": "array", "items": { "type": "string" } },
    "matches": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["file_id", "file_name", "mime_type", "modified_time", "source_url", "retrieved_at", "pattern", "matched_text", "location"],
        "properties": {
          "file_id": { "type": "string" },
          "file_name": { "type": "string" },
          "mime_type": { "type": "string" },
          "modified_time": { "type": "string" },
          "source_url": { "type": "string", "description": "Non-HTTP locator drive:{file_id}; never a downloadable URL" },
          "retrieved_at": { "type": "string" },
          "pattern": { "type": "string" },
          "matched_text": { "type": "string" },
          "location": { "type": "object", "description": "Line-oriented text: {line, offset, occurrences}; offset is the first hit on that line and occurrences counts every hit on it. Sheets/Slides/CSV/JSON: {offset}." },
          "context": { "type": "string" }
        }
      }
    }
  }
}
```

In line-oriented text (Docs, Markdown, plain text) each match is one line: `matched_text` and `location.offset` are the first hit, `location.occurrences` counts every hit on that line, the context holds the whole line, and `max_matches` counts lines. Sheets, Slides, CSV and JSON have no lines, so each hit is its own match, with up to 200 characters of context on each side. `files_scanned` and `bytes_scanned` are always present. No matches after a finished slice with nothing deferred → `EMPTY`, `matches: []` (never fabricate). Deferred files or a `next_cursor` mean `PARTIAL`, not `EMPTY`. `next_cursor` is set only when the listing finished and more remains: non-deferred files after the file cap, the time cap or a Google 429 on a download (the last file id scanned), or more matches after a `max_matches` stop (the file id when later files remain, `file_id:N` when that file has more after its first N matches). Stopping at exactly `max_matches` with nothing left is `COMPLETE`. A listing cut by time or Google 429 does not include `next_cursor`. Small files may be downloaded ahead on worker threads; matches are still taken in size order, so results do not depend on download timing. `bytes_scanned` charges Drive's size when known (the exported length otherwise). A continuation repeats `pattern`, `case_sensitive` and `regex` (N counts matches for them) and the same scope. Deferred ids after the cursor are left out because the next call revisits them. Repeated ids in `file_ids` are searched once. A stop before any file was scanned has no cursor (repeat the call), except that a continuation returns its own cursor again. A continuation whose remaining files are all unsupported is `PARTIAL` `unsupported_skipped`. Identical bytes + identical params in this request → identical `matches`. Content discarded after the call. Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED` (even if `matches` is empty). Hosts grep each `deferred_file_ids` entry as its own `file_ids` call, and repeat the same pattern and scope with `cursor` when `next_cursor` is set.

## Unsupported files

| Target | Result |
| --- | --- |
| Only `file_ids`, and every named file is unsupported / not exportable | `ERROR` / `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` |
| `folder_id` walk: mix of searchable and unsupported | Skip unsupported, search the rest, `PARTIAL` with `partial_reason` noting skips |
| Walk: every target unsupported | `ERROR` / `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` |
