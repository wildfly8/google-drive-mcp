# Contract: `drive_ls`

Enumerate **immediate children** of a folder. No document bodies.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "folder_id": { "type": "string", "description": "Omit for Drive root (`root`)" },
    "max_results": { "type": "integer", "minimum": 1, "maximum": 40 },
    "page_token": { "type": "string" }
  }
}
```

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
        "required": ["id", "name", "mime_type", "is_folder", "modified_time"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "mime_type": { "type": "string" },
          "is_folder": { "type": "boolean" },
          "modified_time": { "type": "string" },
          "web_url": { "type": "string" }
        }
      }
    }
  }
}
```

If `page_token`/`max_results` leave more children, `status` is `PARTIAL` (or `COMPLETE` only when `next_page_token` is absent and no truncation). Empty folder → `EMPTY`, `children: []`.

Must run Access Control chain first. Out-of-scope folder_id → `AUTHORIZATION_ERROR`. Google-missing folder → `FILE_NOT_FOUND`.
