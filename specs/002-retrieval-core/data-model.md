# Data Model: Retrieval Core

Request-scoped only. Drive remains the source of truth.

Results carry `file_id`, `file_name` and `modified_time` as provenance, for the agent's own tracking, and no source link or locator (no `source_url`, no `drive:{id}`), because hosts list any such field as a source (T086). A final answer cites everything as the single line `Source: onto-kb connector` (FR-050a). Domain `DriveFile.web_view_link` may store Drive `webViewLink` internally but MUST NEVER be copied onto the wire (hosts treat HTTPS URLs in tool JSON as downloadable Cited Sources).

## DriveFile

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Required |
| `name` | string | |
| `mime_type` | string | |
| `parents` | string[] | Used by `is_within_scope`, the listing membership check, and Access Control's folder-tree check |
| `modified_time` | datetime | RFC3339 from Drive |
| `created_time` | datetime? | |
| `web_view_link` | string? | Drive `webViewLink` if fetched; internal only, never on the wire |
| `size` | int? | Drive byte size. `drive_grep` uses it only for blobs: Docs, Sheets and Slides count as unknown size |
| `owners` | string[]? | Not requested by the production client; never tokens |
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
| `default_whole_grant` | bool | True when neither folder nor file list named. Access Control refuses this scope (`whole_grant_refused`) |

Descendant checks live only in `domain/retrieval_scope.py`. Retrieval walks call `is_within_scope(file_id, scope, parent_lookup)` for named `file_ids`. The Access Control allow-list check lists `kb`'s folder tree top down (`folder_tree`) and decides membership in memory (`is_inside_tree`), so an id outside `kb`, a missing id and an ungranted id take the same Drive calls. Do not add a descendant check anywhere else. Folder listings keep only children whose `parents` include the listed folder (one membership check on the listing, not a parent walk).

Enforced by Access Control before content export. `DRIVE_ALLOWED_FOLDER_ID` is required (`kb` on this deployment). Access Control rewrites an omitted `folder_id` on `drive_ls`, `drive_find`, and `drive_grep` to that folder, and refuses any named folder or file it cannot prove is that folder or a descendant, whether or not the id exists. No retrieval path lists without a folder: `drive_ls` never lists My Drive `root`, and the Drive port has no whole-grant listing (`list_all` removed).

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
| `file` | DriveFile | Metadata only; no link or locator on the wire |
| `reason` | string | Why it was surfaced: `name match`, `mime filter`, or `folder descendant` |
| `discovery_method` | enum | `find` only (`drive_ls` does not return this type) |

**Not evidence.** MUST NOT be labeled verified.

## SearchMatch

| Field | Type | Rules |
| --- | --- | --- |
| `file_id` | string | Required |
| `file_name` | string | |
| `pattern` | string | As supplied |
| `matched_text` | string | Required |
| `location` | object | `{ "line"?: int, "offset"?: int, "occurrences"?: int }`; line-oriented text has one match per line, `offset` is the first hit's character offset in that line and `occurrences` counts every hit on it (FR-039). Otherwise `{ "offset" }`, the character offset in the whole text |
| `context` | string? | Line-oriented text: the matching line plus `context_lines` lines on each side. Otherwise up to 200 characters on each side of the hit |

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
| `partial_reason` | string? | `max_files` \| `max_bytes` \| `max_matches` \| `max_execution_time` \| `RATE_LIMITED` \| `unsupported_skipped` \| `pagination` (`drive_ls` only) |
| `files_scanned` / `bytes_scanned` | int | `drive_grep` only; always present |
| `next_cursor` | string? | `drive_grep`; a file id (continue after it) or `file_id:N` (continue inside it after N matches) when more remains |
| `deferred_file_ids` | string[]? | `drive_grep`; searchable files not downloaded on this call because their known size did not fit the bytes left, or the byte cap was reached. Never unsupported files |
| `next_page_token` | string? | `drive_ls`; decimal offset of the next page, passed back as `page_token` |

## Relationships

```text
DriveFile ≠ Evidence
SearchCandidate ≠ Evidence
DocumentContent (with provenance) plays Evidence
SearchMatch (with provenance) plays Evidence
DocumentContent ≠ persistent cache
Agent inference ≠ Evidence
```
