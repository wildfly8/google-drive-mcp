# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | Converged (2026-09-13): Retrieval Core FR-091/FR-092 tool schemas + initialize instructions advertised on MCP `tools/list` |
| Next command | Review. Deploy is required before Cloud Run `tools/list` matches this branch. Raise a PR only if the user asks. |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md` (both converged) |
| Git branch | `main` only (spec dirs are not git branches) |
| Implementation | Package in `src/google_drive_mcp/`; AC converged; RC Phase 11 T055 verified; `tasks.md` unchanged this converge |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline.

`/speckit-analyze` is **not** the next step: it is a pre-implement artifact
check. After implement, `/speckit-converge` is the spec-vs-code gate.
Re-run analyze only if spec/plan/tasks are rewritten. Re-run converge only
after a later implement pass or a spec/plan/tasks rewrite.
