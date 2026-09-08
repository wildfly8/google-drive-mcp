# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | Analyze remediations applied (2026-09-08); next is `/speckit-implement` |
| Next command | `/speckit-implement` (access control US1 MVP, then remaining stories / retrieval) |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md` (Ready for implementation) |
| Implementation | None yet |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline.

Analyze remediations (locked for implementers): shared `RetrievalScope.default_whole_grant` and `is_within_scope`; shared `map_google_error`; one fake Drive port; v1 `AUTHORIZATION_ERROR` only for grep folder∩file_ids after granted metadata; rate-limited walks are `PARTIAL`; `source_url` on the wire; Evidence is conceptual.
