# Contract: Result status (all retrieval tools)

Every tool result includes:

| `status` | Meaning |
| --- | --- |
| `COMPLETE` | Finished within budgets; no reason to believe more matching work remained |
| `PARTIAL` | A budget, skipped unsupported files in a mixed grep, or sustained rate-limit on a **walk** could plausibly have found more |
| `EMPTY` | Finished complete coverage with zero children/hits (not an error) |
| `ERROR` | Failed; see `category` from [error-taxonomy.md](./error-taxonomy.md) (canonical enum in Access Control) |

`PARTIAL` MUST include `partial_reason`. Truncation MUST NOT be reported as `COMPLETE` or `EMPTY`.

## Rate-limit (Article X)

| Situation | Result |
| --- | --- |
| List / find / grep **walk** cut short by sustained Google 429, whether or not any items were collected | `status: PARTIAL`, `partial_reason: RATE_LIMITED`. Not `EMPTY`, not `COMPLETE`, not `ErrorEnvelope` `RATE_LIMITED`. |
| Single-file read/export HTTP 429 with **no** usable prefix | `ErrorEnvelope` `category: RATE_LIMITED` |

Do not silently retry until the operation can claim `COMPLETE`.
