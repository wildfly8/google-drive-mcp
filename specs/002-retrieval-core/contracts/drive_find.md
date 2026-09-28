# Contract: `drive_find`

Metadata / Drive-native **candidate** discovery. Recursive when `folder_id` is set. Results are not evidence.

Must run Access Control chain first. Google-missing folder → `FILE_NOT_FOUND`. A Google-granted folder outside `DRIVE_ALLOWED_FOLDER_ID` → `AUTHORIZATION_ERROR`.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "name_pattern": { "type": "string", "description": "Case-insensitive substring of the filename only — not a glob, not file contents, not a natural-language question" },
    "mime_type": { "type": "string" },
    "folder_id": { "type": "string" },
    "modified_after": { "type": "string", "format": "date-time" },
    "modified_before": { "type": "string", "format": "date-time" },
    "trashed": { "type": "boolean", "default": false },
    "max_results": { "type": "integer", "minimum": 1, "maximum": 40 }
  }
}
```

On this deployment, omitted `folder_id` is `DRIVE_ALLOWED_FOLDER_ID` (`kb`) and its descendants, still bounded by `max_results` / `max_files`. A named `folder_id` outside `kb` is `AUTHORIZATION_ERROR`. When the allow-list is unset, omitted `folder_id` uses `DRIVE_DEFAULT_FOLDER_ID` if set, otherwise `default_whole_grant`. Omitted `drive_ls` lists the same allow-list folder’s immediate children.

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

`file` is DriveFile metadata only (id, name, mime_type, modified_time, `source_url` = `drive:{id}`, is_folder, trashed). No `content` field. `source_url` MUST NOT be an HTTP URL.

The server pushes `name contains` (when `name_pattern` is set), `mimeType`, `modifiedTime` bounds, and `trashed = false` unless `trashed` is true, into `files.list`. `name_pattern` is still confirmed as a case-insensitive filename substring on the listed names. `max_results` counts matching non-folder files only. Listing a folder does not `files.get` each child. Page size is 1000.

Zero matches after a finished scan → `EMPTY`. Hitting `max_files` while more matching files remain → `PARTIAL` with `partial_reason: max_files` (the reason is present even when this page of candidates is empty). Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED`.
