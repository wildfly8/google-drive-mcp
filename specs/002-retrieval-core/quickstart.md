# Quickstart: Retrieval Core

Validates discover → read → grep against the shared fake Drive (no RAG, no leftover files). Access Control chain still wraps every tool.

## Prerequisites

- Access Control quickstart env (`MCP_AUTH_TOKEN`, `MCP_PRINCIPAL_ID`)
- Python 3.12, `uv`
- Shared fixture `tests/fakes/fake_drive.py` with: a folder, a nested Doc containing `idempotency`, a binary file that cannot yield text

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

1. `tools/list` returns four tools with non-empty when-to-use / when-not / do / don't descriptions and schema bounds (`tests/contract/test_tool_schemas.py`)
2. `drive_ls` on a folder returns children metadata including `source_url`, no `content` keys
3. `drive_find` on that folder includes the nested Doc as a candidate, not evidence
4. `drive_read` returns body + `file_id` / `modified_time` / `source_url` (no match fields required)
5. `drive_grep` pattern `idempotency` returns a match with provenance including `matched_text` and `location`
6. Same grep twice in one process on the same fixture bytes → identical matches
7. `max_matches=1` on a file with two hits → `PARTIAL`
8. Read of the binary by id → `UNSUPPORTED_MIME_TYPE`, not empty success
9. Folder grep with mixed supported + binary → `PARTIAL` (unsupported skipped); grep of binary by id alone → classified error
10. After tests, no export files under `/tmp` from the app’s temp dirs
11. Unauthenticated call never hits fake Drive **content** I/O (`tests/contract/test_tools_require_auth.py`)
12. Walk cut by simulated 429 → `status: PARTIAL`, `partial_reason: RATE_LIMITED`

## Optional live smoke

Use a throwaway Drive. Update a Doc, `drive_read` again, confirm new text. Grep a missing phrase → `EMPTY`.

## See also

- [drive_ls.md](./contracts/drive_ls.md), [drive_find.md](./contracts/drive_find.md), [drive_read.md](./contracts/drive_read.md), [drive_grep.md](./contracts/drive_grep.md)
- [result-status.md](./contracts/result-status.md), [error-taxonomy.md](./error-taxonomy.md)
- [data-model.md](./data-model.md)
- Upstream [Access Control quickstart](../001-access-control/quickstart.md)
