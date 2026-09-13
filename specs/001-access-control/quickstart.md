# Quickstart: Access Control Boundary

Validates the authorization chain without requiring Retrieval Core tools to be complete. Use the shared fake Drive port (`tests/fakes/fake_drive.py`) that records metadata vs content invocations.

## Prerequisites

- Python 3.12, `uv`
- Env: `MCP_AUTH_TOKEN` (consent password), `MCP_PUBLIC_URL`, `MCP_PRINCIPAL_ID`, and Google secrets (or a test double)

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
uv run pytest tests/contract/test_auth_contract.py tests/unit/access_control tests/integration/test_request_isolation.py -q
```

Expected:

- No `Authorization` header → HTTP 401 on `/mcp`, or `AUTHENTICATION_ERROR` in-process; Drive metadata and content counts = 0
- `Authorization: Bearer $MCP_AUTH_TOKEN` (static secret) → 401 / `AUTHENTICATION_ERROR`; Drive metadata and content counts = 0
- Valid OAuth access token + Google double returns not-found → `FILE_NOT_FOUND`; response has no file name/content
- Valid access token + stub/`evaluate_chain` with `folder_id` and a granted `file_id` **outside** that folder → `AUTHORIZATION_ERROR`; content (export/`get_media`) count = 0; metadata `files.get` may be 1
- Valid access token + `file_id`-only call that Google misses → `FILE_NOT_FOUND`, never `AUTHORIZATION_ERROR`
- Logs/captured stdout contain no token substrings

## Live Google (optional)

Point `GOOGLE_*` at a throwaway account. Call any tool with a random `file_id` the account does not own → `FILE_NOT_FOUND`, not a document body.

## See also

- [authorization-chain.md](./contracts/authorization-chain.md)
- [error-taxonomy.md](./contracts/error-taxonomy.md)
- [data-model.md](./data-model.md)
