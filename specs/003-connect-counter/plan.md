# Implementation Plan: Non-PII Connect Counter

**Branch**: `main` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-connect-counter/spec.md`

## Summary

Count successful MCP OAuth Connects (authorization-code token issuance) and first authenticated `drive_*` use per Connect. Identify a Connect with an opaque `cid` JWT claim. Emit JSON operational events. Expose `GET /stats` (and a `/setup` summary). Durable totals: unique `connect_id` values in Cloud Logging over 30 days. Deploy also creates Cloud Logging **log-based metrics** and a Cloud Monitoring **dashboard** so the owner can chart the same events in the GCP UI (entry counts, `host_family` label only). No emails, IPs, user-agents, or client ids on the wire.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: existing Starlette/MCP stack; `google.auth` + `httpx` to list log entries; `gcloud logging metrics --config-from-file` + `gcloud monitoring dashboards` at deploy

**Storage**: Cloud Logging operational events (Article III exception: not Drive content). In-process sets as fallback. Log-based metrics are derived series, not a document store.

**Testing**: pytest contract tests with TestClient; unit tests for host family, first-use dedupe, metric filters, and console link shape

**Target Platform**: Cloud Run Streamable HTTP + GCP Logging/Monitoring

**Project Type**: web-service (MCP)

**Performance Goals**: `/stats` responds within a few seconds; Logging query timeout then fall back to process counts

**Constraints**: AC-FR-060/061 (no credentials in logs); FR-007 non-PII; metric labels = `host_family` only

**Scale/Scope**: tens to hundreds of Connects per 30 days

## Constitution Check

- Article III: counts are operational metrics in the existing log stream, not a document cache. Documented exception in this spec. Log-based metrics are derived from those logs.
- Article V: no new mutating Drive tools.
- Article VII: telemetry MUST NOT affect authorization decisions.
- Article XIII: host family is coarse; no Claude-only behavior in tools.
- Article XIV: MINOR. Fitness line “no hidden persistent state” remains: this is explicit, non-retrieval, owner-visible telemetry.

Gate: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/003-connect-counter/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── stats.md
└── tasks.md
```

### Source Code

```text
src/google_drive_mcp/domain/connect_telemetry.py
src/google_drive_mcp/infra/telemetry/recorder.py
src/google_drive_mcp/infra/telemetry/cloud_logging_stats.py
src/google_drive_mcp/infra/telemetry/gcp_console.py
src/google_drive_mcp/infra/mcp_auth/stats.py
deploy/connect-telemetry-gcp.json
scripts/ensure-connect-telemetry-gcp.sh
tests/unit/access_control/test_connect_telemetry.py
tests/contract/test_connect_stats.py
```
