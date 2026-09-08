# Contract: Result status (all retrieval tools)

Every tool result includes:

| `status` | Meaning |
| --- | --- |
| `COMPLETE` | Finished within budgets; no reason to believe more matching work remained |
| `PARTIAL` | A budget or sustained rate-limit could plausibly have found more |
| `EMPTY` | Finished complete coverage with zero children/hits (not an error) |
| `ERROR` | Failed; see `category` from Access Control / this context |

`PARTIAL` MUST include `partial_reason`. Truncation MUST NOT be reported as `COMPLETE` or `EMPTY`.
