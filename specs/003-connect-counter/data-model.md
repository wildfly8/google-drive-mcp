# Data Model: Connect Counter

Request-scoped Drive content is unchanged. This model is operational only.

## Connect

| Field | Type | Notes |
| --- | --- | --- |
| `connect_id` | string (UUID) | JWT claim `cid`. Created at authorization-code token issuance. Copied on refresh. |
| `host_family` | enum | `claude`, `chatgpt`, `other` |

## ConnectEvent

| Field | Type | Notes |
| --- | --- | --- |
| `event` | enum | `oauth_connect` or `drive_first_use` |
| `connect_id` | string | Opaque; `/stats` unique-id key; NOT a metric label |
| `host_family` | enum | Coarse host; only metric label besides the metric name |

MUST NOT include email, IP, user-agent, tokens, or `client_id`.

## ConnectStats

| Field | Type | Notes |
| --- | --- | --- |
| `oauth_connects` | int | Unique `connect_id` with `oauth_connect` in lookback |
| `drive_first_uses` | int | Unique `connect_id` with `drive_first_use` in lookback |
| `by_host_family` | map | Same two ints per family |
| `lookback` | string | `30d` |
| `source` | enum | `cloud_logging` or `process` |
| `truncated` | bool? | True if log scan hit the entry cap |
| `note` | string | Counts Connects, not people |
| `gcp` | object? | Console links: `logs_oauth_connects`, `logs_drive_first_uses`, `metrics_explorer`, `dashboards` |

## Operations series (log-based metrics)

| Metric | Log event | Label |
| --- | --- | --- |
| `onto_kb_oauth_connects` | `oauth_connect` | `host_family` |
| `onto_kb_drive_first_uses` | `drive_first_use` | `host_family` |

Dashboard display name: `onto-kb connect counter`.
