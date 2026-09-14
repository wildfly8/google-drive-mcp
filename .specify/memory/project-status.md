# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | 003-connect-counter implemented |
| Next command | Review. Push `main` only unless the user asks for a PR. |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md`, `specs/003-connect-counter/spec.md` |
| Git branch | `main` only (spec dirs are not git branches) |
| Implementation | Package in `src/google_drive_mcp/`; connect counter is `GET /stats` plus GCP log-based metrics / dashboard **onto-kb connect counter** |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline.

`/speckit-analyze` is **not** the next step: it is a pre-implement artifact
check. After implement, `/speckit-converge` is the spec-vs-code gate.
Re-run analyze only if spec/plan/tasks are rewritten. Re-run converge only
after a later implement pass or a spec/plan/tasks rewrite.
