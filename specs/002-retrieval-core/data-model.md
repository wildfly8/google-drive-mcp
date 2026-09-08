# Data Model: Retrieval Core

Request-scoped only. Drive remains the source of truth.

## DriveFile

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Required |
| `name` | string | |
| `mime_type` | string | |
| `parents` | string[] | |
| `modified_time` | datetime | RFC3339 from Drive |
| `created_time` | datetime? | |
| `web_view_link` | string? | |
| `size` | int? | |
| `owners` | string[]? | Non-secret names/emails if Drive returns them; never tokens |
| `trashed` | bool | |
| `is_folder` | bool | `mime_type == application/vnd.google-apps.folder` |

## Folder

A `DriveFile` with `is_folder=true`. Hierarchy is a discovery signal.

## RetrievalScope

| Field | Type | Rules |
| --- | --- | --- |
| `folder_id` | string? | If set: ls = immediate children; find/grep = this folder and descendants |
| `file_ids` | string[]? | If set: only these files |
| `default_whole_grant` | bool | True when neither folder nor file list named |

Enforced by Access Control before these entities are loaded as content.

## DocumentContent

| Field | Type | Rules |
| --- | --- | --- |
| `file_id` | string | Required |
| `mime_type` | string | Source Drive MIME |
| `representation` | string | Export MIME actually used |
| `content` | string | Usable text; discarded after the operation |
| `retrieved_at` | datetime | MCP clock, ISO-8601 |
| `byte_length` | int | |

Invalid if `file_id` missing. Not a cache key.

## SearchCandidate

| Field | Type | Rules |
| --- | --- | --- |
| `file` | DriveFile | |
| `reason` | string | Why it was surfaced (name match, mime filter, etc.) |
| `discovery_method` | enum | `ls` \| `find` |

**Not evidence.** MUST NOT be labeled verified.

## SearchMatch

| Field | Type | Rules |
| --- | --- | --- |
| `file_id` | string | Required |
| `file_name` | string | |
| `pattern` | string | As supplied |
| `matched_text` | string | |
| `location` | object | `{ "line"?: int, "offset"?: int }` |
| `context` | string? | Surrounding text per plan (lines or 200-char window) |

A SearchMatch MUST correspond to bytes actually retrieved in this operation.

## Evidence

| Field | Type | Rules |
| --- | --- | --- |
| `source_file` | DriveFile | Minimum id, name, modified_time |
| `content` | string | Excerpt or body |
| `location` | object? | |
| `retrieval_timestamp` | datetime | |
| `provenance` | Provenance | |

Agent inference is not this type.

## Provenance

| Field | Type | Required |
| --- | --- | --- |
| `file_id` | string | yes |
| `file_name` | string | yes |
| `mime_type` | string | yes |
| `modified_time` | datetime | yes |
| `source_url` | string | yes (`webViewLink` or equivalent) |
| `matched_text` / `location` | string / object | for grep |
| `retrieved_at` | datetime | yes |

A content-derived result without `file_id` is invalid.

## RetrievalOperation

| Field | Type | Rules |
| --- | --- | --- |
| `operation_id` | string | = `request_id` |
| `tool` | enum | `drive_ls` \| `drive_find` \| `drive_read` \| `drive_grep` |
| `scope` | RetrievalScope | |
| `query` / `pattern` | string? | |
| `start_time` / `end_time` | datetime | |
| `result_count` | int | |
| `status` | enum | `COMPLETE` \| `PARTIAL` \| `EMPTY` \| `ERROR` |
| `partial_reason` | string? | `max_files` \| `max_bytes` \| `max_matches` \| `max_execution_time` \| `RATE_LIMITED` \| … |

## Relationships

```text
DriveFile ≠ Evidence
SearchCandidate ≠ Evidence
DocumentContent ≠ persistent cache
Agent inference ≠ Evidence
```
