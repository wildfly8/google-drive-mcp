# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | Converge (2026-09-08): remaining tasks appended; next is `/speckit-implement` |
| Next command | `/speckit-implement` (Access Control T032–T036, then Retrieval T047–T049) |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md` (implemented; converge gaps open) |
| Git branch | `main` only (spec dirs are not git branches) |
| Implementation | Package in `src/google_drive_mcp/`; converge Phase 7 (AC) and Phase 8 (RC) still open |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline.

`/speckit-analyze` is **not** the next step: it is a pre-implement artifact
check. After implement, `/speckit-converge` is the spec-vs-code gate.
Re-run analyze only if spec/plan/tasks are rewritten.
