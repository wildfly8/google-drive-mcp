# Contract: `drive_find`

Metadata / Drive-native **candidate** discovery. Recursive when `folder_id` is set. Results are not evidence.

Must run Access Control chain first. Google-missing folder → `FILE_NOT_FOUND`. v1 does not emit `AUTHORIZATION_ERROR` for this tool.

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

Omitted `folder_id` → `default_whole_grant` (whole Google grant), still bounded by `max_results` / `max_files`. This universe MAY be larger than omitted-folder `drive_ls` (My Drive `root` children only).

Invalid `max_results` or date-time → `INVALID_ARGUMENT`.

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

`file` is DriveFile metadata only (id, name, mime_type, modified_time, `source_url`, is_folder, trashed). No `content` field.

Zero matches after complete scan → `EMPTY`. Hitting `max_files` while descendants remain → `PARTIAL`. Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED`.
