# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | Launch hardening of the paid service (2026-10-01): cancellation proven end to end (004 T025-T030), launch-gap fixes merged (001 T049-T052, 002 T078-T080, 003 T019-T020, 004 T031-T032); deploy with `scripts/deploy-cloud-run.sh` from a clean `main` |
| Next command | `/speckit-converge` |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md`, `specs/003-connect-counter/spec.md`, `specs/004-paid-subscription/spec.md` |
| Git branch | Spec dirs are documentation ids |
| Implementation | Package in `src/google_drive_mcp/`; paywall is Stripe Checkout $20/month, bound to the browser that started it. Active subscriptions keep any connected AI chat app working; a Stripe cancellation ends access within an hour after the paid period. `/subscribe` shows the Pay button and an emailed one-time sign-in link for subscribers in another browser (Google Identity Platform); `/setup` has Manage or cancel (Stripe portal) and Sign out; each Connect needs the subscriber's Allow click. Stateless DCR, body caps and rate limits, JSON logs, CI (`.github/workflows/ci.yml`), image built from `uv.lock` as non-root. Public site: `https://wisdomspringtech.github.io/` |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline. 004 is a
MINOR paywall on that identity, not per-subscriber Google accounts.

`/speckit-analyze` is **not** the next step: it is a pre-implement artifact
check. After implement, `/speckit-converge` is the spec-vs-code gate.
Re-run analyze only if spec/plan/tasks are rewritten. Re-run converge only
after a later implement pass or a spec/plan/tasks rewrite.

## Accepted risks and open operator items (2026-10-01)

- **Accepted by the owner:** the server reads Drive with the owner's own gcloud
  login (`GOOGLE_AUTHORIZED_USER_JSON`), which also carries full Drive and
  Cloud scopes; Google refuses to narrow it. A dedicated service account was
  offered and declined. Keep that secret and project access tightly held.
- **Operator, not code:** save the Stripe customer portal settings in live mode
  (cancel at period end); terms, privacy, refund and contact pages on the
  business site; sales tax / where to sell; Stripe billing emails and failed
  payment settings; a content-rights review of `kb`; a Cloud Billing budget,
  an uptime check and alert email; GitHub branch protection requiring CI.
- **Known limits:** revocation is per instance and `/mcp` checks the JWT only
  (access ends within one access-token lifetime); the webhook only logs.
