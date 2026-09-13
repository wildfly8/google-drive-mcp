# Contract: `drive_read`

Current usable text from live Drive. Never from an MCP-owned copy.

Must run Access Control chain first. v1 does **not** emit `AUTHORIZATION_ERROR` (single `file_id` is the call’s scope). Google grant miss or missing file → `FILE_NOT_FOUND` via shared `map_google_error()`.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["file_id"],
  "properties": {
    "file_id": { "type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$", "description": "Drive file id from ls/find/grep — not a filename or question" },
    "content_format": { "type": "string", "description": "Optional. Omit for the plan export map (Docs/Slides text/plain, Sheets text/csv, text blobs as stored). Unknown or type-incompatible value → INVALID_ARGUMENT" },
    "max_bytes": { "type": "integer", "minimum": 1, "maximum": 5000000 }
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
    "source_url": { "type": "string" },
    "retrieved_at": { "type": "string" },
    "representation": { "type": "string" },
    "content": { "type": "string" }
  }
}
```

Match fields (`matched_text`, `location`) MUST NOT be required. Truncation at `max_bytes` with a usable prefix → `PARTIAL`, `partial_reason: max_bytes`; content is the prefix actually read. Missing `file_id` in output is invalid.

## Errors

Canonical categories: [error-taxonomy.md](./error-taxonomy.md).

| category | When |
| --- | --- |
| `FILE_NOT_FOUND` | Google grant miss or missing file (`map_google_error`) |
| `UNSUPPORTED_MIME_TYPE` | Cannot yield usable text |
| `FILE_NOT_EXPORTABLE` | Workspace type that export refuses |
| `RESOURCE_LIMIT` | Over `max_export_size` / hard cap with **no** usable prefix |
| `RATE_LIMITED` | HTTP 429 on this single-file export with **no** usable prefix |
| `DRIVE_API_ERROR` | Other upstream failures |
| `INVALID_ARGUMENT` | Bad `file_id` shape / `max_bytes` out of range / unknown or type-incompatible `content_format` |
| `TEMPORARY_STORAGE_ERROR` | Tempfile create/cleanup failure |
