# Contract: `drive_read`

Current usable text from live Drive. Never from an MCP-owned copy.

Must run Access Control chain first. A `file_id` not proven to be inside `DRIVE_ALLOWED_FOLDER_ID` (`kb`) → `AUTHORIZATION_ERROR`, whether it lies outside `kb`, does not exist, or Google does not grant it. A file already proven inside `kb` that then misses → `FILE_NOT_FOUND` via shared `map_google_error()`.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["file_id"],
  "properties": {
    "file_id": { "type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$", "description": "Drive file id from ls/find/grep — not a filename or question" },
    "content_format": { "type": "string", "description": "Optional. Omit for the plan export map (Docs/Slides text/plain, Sheets text/csv, text blobs as stored). Docs, Sheets and Slides accept only that default. Unknown or type-incompatible value → INVALID_ARGUMENT" },
    "max_bytes": { "type": "integer", "minimum": 1, "maximum": 20000000, "description": "Default 20000000" }
  }
}
```

## Output (success)

```json
{
  "type": "object",
  "required": ["status", "file_id", "file_name", "mime_type", "modified_time", "source_url", "retrieved_at", "content"],
  "properties": {
    "status": { "enum": ["COMPLETE", "PARTIAL"] },
    "partial_reason": { "type": "string" },
    "file_id": { "type": "string" },
    "file_name": { "type": "string" },
    "mime_type": { "type": "string" },
    "modified_time": { "type": "string" },
    "source_url": { "type": "string", "description": "Non-HTTP locator drive:{file_id}; never a downloadable URL" },
    "retrieved_at": { "type": "string" },
    "representation": { "type": "string" },
    "content": { "type": "string" }
  }
}
```

Match fields (`matched_text`, `location`) MUST NOT be required. Truncation at `max_bytes` with a usable prefix → `PARTIAL`, `partial_reason: max_bytes`; content is the prefix actually read. Missing `file_id` in output is invalid. `source_url` MUST be `drive:{file_id}` and MUST NOT be an HTTP URL.

On the wire the answer stays near the UTF-8 size of `content` (no `\uXXXX` re-encoding), so a read at the 20 MB cap fits Cloud Run's 32 MiB response cap even for CJK text (FR-106).

## Errors

Canonical categories: [error-taxonomy.md](./error-taxonomy.md).

| category | When |
| --- | --- |
| `AUTHORIZATION_ERROR` | Raised by Access Control: `file_id` not proven inside `kb` (outside it, missing, or not granted) |
| `FILE_NOT_FOUND` | File already proven inside `kb` that Google then misses (`map_google_error`) |
| `UNSUPPORTED_MIME_TYPE` | Cannot yield usable text, including a folder id |
| `FILE_NOT_EXPORTABLE` | Workspace type that export refuses |
| `RESOURCE_LIMIT` | Over `max_export_size` / hard cap with **no** usable prefix |
| `RATE_LIMITED` | HTTP 429 on this file's metadata get or export, with **no** usable prefix, or no large-download slot free within 10 s (a file over about 2 MB or of unknown size, FR-106). Access Control returns it too for a 429 while it checks the id (its metadata get or the listing of `kb`'s folder tree) |
| `DRIVE_API_ERROR` | Other upstream failures, including a Drive HTTP call that stalls past 20 s |
| `INVALID_ARGUMENT` | Bad `file_id` shape / `max_bytes` out of range / unknown or type-incompatible `content_format`, or any `content_format` on a type that cannot yield text / any argument other than `file_id`, `content_format`, `max_bytes` |
| `TEMPORARY_STORAGE_ERROR` | Tempfile create/cleanup failure. Not produced today: downloads stay in memory (FR-106) |

## Citing

The tool description ends with: "Citing: one line at the end of your answer, Source: onto-kb connector; never list or cite individual files, ids or links, except a Stack Exchange link beside text quoted word for word from Stack Exchange." Provenance fields in the result are for the agent, not for the answer (FR-050a).
