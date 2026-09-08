# Contract: `drive_read`

Current usable text from live Drive. Never from an MCP-owned copy.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["file_id"],
  "properties": {
    "file_id": { "type": "string" },
    "content_format": { "type": "string", "description": "Optional; default is the plan export map" },
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

Truncation at `max_bytes` → `PARTIAL`, content is the prefix actually read. Missing `file_id` in output is invalid.

## Errors

| category | When |
| --- | --- |
| `FILE_NOT_FOUND` | Google grant miss or missing file (Access Control / Drive) |
| `AUTHORIZATION_ERROR` | file_id outside this call’s scope |
| `UNSUPPORTED_MIME_TYPE` | Cannot yield usable text |
| `FILE_NOT_EXPORTABLE` | Workspace type that export refuses |
| `RESOURCE_LIMIT` | Over max_export_size with no usable prefix policy — prefer `PARTIAL` when a prefix exists |
| `DRIVE_API_ERROR` | Other upstream failures |
| `INVALID_ARGUMENT` | Bad file_id shape / max_bytes |
