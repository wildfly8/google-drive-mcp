# Contract: `GET /stats`

Unauthenticated. Non-PII connect totals for this origin.

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
    "truncated": { "type": "boolean" },
    "note": { "type": "string" },
    "log_store": { "type": "string" },
    "gcp": {
      "type": "object",
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

Forbidden response/event keys: `email`, `ip`, `remoteIp`, `user_agent`, `userAgent`, `authorization`, `access_token`, `client_id`.

`GET /setup` MAY embed the same integers in HTML and MAY link to the operations dashboard. It MUST NOT add personal fields.

Token refresh (`grant_type=refresh_token`) MUST NOT emit `oauth_connect`.

Operations time-series (deploy-time): log-based metrics `onto_kb_oauth_connects` and `onto_kb_drive_first_uses` with label `host_family` only. Dashboard display name `onto-kb connect counter`.
