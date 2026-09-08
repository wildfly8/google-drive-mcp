# Contract: `drive_ls`

Enumerate **immediate children** of a folder. No document bodies.

Must run Access Control chain first. Google-missing folder → `FILE_NOT_FOUND`. v1 does not emit `AUTHORIZATION_ERROR` for this tool.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "folder_id": { "type": "string", "description": "Omit for Drive root (`root`); projects default_whole_grant onto My Drive root children" },
    "max_results": { "type": "integer", "minimum": 1, "maximum": 40 },
    "page_token": { "type": "string" }
  }
}
```

Invalid `max_results` → `INVALID_ARGUMENT`.

## Output (success)

```json
{
  "type": "object",
  "required": ["status", "children"],
  "properties": {
    "status": { "enum": ["COMPLETE", "PARTIAL", "EMPTY"] },
    "partial_reason": { "type": "string" },
    "next_page_token": { "type": "string" },
    "children": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "mime_type", "is_folder", "modified_time", "source_url"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "mime_type": { "type": "string" },
          "is_folder": { "type": "boolean" },
          "modified_time": { "type": "string" },
          "source_url": { "type": "string", "description": "From Drive webViewLink" }
        }
      }
    }
  }
}
```

If `page_token`/`max_results` leave more children, `status` is `PARTIAL` (or `COMPLETE` only when `next_page_token` is absent and no truncation). Empty folder → `EMPTY`, `children: []`. Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED`.
