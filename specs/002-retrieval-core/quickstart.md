# Quickstart: Retrieval Core

Validates discover → read → grep against the shared fake Drive (no RAG, no leftover files). Access Control chain still wraps every tool.

## Prerequisites

- Access Control quickstart env (`MCP_AUTH_TOKEN` consent password, `MCP_PUBLIC_URL`, `MCP_PRINCIPAL_ID`; a running server also needs `DRIVE_ALLOWED_FOLDER_ID`)
- Python 3.12, `uv`
- Shared fixture `tests/fakes/fake_drive.py` with: a folder, a nested Doc containing `idempotency`, a binary file that cannot yield text

## Setup

```bash
uv sync
export MCP_AUTH_TOKEN=test-token
export MCP_PRINCIPAL_ID=deployment-1
export MCP_PUBLIC_URL=http://127.0.0.1
export MCP_OAUTH_AUTO_APPROVE=true
```

`MCP_OAUTH_AUTO_APPROVE` only applies without the paywall. With `MCP_SUBSCRIPTION_REQUIRED=true` every Connect needs an active subscription and a click on the Allow page, whatever it is set to. Most tests build settings with `Settings.for_tests()` rather than from these variables.

## Contract tests

```bash
uv run pytest tests/contract tests/unit/retrieval -q
```

Expected:

1. `tools/list` returns four tools with non-empty when-to-use / when-not / do / don't descriptions and schema bounds (`tests/contract/test_tool_schemas.py`)
2. `drive_ls` on a folder returns children metadata (no link or locator, no `source_url`), no `content` keys
3. `drive_find` on that folder includes the nested Doc as a candidate, not evidence
4. `drive_read` returns body + `file_id` / `file_name` / `modified_time` (no `source_url`; no match fields required)
5. `drive_grep` pattern `idempotency` returns a match with provenance including `matched_text` and `location`
6. Same grep twice in one process on the same fixture bytes → identical matches
7. `max_matches=1` on a file with two hits → `PARTIAL`
8. Read of the binary by id → `UNSUPPORTED_MIME_TYPE`, not empty success
9. Folder grep with mixed supported + binary → `PARTIAL` (unsupported skipped); grep of binary by id alone → classified error
10. After tests, no export files under `/tmp` from the app’s temp dirs
11. Unauthenticated call never hits fake Drive **content** I/O (`tests/contract/test_tools_require_auth.py`)
12. Walk cut by simulated 429 → `status: PARTIAL`, `partial_reason: RATE_LIMITED`
13. `drive_find` with a filename stem among many non-matching siblings returns that file and does not `files.get` each child (`tests/contract/test_drive_find.py`)
14. Folder `drive_grep` scans a small file, returns a larger id in `deferred_file_ids`, and resumes with `cursor` (`tests/contract/test_drive_grep.py`)
15. Omitted `drive_ls` lists the allow-list folder, never My Drive root; an id outside that folder and a missing id get the same `AUTHORIZATION_ERROR`; an argument the tool does not take is `INVALID_ARGUMENT`; no allow-list refuses every call (`tests/contract/test_allowed_folder.py`)
16. Several hits on one line are one match with `location.occurrences`; a folder `drive_grep` scans more than 40 files in one call and stops at 200 with `next_cursor` (`tests/contract/test_drive_grep.py`)
17. A `max_matches` stop returns `file_id:N` inside a file and resumes there, also with `file_ids`; exactly `max_matches` with nothing left is `COMPLETE` (unless unsupported files were skipped); download-ahead returns the same matches as a one-file scan and never downloads a deferred file; a slow download past the time cap and a download 429 both return a cursor (`tests/contract/test_drive_grep.py`)
18. `drive_find` returns matching folders without counting them against `max_results` (`tests/contract/test_drive_find.py`)
19. A `drive_ls` page with more children left is `PARTIAL` (`partial_reason: pagination`) with `next_page_token`; a non-integer `page_token` is `INVALID_ARGUMENT` (`tests/contract/test_partial_status.py`, `tests/contract/test_invalid_argument.py`)
20. The allow-list check makes the same Drive calls for an id outside the folder, a missing id and an ungranted id; startup refuses an allow-list id that Drive cannot read or reports as a file, a Drive root or trashed (`tests/contract/test_allowed_folder.py`)

## Optional live smoke

Use a throwaway Drive and set `DRIVE_ALLOWED_FOLDER_ID` to a test folder in it. Update a Doc in that folder, `drive_read` again, confirm new text. Grep a missing phrase → `EMPTY`.

## See also

- [drive_ls.md](./contracts/drive_ls.md), [drive_find.md](./contracts/drive_find.md), [drive_read.md](./contracts/drive_read.md), [drive_grep.md](./contracts/drive_grep.md)
- [result-status.md](./contracts/result-status.md), [error-taxonomy.md](./contracts/error-taxonomy.md)
- [data-model.md](./data-model.md)
- Upstream [Access Control quickstart](../001-access-control/quickstart.md)
