# Feature Specification: Non-PII Connect Counter

**Branch**: `main`

**Spec directory**: `specs/003-connect-counter`

**Created**: 2026-09-14

**Status**: Implemented

**Input**: User description: "Add a non-PII connect counter for successful OAuth Connect completions and first Drive tool use per connect. Do not identify public people." Follow-up: show the same counters on the cloud operations dashboard, not only `/stats`.

**Constitution**: Ratified v1.0.0. MINOR (Article XIV): operational telemetry only. Does not change Drive as source of truth, read-only tools, or MCP auth. Counts are not document content (Article III exception: operational metrics in the same log stream already used for `chain` / `retrieval`, not a retrieval cache).

**Bounded Context**: Connect telemetry (downstream of Access Control; does not authorize)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See how many successful Connects happened (Priority: P1)

The deployment owner wants to know how many times a host (Claude, ChatGPT, or other) **finished OAuth** against this public MCP — a successful Connect — without learning who those people are.

**Why this priority**: This is the asked-for “how many users connected successfully” signal. A Connect is a completed authorization-code token exchange, not a probe of `/authorize` and not a token refresh.

**Independent Test**: Complete OAuth (auth-code + PKCE) once, then read the counter. It increases by one. Refresh the access token; the Connect counter does not increase. A second new Connect increases it again.

**Acceptance Scenarios**:

1. **Given** a host completes authorization-code + PKCE and receives an access token, **When** the owner reads the counter, **Then** `oauth_connects` is one higher than before that Connect.
2. **Given** the same Connect later refreshes its token, **When** the owner reads the counter, **Then** `oauth_connects` is unchanged.
3. **Given** `/authorize` is hit by a metadata probe that never exchanges a code, **When** the owner reads the counter, **Then** `oauth_connects` is unchanged.

---

### User Story 2 - See how many Connects actually used Drive tools (Priority: P1)

A Connect that never calls `drive_*` is only a linked connector. The owner also wants a count of Connects whose first authenticated Drive tool call occurred.

**Why this priority**: Distinguishes “clicked Connect” from “used the library.”

**Independent Test**: Connect, then call `drive_ls` (or any `drive_*`) once. `drive_first_uses` increases by one. A second `drive_*` on the same Connect does not increase it. `tools/list` / `initialize` do not increase it.

**Acceptance Scenarios**:

1. **Given** a Connect that has not yet called a Drive tool, **When** an authenticated `drive_*` call is accepted past MCP authentication, **Then** `drive_first_uses` increases by one.
2. **Given** that same Connect, **When** further `drive_*` calls occur, **Then** `drive_first_uses` is unchanged.
3. **Given** an unauthenticated or invalid Bearer `drive_*` attempt, **When** the call fails authentication, **Then** neither counter increases.

---

### User Story 3 - Read counts without personal data (Priority: P2)

The owner can read totals (and a coarse host family such as Claude vs ChatGPT vs other) from this origin. The payload must not include emails, names, account ids, IP addresses, user-agents, tokens, or other personal identifiers.

**Why this priority**: The constraint that made a people-directory impossible; the counter must stay non-PII.

**Independent Test**: Inspect the public stats representation and the telemetry events. No email, IP, user-agent, Bearer, or host client id appears.

**Acceptance Scenarios**:

1. **Given** stats are requested, **When** the JSON (or setup summary) is returned, **Then** it contains only counts, host-family rollups, lookback, a source label, and optional console links.
2. **Given** telemetry is emitted, **When** an event is inspected, **Then** it may include an opaque connect id and host family, and MUST NOT include email, IP, user-agent, or credentials.

---

### User Story 4 - See the same counters on the operations console (Priority: P2)

The owner wants charts in the cloud operations console (not only `GET /stats`): Connects over time and first Drive uses over time, split by host family. Those charts must not introduce personal labels.

**Why this priority**: The owner asked to view the counter inside the cloud dashboard. Totals on `/stats` remain the unique-connect source of truth; the dashboard is the time-series view of the same events.

**Independent Test**: After deploy, open the named operations dashboard for this connector. Two charts exist (Connects, first Drive uses). Their series can be grouped by host family. No email, IP, or account label is present.

**Acceptance Scenarios**:

1. **Given** the connector is deployed, **When** the owner opens the operations dashboard named for this connector, **Then** they see a Connects chart and a first-Drive-use chart without calling `/stats`.
2. **Given** a new Connect is logged, **When** the owner waits for the operations pipeline to ingest the event, **Then** the Connects chart can show that increment (entry count of Connect events; not a person id).
3. **Given** the dashboard and `/stats` JSON, **When** either is inspected, **Then** neither exposes email, IP, user-agent, or raw client ids.

---

### Edge Cases

- Tokens minted before this feature have no connect id: Drive calls MUST NOT invent a Connect or inflate `drive_first_uses`.
- Two Cloud Run instances handling the same Connect: first-use MUST still count as one Connect once events are aggregated by opaque connect id (`/stats`).
- Stats lookup failure (log store unreachable): still return in-process counts and say they are not the durable source.
- ReConnect by the same person: two Connects. The product counts Connects, not people.
- Operations-console charts count event lines, not unique connect ids. Duplicate first-use lines from two instances can make a chart slightly higher than `/stats`. `/stats` remains the unique-id total.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: MUST increment `oauth_connects` exactly once per successful authorization-code token issuance (Connect). Token refresh MUST NOT increment it.
- **FR-002**: MUST increment `drive_first_uses` at most once per Connect, on the first `drive_*` call that passes MCP authentication. `initialize` and `tools/list` MUST NOT increment it.
- **FR-003**: MUST attribute counts to a coarse `host_family` of `claude`, `chatgpt`, or `other` derived from the OAuth client identifier’s host, without storing or returning that raw client identifier on stats or telemetry events.
- **FR-004**: MUST identify a Connect only by an opaque, server-generated connect id that is not derived from IP, email, or account. That id MAY travel in the access/refresh token so first-use can be correlated. It is not a person id.
- **FR-005**: MUST expose current totals on `GET /stats` as JSON without authentication (counts are non-PII). `GET /setup` MAY show the same totals in prose.
- **FR-006**: Durable totals MUST survive instance restart by aggregating operational telemetry already retained in the platform log store (unique connect ids). In-process counts are a fallback, not the owner’s source of truth on Cloud Run.
- **FR-007**: Telemetry, stats, operations series, and dashboard labels MUST NOT record or return email, name, account id, IP address, user-agent, MCP or Google credentials, authorization codes, raw OAuth client ids, or connect ids as metric labels.
- **FR-008**: Failed `/authorize` probes and failed token exchanges MUST NOT increment `oauth_connects`.
- **FR-009**: Deploy MUST publish the same two counters as operations time-series (Connects and first Drive uses), groupable by `host_family` only.
- **FR-010**: The owner MUST be able to open a named operations dashboard for this connector that shows those two charts, without using `GET /stats`.
- **FR-011**: `GET /stats` MUST include console links to the log view, metrics explorer, and dashboards list when a cloud project is configured. Links MUST NOT include credentials.

### Key Entities

- **Connect**: One successful authorization-code token issuance. Opaque `connect_id`. Not a person.
- **Host family**: `claude` | `chatgpt` | `other`.
- **ConnectStats**: `oauth_connects`, `drive_first_uses`, per-family rollups, lookback window, source (`cloud_logging` | `process`), optional console links.
- **Operations series**: Time-series of the same two events for the operations console (entry counts, host family only).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After one real Connect and one authenticated Drive tool call, the owner can read `oauth_connects >= 1` and `drive_first_uses >= 1` from this origin within one minute without opening a log console.
- **SC-002**: A reviewer scanning stats JSON, telemetry events, and operations-chart labels finds zero email addresses, IP addresses, user-agents, or Bearer tokens.
- **SC-003**: Refreshing a token 10 times does not increase `oauth_connects`.
- **SC-004**: The owner can tell Claude Connects apart from ChatGPT/other Connects at family granularity, not as individual people.
- **SC-005**: After deploy, the owner can open the named operations dashboard and see Connect and first-Drive-use charts without using `/stats`.

## Assumptions

- “Users connected successfully” means completed OAuth Connects, not unique humans (this origin never receives a Claude/ChatGPT account).
- Platform log retention (default Cloud Logging) is the durability window; v1 lookback is 30 days.
- Existing MCP OAuth 2.1 and mixed-auth `initialize` / `tools/list` behavior is unchanged.
- Public `/stats` is acceptable because it contains only counts.
- The operations dashboard is for the deployment owner in the cloud console; it is not a public page.
