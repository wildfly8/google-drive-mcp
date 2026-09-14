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

**Rationale**: Counts are non-PII. Console URLs (Logs Explorer, Metrics Explorer, Dashboards) help the owner without putting credentials in the payload.

**Alternatives considered**: Hide behind consent password (friction; password is not for this).
