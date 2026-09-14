# Quickstart: Connect Counter

1. `GET /stats` returns JSON with `oauth_connects` and `drive_first_uses` (zeros on a fresh process).
2. Complete auth-code + PKCE; `GET /stats` → `oauth_connects` is 1; `drive_first_uses` still 0.
3. Call `drive_ls` with the access token; `drive_first_uses` is 1.
4. Call `drive_ls` again; both counters unchanged.
5. Refresh the token; `oauth_connects` unchanged.
6. JSON has no `client_id`, email, IP, or user-agent.
7. `/setup` HTML mentions the same integers.
8. `GET /stats` includes `gcp.dashboards` / `gcp.metrics_explorer` / log links when a cloud project is set.
9. After `scripts/ensure-connect-telemetry-gcp.sh` (or full deploy), Metrics Explorer lists `logging.googleapis.com/user/onto_kb_oauth_connects` and `onto_kb_drive_first_uses`. Dashboard **onto-kb connect counter** has two charts. Charts stay empty until new `oauth_connect` / `drive_first_use` JSON logs exist after the metrics are created (browser `/authorize` hits are not Connects).
