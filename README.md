# Google Drive Agentic Retrieval MCP

Read-only agentic retrieval over Google Drive and Google Docs/Sheets/Slides,
served by a stateless MCP on Cloud Run, for any MCP-compatible reasoning agent.

This repository is developed with [Spec-Kit](https://github.com/github/spec-kit)
spec-driven development. Governing principles live in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) and bind
every subsequent spec, plan, task list, and implementation.

## Constitution (v2.0.0)

Google Drive is the sole source of truth. The MCP is a secure, deterministic,
ephemeral evidence-acquisition layer. The calling agent owns reasoning and the
retrieval loop. v1 is read-only, single Google identity per deployment, and
does not require an application-owned RAG index.

See the constitution for the full invariant set (Articles I–XV).

## Connecting an AI chat app

This is standard **MCP Streamable HTTP** (`POST /mcp`). The host model — not this server — parses the user question and chooses `drive_ls` / `drive_find` / `drive_read` / `drive_grep` arguments. `tools/list` advertises when to use each tool and positive/negative examples.

**Auth:** [MCP OAuth 2.1](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization) on this origin (authorization code + PKCE, dynamic client registration, protected-resource metadata). Hosts send `Authorization: Bearer <access_token>` on `POST /mcp`. **USD 20 / month** via [Stripe Checkout](https://onto-kb-kxjtmypvfa-uc.a.run.app/subscribe) is required before the first Connect. After that, any AI chat app that finished Connect keeps calling tools while Stripe reports the subscription active. To use the subscription in another browser, ask `/subscribe` for a one-time sign-in link at the Stripe receipt email (sent by Google; an email address alone never grants access). Each Connect shows an **Allow** page with the app's return address; the code is issued only after the subscriber clicks Allow in the paying browser. Cancel any time with **Manage or cancel subscription** on the setup page (Stripe's customer portal): access continues to the end of the paid period, and the AI chat app loses it within an hour after that. **Sign out of this browser** forgets the subscription on a shared computer. `MCP_AUTH_TOKEN` is still not an API key.

### Add this connector in an AI chat app

Read-only Google Drive tools. This server cannot write, delete, or share. The app may still ask you to allow read-only tools and to enable the connector in a chat. Menu names differ by app.

**Connector URL:** shown on the setup page once your subscription is active. Paid setup steps for any AI chat app are on [https://onto-kb-kxjtmypvfa-uc.a.run.app/setup](https://onto-kb-kxjtmypvfa-uc.a.run.app/setup) after payment. Subscribe: [https://onto-kb-kxjtmypvfa-uc.a.run.app/subscribe](https://onto-kb-kxjtmypvfa-uc.a.run.app/subscribe) ($20 USD/month on Stripe; this origin never shows the operator’s bank or collects card numbers).

The only folder this server may read is `kb` and its descendants. Nothing outside `kb` is listed or read, not even names or ids. Omit `folder_id` on `drive_ls`, `drive_find`, and `drive_grep` to use `kb`. A `folder_id` or `file_id` outside `kb`, or one that does not exist, is `AUTHORIZATION_ERROR`. `drive_find` asks Drive for the filename stem, so unrelated files do not fill the result cap. One `drive_read` or `drive_grep` returns at most 20 MB. A folder grep scans smaller files first; a file that does not fit is listed in `deferred_file_ids` (grep that id on its own). When the result includes `next_cursor`, call `drive_grep` again with that value in the `next_cursor` argument, the same pattern, `case_sensitive`, `regex` and scope; after a `max_matches` stop it can continue inside a file (`file_id:N`), also for `file_ids` calls. A folder grep downloads small files in parallel, so one call usually covers every small file in `kb`. A single `file_id`, including a large year export, is still searched in one call. `pattern` is at most 512 characters; with `regex=true` a pattern that is too slow stops with `PARTIAL` (`max_execution_time`) and a cursor, so simplify it.

For operators: `DRIVE_ALLOWED_FOLDER_ID` is required. The server refuses to start when it is unset, blank, or an alias such as `root`. `scripts/deploy-cloud-run.sh` pins it to the `kb` folder id kept in the Secret Manager secret `DRIVE_ALLOWED_FOLDER_ID` (not in this repo), sends all traffic to the new revision, and deletes older Cloud Run revisions that lack it, since a rollback to one of those would serve the whole Drive.

Operator checklist for a paid deploy (details in `specs/004-paid-subscription/quickstart.md`):

- Secret Manager: `MCP_AUTH_TOKEN` (at least 32 random characters, or set `MCP_OAUTH_SIGNING_KEY`; the server refuses to start otherwise), `DRIVE_ALLOWED_FOLDER_ID`, `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, the Google credential, and optionally `IDENTITY_TOOLKIT_API_KEY` for emailed sign-in links.
- Stripe Dashboard: save the **Customer portal** settings in live mode with cancellation at the end of the billing period, and turn on the portal link in customer emails. Until then **Manage or cancel subscription** answers 503.
- The deploy script refuses a working tree with uncommitted changes (`ALLOW_DIRTY=1` overrides) and runs the tests first (`SKIP_TESTS=1` skips). It deploys with 1 GiB, concurrency `CLOUD_RUN_CONCURRENCY` (default 10) and at most `CLOUD_RUN_MAX_INSTANCES` (default 3) instances, which is the cost ceiling; add a Cloud Billing budget alert as well.
- CI (`.github/workflows/ci.yml`) runs the tests, `ruff --select F,E9` and `pip-audit` on every push, and builds and checks the production image; the image is built from `uv.lock` and runs as a non-root user.
- Automatic deploys: after the `test` and `image` jobs pass on `main`, the CI `deploy` job runs `scripts/deploy-cloud-run.sh` with `ONE_TIME_SETUP=0` (no API enabling, IAM grants or dashboards). It signs in to Google Cloud through Workload Identity Federation as `onto-kb-deployer`, with no stored key, and only for this repository's `main` branch in the GitHub environment `production`. It is skipped until a project owner runs `scripts/setup-github-deploy.sh` once (Cloud Shell) and adds the `production` environment, the four Actions secrets and the `GCP_REGION` variable it prints. The environment has no required reviewer by the owner's choice, so a push to `main` that passes CI goes live; add one there to make each deploy wait for a click ([005](specs/005-delivery-pipeline/spec.md) FR-005).

Public business site for Stripe verification (free GitHub Pages): [https://wisdomspringtech.github.io/](https://wisdomspringtech.github.io/). That page has one subscribe link and does not publish the connector URL.

1. In your AI chat app, add a remote MCP connector.
2. Name: **onto-kb**. Paste the connector URL from the setup page. Transport, if asked: Streamable HTTP.
3. Authentication: **Sign in** or **OAuth**. Leave extra request headers empty. Do not paste a static token.
4. Connect. Check the app address on the **Allow** page and click Allow; your browser returns to the app. There is no deployment password.
5. If the app asks you to **Always allow** read-only tools, allow them, then enable onto-kb in a chat.

Knowing the connector URL is not enough: Connect finishes only in a browser with an active subscription, after its Allow click. Drive calls require the short-lived token that app stores after Connect. Do not put `MCP_AUTH_TOKEN` in request headers.

Answers that use onto-kb cite it in one line only, `Source: onto-kb connector`, with no separate references; the server's instructions and tool descriptions tell the AI app so. Tool results identify files with `file_id` and `source_url` as `drive:{file_id}` — not an HTTPS Drive link — so Cited Sources cannot offer a download. Document text is still returned as evidence; use `drive_read` for the body.

Any AI chat app that can add a remote MCP server uses that same URL and OAuth. Do not put tokens in the MCP URL or in tool arguments. Do not send `MCP_AUTH_TOKEN` as the `/mcp` Bearer.

Non-PII usage totals (Connect completions and first Drive tool use — not unique people): [https://onto-kb-kxjtmypvfa-uc.a.run.app/stats](https://onto-kb-kxjtmypvfa-uc.a.run.app/stats).

Operators, in the deployment's Google Cloud project: Logs Explorer with `jsonPayload.event="oauth_connect"` on the Cloud Run service, Metrics Explorer (`logging.googleapis.com/user/onto_kb_oauth_connects` and `onto_kb_drive_first_uses`), and the Monitoring dashboard **onto-kb connect counter**. `scripts/ensure-connect-telemetry-gcp.sh` prints direct links for your project. Cloud Run’s own Metrics tab is only request/latency/error.

## Spec-Driven Development

Cursor skills are installed under `.cursor/skills/`. Use them in this order:

0. `/speckit-constitution` — project principles (done: v1.0.0; amended to v2.0.0 on 2026-10-04)
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
- [Delivery pipeline](specs/005-delivery-pipeline/spec.md) — CI tests and an image build on every push; `main` deploys to Cloud Run once they pass, without a stored key

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
