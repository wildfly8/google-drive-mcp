# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | 004-paid-subscription implemented (live paywall on Cloud Run `onto-kb-00017-ks8`; every granted folder searchable; 20 MB per file) |
| Next command | `/speckit-converge` |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md`, `specs/003-connect-counter/spec.md`, `specs/004-paid-subscription/spec.md` |
| Git branch | Spec dirs are documentation ids |
| Implementation | Package in `src/google_drive_mcp/`; paywall is Stripe Checkout $20/month. Active subscriptions keep any connected AI chat app working. A passkey saved in the paying browser continues that subscription in another browser, with no receipt email and no second charge. Public site: `https://wisdomspringtech.github.io/` |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline. 004 is a
MINOR paywall on that identity, not per-subscriber Google accounts.

`/speckit-analyze` is **not** the next step: it is a pre-implement artifact
check. After implement, `/speckit-converge` is the spec-vs-code gate.
Re-run analyze only if spec/plan/tasks are rewritten. Re-run converge only
after a later implement pass or a spec/plan/tasks rewrite.
