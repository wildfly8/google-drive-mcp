# Contract: `drive_find`

Metadata / Drive-native **candidate** discovery. Recursive when `folder_id` is set. Results are not evidence.

Must run Access Control chain first. A named folder that is not `DRIVE_ALLOWED_FOLDER_ID` (`kb`) or a descendant → `AUTHORIZATION_ERROR`, whether it lies outside `kb`, does not exist, or Google does not grant it. `FILE_NOT_FOUND` only when a folder already proven inside `kb` then misses.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "name_pattern": { "type": "string", "description": "Case-insensitive substring of the filename only — not a glob, not file contents, not a natural-language question" },
    "mime_type": { "type": "string" },
    "folder_id": { "type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$" },
    "modified_after": { "type": "string", "format": "date-time", "description": "Inclusive lower bound on modifiedTime" },
    "modified_before": { "type": "string", "format": "date-time", "description": "Inclusive upper bound on modifiedTime" },
    "trashed": { "type": "boolean", "default": false },
    "max_results": { "type": "integer", "minimum": 1, "maximum": 40, "description": "Default 40" }
  }
}
```

Omitted `folder_id` is the required `DRIVE_ALLOWED_FOLDER_ID` (`kb` on this deployment) and its descendants, still bounded by `max_results` / `max_files`. A named `folder_id` that is not `kb` or a descendant is `AUTHORIZATION_ERROR`. There is no whole-grant find. Omitted `drive_ls` lists the same folder’s immediate children.

Invalid `max_results`, date-time or `folder_id` shape, or an argument not in this schema (for example `file_id`) → `INVALID_ARGUMENT`.

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

`file` is DriveFile metadata only (id, name, mime_type, modified_time, `source_url` = `drive:{id}`, is_folder, trashed). No `content` field. `source_url` MUST NOT be an HTTP URL. `reason` is `name match` (when `name_pattern` is set), `mime filter` (when `mime_type` is set without `name_pattern`), or `folder descendant`.

The server pushes `name contains` (when `name_pattern` is set), `mimeType`, `modifiedTime` bounds, and `trashed = false` unless `trashed` is true, into `files.list`. `name_pattern` is still confirmed as a case-insensitive filename substring on the listed names. `max_results` counts matching non-folder files only; matching folders are still returned, under their own cap of the same size (more → `PARTIAL` `max_files`). The walk stops listing at the file cap, so a folder listed after it may be omitted from that `PARTIAL` result. When `mime_type` is the folder type, folders count. With any filter, the query also returns subfolders so the walk can descend; a subfolder is a candidate only if it matches. Listing a folder does not `files.get` each child. A listed child whose `parents` do not include the folder being listed is dropped. Page size is 1000.

Zero matches after a finished scan → `EMPTY`. Hitting `max_files` while more matching files remain → `PARTIAL` with `partial_reason: max_files` (the reason is present even when this page of candidates is empty). Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED`. Walk cut by the time cap → `PARTIAL`, `partial_reason: max_execution_time`. When several apply, the reason is the first of `RATE_LIMITED`, `max_execution_time`, `max_files`.
