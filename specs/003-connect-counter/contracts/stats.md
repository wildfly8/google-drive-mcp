# Contract: `GET /stats`

Unauthenticated. Non-PII connect totals for this origin. Always HTTP 200 with JSON, with or without the paywall.

## Output

```json
{
  "type": "object",
  "required": ["oauth_connects", "drive_first_uses", "by_host_family", "lookback", "source", "note"],
  "properties": {
    "oauth_connects": { "type": "integer", "minimum": 0 },
    "drive_first_uses": { "type": "integer", "minimum": 0 },
    "by_host_family": {
      "type": "object",
      "propertyNames": { "enum": ["claude", "chatgpt", "other"] },
      "additionalProperties": {
        "type": "object",
        "required": ["oauth_connects", "drive_first_uses"],
        "properties": {
          "oauth_connects": { "type": "integer", "minimum": 0 },
          "drive_first_uses": { "type": "integer", "minimum": 0 }
        }
      }
    },
    "lookback": { "const": "30d" },
    "source": { "enum": ["cloud_logging", "process"] },
    "truncated": { "const": true },
    "note": { "type": "string" },
    "log_store": { "type": "string", "description": "auth | no_project | http_<status> | timeout | error" },
    "gcp": {
      "type": "object",
      "required": ["logs_oauth_connects", "logs_drive_first_uses", "metrics_explorer", "dashboards"],
      "properties": {
        "logs_oauth_connects": { "type": "string", "format": "uri" },
        "logs_drive_first_uses": { "type": "string", "format": "uri" },
        "metrics_explorer": { "type": "string", "format": "uri" },
        "dashboards": { "type": "string", "format": "uri" }
      }
    }
  }
}
```

`by_host_family` lists only families seen in the lookback (with source `process`, since this process started; `lookback` still reads `30d`). `truncated` is present only when the log scan hit its 10,000-entry cap. `log_store` is present only when the log query was tried and failed; `source` is then `process`.

## Source

- `MCP_STATS_FROM_LOGS` = `1`/`true`/`yes`: count unique `connect_id` values in Cloud Logging entries with `resource.type="cloud_run_revision"` and `jsonPayload.event` of `oauth_connect` or `drive_first_use` over the last 30 days, newest first, at most 10,000 entries. The filter does not name the Cloud Run service. The project comes from the environment, the Cloud Run metadata server, or Google default credentials. On success `source` is `cloud_logging`; on failure see `log_store`.
- `0`/`false`/`no`: in-process counts only. `source` is `process`.
- Unset or any other value: Cloud Logging on Cloud Run (`K_SERVICE` set), else process counts.
- `gcp` is present when a project is known (`GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT`, `GCLOUD_PROJECT`, or the Cloud Run metadata server), whatever the source. Log links filter on the Cloud Run service name (`K_SERVICE`, else `CLOUD_RUN_SERVICE`, else `onto-kb`).

## Forbidden

Forbidden response/event keys: `email`, `ip`, `remoteIp`, `user_agent`, `userAgent`, `authorization`, `access_token`, `refresh_token`, `client_id`. The response and events also carry no Stripe customer or subscription ids. An event has exactly `severity`, `event`, `connect_id`, `host_family`.

## Related behaviour

`GET /setup` with the paywall off MAY embed the same integers in HTML and link to `/stats`, the dashboards list, Metrics Explorer, and the Connect logs. It MUST NOT add personal fields. With the paywall on, `/setup` shows no counts and no console links, paid or not.

Token refresh (`grant_type=refresh_token`) MUST NOT emit `oauth_connect`. With the paywall on, a code exchange refused for an inactive subscription (`invalid_grant`) MUST NOT emit it either.

`drive_first_use` is emitted on the first `drive_*` call per `cid` that passes MCP authentication and reaches the tool handler, before the server's own argument checks and Access Control. A call the MCP layer rejects against the tool's input schema (wrong type or id pattern) does not emit it.

Operations time-series (deploy-time): log-based metrics `onto_kb_oauth_connects` and `onto_kb_drive_first_uses` with label `host_family` only. Dashboard display name `onto-kb connect counter`.
