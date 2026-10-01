# Tasks: Non-PII Connect Counter

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

- [x] T001 Domain host-family + ConnectStats in `src/google_drive_mcp/domain/connect_telemetry.py`
- [x] T002 In-process recorder + JSON events in `src/google_drive_mcp/infra/telemetry/recorder.py`
- [x] T003 Cloud Logging unique-id snapshot in `src/google_drive_mcp/infra/telemetry/cloud_logging_stats.py`
- [x] T004 JWT `cid` on auth-code issue; copy on refresh; emit `oauth_connect`
- [x] T005 First authenticated `drive_*` emits `drive_first_use` once per `cid`
- [x] T006 `GET /stats` and `/setup` summary
- [x] T007 Grant `roles/logging.viewer` on deploy
- [x] T008 Contract tests for counters, refresh, forbidden fields
- [x] T009 Log-based metric definitions + dashboard config (`deploy/connect-telemetry-gcp.json`)
- [x] T010 `scripts/ensure-connect-telemetry-gcp.sh` creates/updates metrics and the named dashboard
- [x] T011 `/stats` and `/setup` console links (FR-011)
- [x] T012 Tests for metric filters (no PII labels) and `gcp` link shape
- [x] T013 Apply log metrics with `--config-from-file` LogMetric JSON (no `--label-extractors`; label `host_family` only)
- [x] T014 Dashboard update includes current Monitoring `etag` so re-deploy is idempotent
- [x] T015 With the paywall on, `/setup` shows no counts, `/stats` link, or console links, paid or not; `/stats` stays public with no billing fields, in `src/google_drive_mcp/infra/mcp_auth/setup.py` and `tests/contract/test_subscription_http.py` (FR-005, FR-007)
- [x] T016 With the paywall on, re-check the subscription in `exchange_authorization_code` before emitting `oauth_connect`; a refused code (`invalid_grant`) and an Allow click with no code exchange count nothing, in `src/google_drive_mcp/infra/mcp_auth/provider.py` (FR-008, 004 FR-008)
- [x] T017 `MCP_STATS_FROM_LOGS` switch (unset: logs only on Cloud Run), `log_store` fallback reason, and the 10,000-entry `truncated` cap; deploy sets `MCP_STATS_FROM_LOGS=true` and `GOOGLE_CLOUD_PROJECT` and grants `roles/logging.viewer`, in `src/google_drive_mcp/infra/telemetry/cloud_logging_stats.py`, `src/google_drive_mcp/infra/mcp_auth/stats.py`, and `scripts/deploy-cloud-run.sh` (FR-006)
- [x] T018 `scripts/ensure-connect-telemetry-gcp.sh` takes the project from `GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT` or the gcloud config and stops without one; no project id in the repo; telemetry tests use a placeholder project
- [x] T019 Contract test for paid Connect counting (`test_paid_connect_counts_once_and_a_lapsed_exchange_counts_nothing`): Allow plus code exchange counts once; a code exchanged after the subscription lapses counts nothing; an unpaid `/authorize` counts nothing (FR-008, 004 FR-008)
- [x] T020 Paid deployments: `/stats` omits console links, `/setup` skips the log scan, the scan is cached 60 s and filtered to this service, `claude.com` client ids count as Claude (FR-003, FR-011)
