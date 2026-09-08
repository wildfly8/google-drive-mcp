# Quickstart: Access Control Boundary

Validates the authorization chain without requiring Retrieval Core tools to be complete. Use a stub Drive adapter that records whether it was invoked.

## Prerequisites

- Python 3.12, `uv`
- Env: `MCP_AUTH_TOKEN`, `MCP_PRINCIPAL_ID`, and Google secrets (or a test double)

## Setup

```bash
uv sync
export MCP_AUTH_TOKEN=test-token
export MCP_PRINCIPAL_ID=deployment-1
```

## Contract tests (no live Google)

```bash
uv run pytest tests/contract/test_auth_contract.py tests/unit/access_control -q
```

Expected:

- No `Authorization` header → `AUTHENTICATION_ERROR`; Drive adapter call count = 0
- Bad bearer → `AUTHENTICATION_ERROR`; Drive adapter call count = 0
- Valid bearer + `file_id` outside stated `folder_id` scope → `AUTHORIZATION_ERROR`; Drive adapter call count = 0
- Valid bearer + Google double returns not-found → `FILE_NOT_FOUND`; response has no file name/content
- Logs/captured stdout contain no token substrings

## Live Google (optional)

Point `GOOGLE_*` at a throwaway account. Call any tool with a random `file_id` the account does not own → `FILE_NOT_FOUND`, not a document body.

## See also

- [authorization-chain.md](./contracts/authorization-chain.md)
- [error-taxonomy.md](./contracts/error-taxonomy.md)
- [data-model.md](./data-model.md)
