# Contract: `drive_find`

Metadata / Drive-native **candidate** discovery. Recursive when `folder_id` is set. Results are not evidence.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "name_pattern": { "type": "string" },
    "mime_type": { "type": "string" },
    "folder_id": { "type": "string" },
    "modified_after": { "type": "string", "format": "date-time" },
    "modified_before": { "type": "string", "format": "date-time" },
    "trashed": { "type": "boolean", "default": false },
    "max_results": { "type": "integer", "minimum": 1, "maximum": 40 }
  }
}
```

Omitted `folder_id` → default RetrievalScope (whole Google grant), still bounded by `max_results` / `max_files`.

## Output (success)

```json
{
  "type": "object",
  "required": ["status", "candidates"],
  "properties": {
    "status": { "enum": ["COMPLETE", "PARTIAL", "EMPTY"] },
    "partial_reason": { "type": "string" },
    "candidates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["file", "reason", "discovery_method"],
        "properties": {
          "file": { "type": "object" },
          "reason": { "type": "string" },
          "discovery_method": { "const": "find" }
        }
      }
    }
  }
}
```

`file` is DriveFile metadata only (id, name, mime_type, modified_time, web_view_link, is_folder, trashed). No `content` field.

Zero matches after complete scan → `EMPTY`. Hitting `max_files` while descendants remain → `PARTIAL`.
