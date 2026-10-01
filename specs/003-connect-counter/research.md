# Research: Non-PII Connect Counter

## Decision: Opaque `cid` on access and refresh JWTs

**Rationale**: First Drive use can happen on another Cloud Run instance than `/token`. The connect id must be self-contained (AC-FR-062). A server-generated UUID is not derived from IP or account.

**Alternatives considered**: Count HTTP `/token` 200s only (cannot tell refresh vs auth-code without parsing body logs; mixes probes). In-memory only (lost on scale-to-zero). Store all connect ids in GCS (new bucket and IAM).

## Decision: Cloud Logging unique `connect_id` is durable `/stats`

**Rationale**: JSON stdout becomes `jsonPayload` on Cloud Run. Unique `connect_id` for `drive_first_use` stays correct if two instances both emit. Runtime SA needs `roles/logging.viewer`. 30-day lookback matches typical retention.

**Alternatives considered**: Firestore (new service). In-process only (wrong after scale-to-zero).

## Decision: Log-based metrics + Monitoring dashboard for the GCP UI

**Rationale**: Cloud Run Metrics are only request/latency/error. The owner asked to see Connect counts in the GCP dashboard. Log-based metrics (`logging.googleapis.com/user/onto_kb_*`) turn the same `jsonPayload.event` lines into time series. A named dashboard (`onto-kb connect counter`) shows two charts grouped by `host_family`. Metric labels MUST NOT include `connect_id` (cardinality and FR-007). Entry counts can exceed `/stats` unique-id totals if two instances both emit `drive_first_use`; `/stats` stays canonical for uniques.

**Alternatives considered**: Only Logs Explorer (works, but is not a dashboard). Custom metrics written from the app (extra API on the request path). Looker Studio (out of v1).

**Apply path**: `gcloud logging metrics create|update --config-from-file` with LogMetric JSON (`metricDescriptor.labels` + `labelExtractors`). This gcloud does not accept `--label-extractors`. Metric labels remain `host_family` only. Dashboard updates MUST include the current `etag` from `gcloud monitoring dashboards describe`.

## Decision: Host family from client_id hostname, never emit client_id

**Rationale**: Claude CIMD is one shared URL for every person; logging it does not identify them but also does not help. Family (`claude` / `chatgpt` / `other`) is enough. DCR UUIDs are not emails but still omitted from events.

**Alternatives considered**: Log full client_id (rejected: FR-007). Use User-Agent (PII-adjacent and often empty).

## Decision: `/stats` is public JSON and includes console links

**Rationale**: Counts are non-PII. Console URLs (Logs Explorer, Metrics Explorer, Dashboards) help the owner without putting credentials in the payload. The links name the GCP project, and the console still requires the owner's Google sign-in.

**Alternatives considered**: Hide behind consent password (friction; password is not for this).

## Decision: `MCP_STATS_FROM_LOGS` picks the `/stats` source

**Rationale**: Local runs and tests have no log store; Cloud Run does. `1`/`true`/`yes` reads Cloud Logging, `0`/`false`/`no` uses process counts, and unset (or any other value) reads logs only when `K_SERVICE` is set. Deploy sets it to `true`. Any log failure returns process counts with source `process` and a short `log_store` reason (`auth`, `no_project`, `http_<status>`, `timeout`, `error`). The scan reads the newest 10,000 entries at most (pages of up to 1,000) and sets `truncated` when it reaches that cap.

**Alternatives considered**: Always query logs (fails locally and in tests). Silent fallback (owner cannot tell process counts from durable totals).

## Decision: With the paywall on, count only paid Connects (2026-09-27; Allow page 2026-10-01)

**Rationale**: 004 FR-008. The token endpoint re-checks the subscription before it emits `oauth_connect`, so a code refused for an inactive subscription is a failed token exchange and does not count. Since 2026-10-01 a paid Connect also needs the subscriber's Allow click on `/consent`; `MCP_OAUTH_AUTO_APPROVE` only applies without the paywall. The click alone emits nothing; only the code exchange counts.

**Alternatives considered**: Count Allow clicks (a click without a code exchange is not a finished Connect). Count `/subscribe` checkouts (payment is not a Connect, and Stripe data stays out of telemetry).

## Decision: `/setup` shows counts only without the paywall (2026-09-28)

**Rationale**: The paid setup page only helps a subscriber connect. Usage totals and console links are for the owner. With the paywall on, `/setup` shows neither, paid or not. `/stats` stays public in both modes.

**Alternatives considered**: Show counts to paid subscribers (done until 2026-09-28, then removed together with the consent-password line on the paid page).

## Decision: No GCP project id in the repo (2026-10-01)

**Rationale**: The repo is public. `scripts/ensure-connect-telemetry-gcp.sh` takes the project from `GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT` or the gcloud config and stops if none is set. Tests use a placeholder project. The running server learns its project from the environment that deploy sets or from the Cloud Run metadata server.

**Alternatives considered**: Keep a default project id in the script (published a deployment identifier).
