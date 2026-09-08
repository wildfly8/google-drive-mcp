# Data Model: Retrieval Core

Request-scoped only. Drive remains the source of truth.

Wire field for a view link is always `source_url` (adapter maps Drive `webViewLink`). Domain `DriveFile.web_view_link` is the internal Drive-shaped name only.

## DriveFile

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Required |
| `name` | string | |
| `mime_type` | string | |
| `parents` | string[] | Used by `is_within_scope` |
| `modified_time` | datetime | RFC3339 from Drive |
| `created_time` | datetime? | |
| `web_view_link` | string? | Drive `webViewLink`; expose on the wire as `source_url` |
| `size` | int? | |
| `owners` | string[]? | Non-secret names/emails if Drive returns them; never tokens |
| `trashed` | bool | |
| `is_folder` | bool | `mime_type == application/vnd.google-apps.folder` |

## Folder

A `DriveFile` with `is_folder=true`. Hierarchy is a discovery signal.

## RetrievalScope

Canonical type. Access Control enforces the same fields (`src/google_drive_mcp/domain/retrieval_scope.py`).

| Field | Type | Rules |
| --- | --- | --- |
| `folder_id` | string? | If set: ls = immediate children; find/grep = this folder and descendants |
| `file_ids` | string[]? | If set: only these files |
| `default_whole_grant` | bool | True when neither folder nor file list named |

`is_within_scope(file_id, scope, parent_lookup)` is the only descendant check. Retrieval walks and the authorization chain MUST call it. Do not fork a second parent walk.

Enforced by Access Control before content export. `drive_ls` with `default_whole_grant` lists immediate children of My Drive `root` only — a projection of the grant, not a narrower MCP allow-list.

## DocumentContent

| Field | Type | Rules |
| --- | --- | --- |
| `file_id` | string | Required |
| `mime_type` | string | Source Drive MIME |
| `representation` | string | Export MIME actually used |
| `content` | string | Usable text; discarded after the operation |
| `retrieved_at` | datetime | MCP clock, ISO-8601 |
| `byte_length` | int | |

Invalid if `file_id` missing. Not a cache key. Plays the **evidence** role when returned from `drive_read` with provenance.

## SearchCandidate

| Field | Type | Rules |
| --- | --- | --- |
| `file` | DriveFile | Metadata only; wire link field is `source_url` |
| `reason` | string | Why it was surfaced (name match, mime filter, etc.) |
| `discovery_method` | enum | `find` only (`drive_ls` does not return this type) |

**Not evidence.** MUST NOT be labeled verified.

## SearchMatch

| Field | Type | Rules |
| --- | --- | --- |
| `file_id` | string | Required |
| `file_name` | string | |
| `pattern` | string | As supplied |
| `matched_text` | string | Required |
| `location` | object | `{ "line"?: int, "offset"?: int }` |
| `context` | string? | Surrounding text per plan (lines or 200-char window) |

A SearchMatch MUST correspond to bytes actually retrieved in this operation. Plays the **evidence** role when returned from `drive_grep` with provenance.

## Evidence (conceptual)

Not a class, not a wire type, not a task. Role played by `DocumentContent` and `SearchMatch` when provenance is present. Never played by `SearchCandidate` or agent inference.

## Provenance

| Field | Type | Required |
| --- | --- | --- |
| `file_id` | string | yes |
| `file_name` | string | yes |
| `mime_type` | string | yes |
| `modified_time` | datetime | yes |
| `source_url` | string | yes (from Drive `webViewLink` or equivalent) |
| `matched_text` / `location` | string / object | grep only; omit on `drive_read` |
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
| `partial_reason` | string? | `max_files` \| `max_bytes` \| `max_matches` \| `max_execution_time` \| `RATE_LIMITED` \| `unsupported_skipped` \| … |

## Relationships

```text
DriveFile ≠ Evidence
SearchCandidate ≠ Evidence
DocumentContent (with provenance) plays Evidence
SearchMatch (with provenance) plays Evidence
DocumentContent ≠ persistent cache
Agent inference ≠ Evidence
```
