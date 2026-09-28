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
    "folder_id": { "type": "string" },
    "case_sensitive": { "type": "boolean", "default": true },
    "regex": { "type": "boolean", "default": false },
    "context_lines": { "type": "integer", "minimum": 0, "maximum": 10, "default": 2 },
    "max_matches": { "type": "integer", "minimum": 1, "maximum": 50 },
    "cursor": { "type": "string", "description": "next_cursor from a previous folder or whole-grant grep. Not valid together with file_ids." }
  }
}
```

If both `file_ids` and `folder_id` omitted → `default_whole_grant`, still budgeted (`PARTIAL` expected on large drives). `regex=false` → literal (`re.escape`). Invalid regex, out-of-range budgets, `cursor` combined with `file_ids`, or a `cursor` that is not a file id in a finished listing → `INVALID_ARGUMENT`. Runtime engine failure after a valid compile → `SEARCH_ERROR`.

A folder or whole-grant call scans known-smaller files first. The per-file cap stays 20 MB, so one named `file_id` (including a ~19 MB `.mdx`) is exported in that call and is never placed in `deferred_file_ids`. A known size that does not fit the bytes left in the operation is not downloaded; that id and the larger tail are `deferred_file_ids`. Unknown size is not deferred only because remaining bytes are below 20 MB.

When **both** `folder_id` and `file_ids` are set: Access Control step 4 metadata-checks each named id. Granted file outside the folder → `AUTHORIZATION_ERROR`. Ungranted → `FILE_NOT_FOUND`.

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
    "next_cursor": { "type": "string", "description": "Last file id scanned, when the listing finished and more non-deferred files remain" },
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
          "location": { "type": "object" },
          "context": { "type": "string" }
        }
      }
    }
  }
}
```

`files_scanned` and `bytes_scanned` are always present. No matches after a finished slice with nothing deferred → `EMPTY`, `matches: []` (never fabricate). Deferred files or a `next_cursor` mean `PARTIAL`, not `EMPTY`. `next_cursor` is set only when the listing finished and more non-deferred files remain because of `max_files` or `max_execution_time`. A listing cut by time or Google 429 does not include `next_cursor`. Identical bytes + identical params in this request → identical `matches`. Content discarded after the call. Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED` (even if `matches` is empty). Hosts grep each `deferred_file_ids` entry as its own `file_ids` call, and repeat the same pattern and scope with `cursor` when `next_cursor` is set.

## Unsupported files

| Target | Result |
| --- | --- |
| Only `file_ids`, and every named file is unsupported / not exportable | `ERROR` / `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` |
| `folder_id` or `default_whole_grant` walk: mix of searchable and unsupported | Skip unsupported, search the rest, `PARTIAL` with `partial_reason` noting skips |
| Walk: every target unsupported | `ERROR` / `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` |
