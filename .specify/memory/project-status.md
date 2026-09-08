# SDD project status

This file is the shared pickup pointer for the next agent. Update it when the
SDD phase changes (specify / plan / tasks / implement / converge).

| Field | Value |
| --- | --- |
| Spec-Kit | Initialized (specify-cli 1.0.4, cursor-agent, bash) |
| Constitution | Ratified v1.0.0 (`.specify/memory/constitution.md`) |
| Current phase | Implement complete (2026-09-08); next is `/speckit-converge` |
| Next command | `/speckit-converge` |
| Feature specs | `specs/001-access-control/spec.md`, `specs/002-retrieval-core/spec.md` (implemented) |
| Git branch | `main` only (spec dirs are not git branches) |
| Implementation | Access Control T001–T031 and Retrieval Core T001–T046 in `src/google_drive_mcp/` |
| Pull requests | Only when the user explicitly asks |

v1 scope remains: one authenticated Google identity, read-only agentic
retrieval over Google Drive, no application-owned RAG pipeline.

Implemented: ordered auth chain, shared `RetrievalScope` / `is_within_scope`,
shared `map_google_error`, one fake Drive port, MCP tools `drive_ls` /
`drive_find` / `drive_read` / `drive_grep` behind the chain, PARTIAL completeness,
Cloud Run Dockerfile. Validate with:

```bash
uv run pytest tests/contract/test_auth_contract.py tests/unit/access_control tests/integration/test_request_isolation.py -q
uv run pytest tests/contract tests/unit/retrieval -q
```
