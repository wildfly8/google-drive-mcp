# Contract: Result status (all retrieval tools)

Every tool result includes:

| `status` | Meaning |
| --- | --- |
| `COMPLETE` | Finished within budgets; no reason to believe more matching work remained |
| `PARTIAL` | A budget, skipped unsupported files in a mixed grep, or sustained rate-limit on a **walk** could plausibly have found more |
| `EMPTY` | Finished coverage of this slice with zero children/hits (not an error). Grep `EMPTY` means nothing was deferred and no cursor remains |
| `ERROR` | Failed; see `category` from [error-taxonomy.md](./error-taxonomy.md) (canonical enum in Access Control) |

`PARTIAL` MUST include `partial_reason`. Truncation MUST NOT be reported as `COMPLETE` or `EMPTY`.

| Tool | `partial_reason` values |
| --- | --- |
| `drive_ls` | `RATE_LIMITED`, `pagination` (more children; `next_page_token` set), `max_execution_time` |
| `drive_find` | `RATE_LIMITED`, `max_execution_time`, `max_files` |
| `drive_read` | `max_bytes` (prefix returned) |
| `drive_grep` | `RATE_LIMITED`, `max_execution_time`, `max_matches`, `max_bytes`, `max_files`, `unsupported_skipped` |

When several apply, the reason is the first listed for that tool.

## Rate-limit (Article X)

| Situation | Result |
| --- | --- |
| List / find / grep **walk** cut short by sustained Google 429, whether or not any items were collected | `status: PARTIAL`, `partial_reason: RATE_LIMITED`. Not `EMPTY`, not `COMPLETE`, not `ErrorEnvelope` `RATE_LIMITED`. |
| Single-file read/export HTTP 429 with **no** usable prefix | `ErrorEnvelope` `category: RATE_LIMITED` |
| `drive_grep` continuation (`next_cursor` set) whose download gets a 429 before it handles any file, including a single named file | `status: PARTIAL`, `partial_reason: RATE_LIMITED`, the incoming cursor returned |
| HTTP 429 while Access Control checks a named id (its metadata get, or the listing of `kb`'s folder tree), before any walk starts | `ErrorEnvelope` `category: RATE_LIMITED`. An omitted folder (`kb` itself) skips the tree listing |

Do not silently retry until the operation can claim `COMPLETE`.

## Grep coverage

Every `drive_grep` result includes `files_scanned` and `bytes_scanned`. `deferred_file_ids` with `partial_reason: max_bytes` means those files were not downloaded. `next_cursor` means the listing finished and more remains: non-deferred files (`max_files`, `max_execution_time`, or `RATE_LIMITED` on a download), or more matches after `max_matches` (`file_id:N` continues inside a file). A continuation whose listing was cut returns its incoming cursor unchanged. `EMPTY` is only a finished slice with zero hits. Deferred ids or a cursor are `PARTIAL`.
