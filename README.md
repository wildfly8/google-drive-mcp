# Google Drive Agentic Retrieval MCP

Read-only agentic retrieval over Google Drive and Google Docs/Sheets/Slides,
served by a stateless MCP on Cloud Run, for any MCP-compatible reasoning agent.

This repository is developed with [Spec-Kit](https://github.com/github/spec-kit)
spec-driven development. Governing principles live in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) and bind
every subsequent spec, plan, task list, and implementation.

## Constitution (ratified v1.0.0)

Google Drive is the sole source of truth. The MCP is a secure, deterministic,
ephemeral evidence-acquisition layer. The calling agent owns reasoning and the
retrieval loop. v1 is read-only, single Google identity per deployment, and
does not require an application-owned RAG index.

See the constitution for the full invariant set (Articles I–XV).

## Connecting an AI chat app

This is standard **MCP Streamable HTTP** (`POST /mcp`). The host model — not this server — parses the user question and chooses `drive_ls` / `drive_find` / `drive_read` / `drive_grep` arguments. `tools/list` advertises when to use each tool and positive/negative examples.

**Auth:** [MCP OAuth 2.1](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization) on this origin (authorization code + PKCE, dynamic client registration, protected-resource metadata). Hosts send `Authorization: Bearer <access_token>` on `POST /mcp`. **USD 20 / month** via [Stripe Checkout](https://onto-kb-kxjtmypvfa-uc.a.run.app/subscribe) is required before the first Connect. After that, any AI chat app that finished Connect keeps calling tools while Stripe reports the subscription active. No email, and no second charge. Public Cloud Run still auto-approves the OAuth consent step after a paid period. `MCP_AUTH_TOKEN` is still not an API key.

### Add this connector in an AI chat app

Read-only Google Drive tools. This server cannot write, delete, or share. The app may still ask you to allow read-only tools and to enable the connector in a chat. Menu names differ by app.

**Connector URL**

```
https://onto-kb-kxjtmypvfa-uc.a.run.app/mcp
```

Paid setup steps for any AI chat app are on [https://onto-kb-kxjtmypvfa-uc.a.run.app/setup](https://onto-kb-kxjtmypvfa-uc.a.run.app/setup) after payment. Subscribe: [https://onto-kb-kxjtmypvfa-uc.a.run.app/subscribe](https://onto-kb-kxjtmypvfa-uc.a.run.app/subscribe) ($20 USD/month on Stripe; this origin never shows the operator’s bank or collects card numbers).

A call that omits `folder_id` searches the whole Google grant. No folder is disallowed. `drive_ls` of an omitted folder lists My Drive root children; `drive_find` and `drive_grep` search every granted folder. One `drive_read` or `drive_grep` returns at most 20 MB, so a large year file is one `file_id` per call.

Public business site for Stripe verification (free GitHub Pages): [https://wisdomspringtech.github.io/](https://wisdomspringtech.github.io/). That page has one subscribe link and does not publish the connector URL.

1. In your AI chat app, add a remote MCP connector.
2. Name: **onto-kb**. Paste the URL above. Transport, if asked: Streamable HTTP.
3. Authentication: **Sign in** or **OAuth**. Leave extra request headers empty. Do not paste a static token.
4. Connect. Your browser returns to the app. There is no deployment password.
5. If the app asks you to **Always allow** read-only tools, allow them, then enable onto-kb in a chat.

Knowing the connector URL is enough to finish OAuth. Drive calls still require the short-lived token that app stores after Connect. Do not put `MCP_AUTH_TOKEN` in request headers.

Tool results identify files with `file_id` and `source_url` as `drive:{file_id}` — not an HTTPS Drive link — so Cited Sources cannot offer a download. Document text is still returned as evidence; use `drive_read` for the body.

Any AI chat app that can add a remote MCP server uses that same URL and OAuth. Do not put tokens in the MCP URL or in tool arguments. Do not send `MCP_AUTH_TOKEN` as the `/mcp` Bearer.

Non-PII usage totals (Connect completions and first Drive tool use — not unique people): [https://onto-kb-kxjtmypvfa-uc.a.run.app/stats](https://onto-kb-kxjtmypvfa-uc.a.run.app/stats). The same numbers appear on `/setup`.

In GCP: [Logs (oauth_connect)](https://console.cloud.google.com/logs/query;query=resource.type%3D%22cloud_run_revision%22%0Aresource.labels.service_name%3D%22onto-kb%22%0AjsonPayload.event%3D%22oauth_connect%22;project=project-84207120-95a7-43ac-95e), [Metrics Explorer](https://console.cloud.google.com/monitoring/metrics-explorer?project=project-84207120-95a7-43ac-95e) (`logging.googleapis.com/user/onto_kb_oauth_connects` and `onto_kb_drive_first_uses`), and dashboard **onto-kb connect counter** under [Monitoring dashboards](https://console.cloud.google.com/monitoring/dashboards?project=project-84207120-95a7-43ac-95e). Cloud Run’s own Metrics tab is only request/latency/error.

## Spec-Driven Development

Cursor skills are installed under `.cursor/skills/`. Use them in this order:

0. `/speckit-constitution` — project principles (done: v1.0.0)
1. `/speckit-specify` — what to build (done: access control + retrieval core + connect counter)
2. `/speckit-clarify` — optional; de-risk underspecified areas (done: session 2026-09-08)
3. `/speckit-plan` — how to build it (done: access control + retrieval core + connect counter)
4. `/speckit-tasks` — actionable implementation tasks (done: access control, retrieval core, connect counter)
5. `/speckit-analyze` — optional; cross-artifact consistency (done: 2026-09-08; remediations and plan sync applied)
6. `/speckit-implement` — execute the tasks
7. `/speckit-converge` — compare the codebase to spec/plan/tasks and append remaining work

Feature specs (ready for implementation):

- [Access Control Boundary](specs/001-access-control/spec.md) — who may act, and on what authority
- [Retrieval Core](specs/002-retrieval-core/spec.md) — discover, read, exact-search once a call is cleared
- [Non-PII Connect Counter](specs/003-connect-counter/spec.md) — Connect and first Drive-use counts on `/stats` and the GCP dashboard **onto-kb connect counter**
- [Mandatory paid subscription](specs/004-paid-subscription/spec.md) — $20 USD/month Stripe Checkout before MCP Connect

Repeat implement and converge until converge reports **Converged**.

The Specify CLI (`specify-cli` 1.0.4) initialized this project with the
`cursor-agent` integration and bash scripts. Refresh managed files with
`specify integration upgrade` after upgrading the CLI.

Shared pickup state for the next Cloud Agent:

- `.specify/memory/project-status.md` — current SDD phase
- `.cursor/rules/spec-kit-sdd.mdc` — always-on constitution and next-step rules
- `.cursor/environment.json` — installs `uv` and `specify-cli` on Cloud Agent boot

## Out of v1 scope

Multi-tenant access, write capability, persistent caches, and
semantic/vector retrieval are MAJOR constitutional changes (Article XIV)
and MUST be specified before any implementation work.
