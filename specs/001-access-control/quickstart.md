# Quickstart: Access Control Boundary

Validates the authorization chain without requiring Retrieval Core tools to be complete. Use the shared fake Drive port (`tests/fakes/fake_drive.py`) that records metadata, subfolder-listing, and content invocations separately.

## Prerequisites

- Python 3.12, `uv`
- Env: `MCP_AUTH_TOKEN` (consent password), `MCP_PUBLIC_URL`, `MCP_PRINCIPAL_ID`, and Google secrets (or a test double)
- A running server also needs `DRIVE_ALLOWED_FOLDER_ID` (the only readable folder, `kb` on this deployment). It refuses to start without it, and also when Drive reports that id as a file, a trashed folder, a Drive root, or unreadable. Contract tests use `Settings.for_tests()`, which sets it for the fake Drive, turns auto-approve on, and leaves the paywall off.

## Setup

```bash
uv sync
export MCP_AUTH_TOKEN=test-token
export MCP_PRINCIPAL_ID=deployment-1
export MCP_PUBLIC_URL=http://127.0.0.1
export MCP_OAUTH_AUTO_APPROVE=true
```

## Contract tests (no live Google)

```bash
uv run pytest tests/contract/test_auth_contract.py tests/contract/test_allowed_folder.py \
  tests/contract/test_oauth_http.py tests/contract/test_streamable_http_auth.py \
  tests/contract/test_tools_require_auth.py tests/unit/access_control \
  tests/integration/test_request_isolation.py -q
# Paid Connect Allow page (tests owned by 004):
uv run pytest tests/contract/test_subscription_http.py -q -k "allow or connect or authorize"
```

Expected:

- No `Authorization` header → HTTP 401 + `WWW-Authenticate` (`resource_metadata`) on a `drive_*` `tools/call`, or `AUTHENTICATION_ERROR` in-process; Drive metadata and content counts = 0. `initialize` and `tools/list` work without a Bearer; `GET /mcp` is 405
- `Authorization: Bearer $MCP_AUTH_TOKEN` (static secret) → 401 / `AUTHENTICATION_ERROR`; Drive metadata and content counts = 0
- Valid OAuth access token + Google double returns not-found → `AUTHORIZATION_ERROR`; response has no file name/content
- Valid access token + stub/`evaluate_chain` with `folder_id` and a granted `file_id` **outside** that folder → `AUTHORIZATION_ERROR`; content (export/`get_media`) count = 0; one metadata `files.get` per named id (the folder and the file) after the allow-list tree listing
- Valid access token + an id that Google misses, an id Google does not grant, and an id outside the allow-list folder → the same `AUTHORIZATION_ERROR` after the same Drive calls (the allow-list tree listing, then one metadata get). No folder outside the allow-list folder is listed or looked up. `FILE_NOT_FOUND` only when an id proven inside that folder then misses
- No allow-list folder → every call is `AUTHORIZATION_ERROR` before any Google call
- An argument key the tool does not take → `INVALID_ARGUMENT` before the chain, with no listing or content I/O
- DCR + PKCE (and ChatGPT / Claude CIMD) issue an access token; `tools/list` returns exactly `drive_ls`, `drive_find`, `drive_read`, `drive_grep`. With auto-approve off and no paywall, `/consent` asks for `MCP_AUTH_TOKEN`; a wrong password is HTTP 400
- Paywall on: unpaid `/authorize` → `/subscribe`; entitled `/authorize` → `/consent` Allow page (no password, not frameable, unknown return host flagged); `POST /consent` with no cookie, another subscriber’s cookie, or a lapsed subscription → HTTP 400 and no code
- Logs/captured stdout contain no token substrings

## Live Google (optional)

Point `GOOGLE_*` at a throwaway account and `DRIVE_ALLOWED_FOLDER_ID` at a test folder (a placeholder such as `<test-folder-id>`; never commit a real id). Call any tool with a random `file_id`, or one outside that folder → `AUTHORIZATION_ERROR`, not a document body.

## See also

- [authorization-chain.md](./contracts/authorization-chain.md)
- [error-taxonomy.md](./contracts/error-taxonomy.md)
- [data-model.md](./data-model.md)
