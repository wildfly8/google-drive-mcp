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

Analyze remediations (locked for implementers): shared `RetrievalScope.default_whole_grant` and `is_within_scope`; shared `map_google_error` (404/403-as-404 and single-file 429 only; walk 429 is `PARTIAL`); one fake Drive port; v1 `AUTHORIZATION_ERROR` tested on AC stub/`evaluate_chain` then replayed on `drive_grep` (T039); `source_url` on the wire; Evidence is conceptual; `content_format` defaults to the export map. Plans and leftover LOW items synced (2026-09-08).
