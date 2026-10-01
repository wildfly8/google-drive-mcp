# Quickstart: Connect Counter

Steps 1–7 run locally with the paywall off and `MCP_OAUTH_AUTO_APPROVE=true`, as in `tests/contract/test_connect_stats.py`. Without `K_SERVICE`, and without `MCP_STATS_FROM_LOGS` set to `1`/`true`/`yes`, `/stats` uses process counts (`source: process`).

1. `GET /stats` returns JSON with `oauth_connects` and `drive_first_uses` (zeros on a fresh process).
2. Complete auth-code + PKCE; `GET /stats` → `oauth_connects` is 1; `drive_first_uses` still 0.
3. Call `drive_ls` with the access token; `drive_first_uses` is 1. `initialize` and `tools/list` do not count.
4. Call `drive_ls` again; both counters unchanged. A bad Bearer gets 401 and counts nothing.
5. Refresh the token; `oauth_connects` unchanged. The new access token keeps the same `cid`.
6. JSON has no `client_id`, email, IP, user-agent, or Stripe id.
7. `/setup` HTML mentions the same integers and links to `/stats` (paywall off only).
8. `GET /stats` includes `gcp.dashboards` / `gcp.metrics_explorer` / log links when a cloud project is set (`GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT`, `GCLOUD_PROJECT`, or the Cloud Run metadata server).
9. With the paywall on (every deployment): an unpaid `/authorize` goes to `/subscribe` and counts nothing. A paid browser gets the Allow page on `/consent`; the count rises only when the host then exchanges the code while the subscription is active. Paid or unpaid, `/setup` shows no counts or console links; read `/stats`.
10. On Cloud Run, deploy sets `MCP_STATS_FROM_LOGS=true`, so `/stats` reports `source: cloud_logging`. If the log query fails, it reports `source: process` and a `log_store` reason.
11. After `scripts/ensure-connect-telemetry-gcp.sh` (with `GOOGLE_CLOUD_PROJECT` or `GCP_PROJECT` set, or a gcloud default project) or a full deploy, Metrics Explorer lists `logging.googleapis.com/user/onto_kb_oauth_connects` and `onto_kb_drive_first_uses`. Dashboard **onto-kb connect counter** has two charts. Charts stay empty until new `oauth_connect` / `drive_first_use` JSON logs exist after the metrics are created (browser `/authorize` hits are not Connects).
