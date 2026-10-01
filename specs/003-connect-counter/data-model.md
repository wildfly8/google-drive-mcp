# Data Model: Connect Counter

Request-scoped Drive content is unchanged. This model is operational only.

## Connect

| Field | Type | Notes |
| --- | --- | --- |
| `connect_id` | string (UUID4) | JWT claim `cid` on access and refresh tokens. Generated when the token endpoint exchanges a code. With the paywall on, it is recorded and put in tokens only if the subscription check then passes. Copied on refresh. A token without `cid` never counts. |
| `host_family` | enum | `claude` (lowercased client id contains `claude.ai` or `anthropic.com`), `chatgpt` (`openai.com` or `chatgpt.com`), else `other` (including DCR UUIDs). Checked in that order. Not verified. |

## ConnectEvent

| Field | Type | Notes |
| --- | --- | --- |
| `severity` | string | Always `INFO` |
| `event` | enum | `oauth_connect` or `drive_first_use` |
| `connect_id` | string | Opaque; `/stats` unique-id key; NOT a metric label |
| `host_family` | enum | Coarse host; only metric label besides the metric name |

One JSON line on stdout per event; Cloud Run stores it as `jsonPayload`. These four keys are the whole event. The recorder refuses `email`, `ip`, `remoteip`, `user_agent`, `useragent`, `authorization`, `access_token`, `refresh_token`, and `client_id`. MUST NOT include tokens or Stripe ids.

`drive_first_use` is deduplicated per process. A second instance, or the same instance after a restart, can log it again for the same `connect_id`.

## ConnectStats

| Field | Type | Notes |
| --- | --- | --- |
| `oauth_connects` | int | Unique `connect_id` with `oauth_connect` in lookback |
| `drive_first_uses` | int | Unique `connect_id` with `drive_first_use` in lookback |
| `by_host_family` | map | Same two ints per family |
| `lookback` | string | Always `30d`. With source `process` the counts cover only this process's lifetime, not 30 days. |
| `source` | enum | `cloud_logging` or `process` |
| `truncated` | bool? | Present and true only if the log scan hit the 10,000-entry cap |
| `log_store` | string? | Present only when the log query was tried and failed: `auth` (no credentials or token), `no_project`, `http_<status>`, `timeout`, or `error`. `source` is then `process`. |
| `note` | string | Counts Connects, not people |
| `gcp` | object? | Present when a project is known from the environment or the Cloud Run metadata server, whatever the source. Console links: `logs_oauth_connects`, `logs_drive_first_uses`, `metrics_explorer`, `dashboards` |

## Operations series (log-based metrics)

| Metric | Log event | Label |
| --- | --- | --- |
| `onto_kb_oauth_connects` | `oauth_connect` | `host_family` |
| `onto_kb_drive_first_uses` | `drive_first_use` | `host_family` |

Both are `DELTA` `INT64` counters on `logging.googleapis.com/user/<metric>`. Filter: `resource.type="cloud_run_revision"`, `resource.labels.service_name` from `deploy/connect-telemetry-gcp.json` (`onto-kb`), and `jsonPayload.event`. Label extractor: `EXTRACT(jsonPayload.host_family)`.

Dashboard display name: `onto-kb connect counter`. Two stacked-bar charts, "OAuth Connects" and "First Drive tool uses", summed per hour and grouped by `host_family`.
