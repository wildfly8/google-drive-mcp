# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | Specify complete (2 features); next is clarify or plan |
| Next command | `/speckit-clarify` or `/speckit-plan` (per feature) |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md` |
| Implementation | None yet |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline.
