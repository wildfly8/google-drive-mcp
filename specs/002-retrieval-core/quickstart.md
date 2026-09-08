# Quickstart: Retrieval Core

Validates discover → read → grep against a fake Drive (no RAG, no leftover files). Access Control chain still wraps every tool.

## Prerequisites

- Access Control quickstart env (`MCP_AUTH_TOKEN`, `MCP_PRINCIPAL_ID`)
- Python 3.12, `uv`
- Fake Drive fixture with: a folder, a nested Doc containing `idempotency`, a binary file that cannot yield text

## Setup

```bash
uv sync
export MCP_AUTH_TOKEN=test-token
export MCP_PRINCIPAL_ID=deployment-1
```

## Contract tests

```bash
uv run pytest tests/contract tests/unit/retrieval -q
```

Expected:

1. `drive_ls` on a folder returns children metadata, no `content` keys
2. `drive_find` on that folder includes the nested Doc as a candidate, not evidence
3. `drive_read` returns body + `file_id` / `modified_time` / `source_url`
4. `drive_grep` pattern `idempotency` returns a match with provenance
5. Same grep twice in one process on the same fixture bytes → identical matches
6. `max_matches=1` on a file with two hits → `PARTIAL`
7. Read of the binary → `UNSUPPORTED_MIME_TYPE`, not empty success
8. After tests, no export files under `/tmp` from the app’s temp dirs
9. Unauthenticated call never hits the fake Drive

## Optional live smoke

Use a throwaway Drive. Update a Doc, `drive_read` again, confirm new text. Grep a missing phrase → `EMPTY`.

## See also

- [drive_ls.md](./contracts/drive_ls.md), [drive_find.md](./contracts/drive_find.md), [drive_read.md](./contracts/drive_read.md), [drive_grep.md](./contracts/drive_grep.md)
- [data-model.md](./data-model.md)
- Upstream [Access Control quickstart](../001-access-control/quickstart.md)
