# Contract: Result status (all retrieval tools)

Every tool result includes:

| `status` | Meaning |
| --- | --- |
| `COMPLETE` | Finished within budgets; no reason to believe more matching work remained |
| `PARTIAL` | A budget, skipped unsupported files in a mixed grep, or sustained rate-limit on a **walk** could plausibly have found more |
| `EMPTY` | Finished coverage of this slice with zero children/hits (not an error). Grep `EMPTY` means nothing was deferred and no cursor remains |
| `ERROR` | Failed; see `category` from [error-taxonomy.md](./error-taxonomy.md) (canonical enum in Access Control) |

`PARTIAL` MUST include `partial_reason`. Truncation MUST NOT be reported as `COMPLETE` or `EMPTY`.

## Rate-limit (Article X)

| Situation | Result |
| --- | --- |
| List / find / grep **walk** cut short by sustained Google 429, whether or not any items were collected | `status: PARTIAL`, `partial_reason: RATE_LIMITED`. Not `EMPTY`, not `COMPLETE`, not `ErrorEnvelope` `RATE_LIMITED`. |
| Single-file read/export HTTP 429 with **no** usable prefix | `ErrorEnvelope` `category: RATE_LIMITED` |

Do not silently retry until the operation can claim `COMPLETE`.

## Grep coverage

Folder `drive_grep` results include `files_scanned` and `bytes_scanned`. `deferred_file_ids` with `partial_reason: max_bytes` means those files were not downloaded. `next_cursor` means the listing finished and more remains: non-deferred files (`max_files`, `max_execution_time`, or `RATE_LIMITED` on a download), or more matches after `max_matches` (`file_id:N` continues inside a file). A continuation whose listing was cut returns its incoming cursor unchanged. `EMPTY` is only a finished slice with zero hits. Deferred ids or a cursor are `PARTIAL`.
