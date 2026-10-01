# Contract: `drive_ls`

Enumerate **immediate children** of a folder. No document bodies.

Must run Access Control chain first. A named folder that is not `DRIVE_ALLOWED_FOLDER_ID` (`kb`) or a descendant → `AUTHORIZATION_ERROR`, whether it lies outside `kb`, does not exist, or Google does not grant it (AC-FR-021). `FILE_NOT_FOUND` only when a folder already proven inside `kb` then misses. There is no listing without a folder: My Drive `root` is never listed.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "folder_id": { "type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$", "description": "Omit to list DRIVE_ALLOWED_FOLDER_ID (kb on this deployment). A named folder outside kb, or one that does not exist, is AUTHORIZATION_ERROR." },
    "max_results": { "type": "integer", "minimum": 1, "maximum": 40, "description": "Page size, default 40; remaining children → PARTIAL + next_page_token" },
    "page_token": { "type": "string", "description": "next_page_token from the previous page (a decimal offset). Omit on the first page." }
  }
}
```

Invalid `max_results`, a `folder_id` that does not match the id pattern, a `page_token` that is not a decimal integer, or any argument other than `folder_id`, `max_results`, and `page_token` (for example `file_id`) → `INVALID_ARGUMENT`.

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
          "source_url": { "type": "string", "description": "Non-HTTP locator drive:{id}; never webViewLink" }
        }
      }
    }
  }
}
```

If `page_token`/`max_results` leave more children, `status` is `PARTIAL`, `partial_reason: pagination`, with `next_page_token` (`COMPLETE` only when `next_page_token` is absent and no truncation). Empty folder → `EMPTY`, `children: []`. Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED`. Time cap → `PARTIAL`, `partial_reason: max_execution_time`. Trashed children are not listed. A listed child whose `parents` do not include `folder_id` is dropped (stale Drive search-index entry).
