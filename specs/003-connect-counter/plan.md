# Implementation Plan: Non-PII Connect Counter

**Branch**: `main` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-connect-counter/spec.md`

## Summary

Count successful MCP OAuth Connects (authorization-code token issuance) and first authenticated `drive_*` use per Connect. Identify a Connect with an opaque `cid` JWT claim. Emit JSON operational events. Expose `GET /stats` (and a `/setup` summary when the paywall is off). Durable totals: unique `connect_id` values in Cloud Logging over 30 days. Deploy also creates Cloud Logging **log-based metrics** and a Cloud Monitoring **dashboard** so the owner can chart the same events in the GCP UI (entry counts, `host_family` label only). No emails, IPs, user-agents, client ids, or Stripe ids in events, `/stats`, or metric labels. (The access and refresh JWTs themselves carry `client_id`, `cid` and, under the paywall, the Stripe customer id `scid`; they are signed, not encrypted.)

With the paywall on (every deployment), `exchange_authorization_code` checks the subscription first and emits `oauth_connect` only when Stripe still reports it `active` or `trialing`. A Connect then needs the subscriber's Allow click on `/consent`; `MCP_OAUTH_AUTO_APPROVE` only applies without the paywall.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: existing Starlette/MCP stack; `google.auth` + `httpx` to list log entries; `gcloud logging metrics --config-from-file` + `gcloud monitoring dashboards` at deploy

**Storage**: Cloud Logging operational events (Article III exception: not Drive content). In-process sets as fallback. Log-based metrics are derived series, not a document store.

**Testing**: pytest contract tests with TestClient; unit tests for host family, first-use dedupe, metric filters, and console link shape

**Target Platform**: Cloud Run Streamable HTTP + GCP Logging/Monitoring

**Project Type**: web-service (MCP)

**Performance Goals**: `/stats` responds within a few seconds. The log scan asks for pages of up to 1,000 entries, newest first, and stops at 10,000 entries or the last page. The HTTP client timeout is 15 s; there is no overall deadline. Any failure falls back to process counts. Nothing is cached: each `/stats` and each `/setup` GET runs a fresh scan.

**Configuration**: `MCP_STATS_FROM_LOGS` = `1`/`true`/`yes` reads Cloud Logging; `0`/`false`/`no` uses process counts only; unset (or any other value) reads Cloud Logging only on Cloud Run (`K_SERVICE` set). Project: `GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT` or `GCLOUD_PROJECT`, else the metadata server on Cloud Run; the log query also falls back to the project that Google default credentials report. Console links use the service name from `K_SERVICE` or `CLOUD_RUN_SERVICE`, default `onto-kb`. `scripts/deploy-cloud-run.sh` sets `MCP_STATS_FROM_LOGS=true` and `GOOGLE_CLOUD_PROJECT`, grants the runtime service account `roles/logging.viewer`, and runs `scripts/ensure-connect-telemetry-gcp.sh` after traffic moves to the new revision. That script takes the project from `GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT` or the gcloud config and stops if none is set. No project id is in the repo.

**Constraints**: AC-FR-060/061 (no credentials in logs); FR-007 non-PII; metric labels = `host_family` only; paid Connects only when the paywall is on (004 FR-008); `/setup` shows no counts or console links when the paywall is on

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
src/google_drive_mcp/infra/mcp_auth/setup.py        # counts only when the paywall is off
src/google_drive_mcp/infra/mcp_auth/provider.py     # cid on code exchange, oauth_connect
src/google_drive_mcp/infra/mcp_auth/tokens.py       # cid claim on access and refresh JWTs
src/google_drive_mcp/mcp/tools.py                   # drive_first_use after MCP authentication
src/google_drive_mcp/mcp/server.py                  # GET /stats and /setup routes
deploy/connect-telemetry-gcp.json
scripts/ensure-connect-telemetry-gcp.sh
scripts/deploy-cloud-run.sh                         # env, logging.viewer, runs the ensure script
tests/unit/access_control/test_connect_telemetry.py
tests/contract/test_connect_stats.py
tests/contract/test_subscription_http.py            # paid /setup hides counts; /stats has no billing fields
```
