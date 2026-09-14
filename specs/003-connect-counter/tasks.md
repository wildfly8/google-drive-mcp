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
