# Data Model: Access Control Boundary

All **Drive** objects below are request-scoped. MCP OAuth access/refresh/authorization-code values are self-contained JWTs (not Drive documents). DCR client records are in-memory protocol state (Article III exception).

## Principal

| Field | Type | Rules |
| --- | --- | --- |
| `id` | string | Non-secret deployment/identity label (`MCP_PRINCIPAL_ID`). Never a raw token. |
| `kind` | enum | `deployment_google_identity` in v1 |

v1: exactly one Principal per deployment. A valid MCP OAuth access token proves the caller may act *as* this principal; it does not select among Google users.

## McpAccessToken

| Field | Type | Rules |
| --- | --- | --- |
| `scheme` | enum | `mcp_oauth21_jwt` in v1 |
| `token` | secret string | HS256 JWT issued by this origin; `aud` / resource = `{issuer}/mcp`; scope `drive.read` |
| `client_id` | string | DCR client that received the token |

Presented as `Authorization: Bearer` on `/mcp`. Never a Google token. Never a tool argument. Tests may mint with the deployment signing key; production hosts obtain it via auth-code + PKCE.

## ConsentPassword

| Field | Type | Rules |
| --- | --- | --- |
| `value` | secret string | Env `MCP_AUTH_TOKEN`. HMAC-compared only on `POST /consent` |

MUST NOT verify as `McpAccessToken`. Used to derive the JWT HMAC key unless `MCP_OAUTH_SIGNING_KEY` is set.

## RegisteredClient

| Field | Type | Rules |
| --- | --- | --- |
| `client_id` | string | RFC 7591 |
| `redirect_uris` | string[] | Validated by the MCP SDK |

Stored in process memory only. Discarded when the instance disappears. Hosts re-register.

## Credential

| Field | Type | Rules |
| --- | --- | --- |
| `scheme` | enum | `google_oauth_refresh` in v1 |
| `access_token` | secret string | Google access token; in-memory only for the request; never in logs, errors, or tool results |
| `scope` | string | Must be read-only Drive (`drive.readonly`) on the three-field refresh mint |

The agent never receives this object. Adapter maps env secrets (`GOOGLE_*` or authorized-user JSON) → Credential. Distinct from `McpAccessToken`.

## Grant

| Field | Type | Rules |
| --- | --- | --- |
| `oauth_scope` | string | Narrowest practical: `https://www.googleapis.com/auth/drive.readonly` |
| `identity` | Principal.id | Deployment identity |

## RetrievalScope

**Canonical field definitions live in Retrieval Core** (`specs/002-retrieval-core/data-model.md`). This context stores and **enforces** the same object. Shared module: `src/google_drive_mcp/domain/retrieval_scope.py`.

| Field | Type | Rules |
| --- | --- | --- |
| `folder_id` | string? | If set, allowed resources are this folder and (for find/grep) descendants; ls uses immediate children only |
| `file_ids` | string[]? | If set, only these ids |
| `default_whole_grant` | bool | True when neither folder nor file list named; scope = whole Google grant for this identity |

A caller-named `file_id` that Google grants but that lies outside `folder_id` is an MCP authorization failure (`AUTHORIZATION_ERROR`) after metadata `files.get` (not a content fetch). See [authorization-chain.md](./contracts/authorization-chain.md).

## AuthorizationDecision

| Field | Type | Rules |
| --- | --- | --- |
| `outcome` | enum | `ALLOW` \| `AUTHENTICATION_ERROR` \| `AUTHORIZATION_ERROR` \| `FILE_NOT_FOUND` |
| `step_failed` | enum? | `mcp_authentication` \| `mcp_authorization` \| `google_authorization` |
| `reason_code` | string | Machine-readable, no token material |
| `principal_id` | string | Non-secret; for logs only |

`AUTHORIZATION_ERROR` from a folder ∩ file_ids miss uses `step_failed = google_authorization` because it requires granted metadata. Argument-level step-3 failures (none in v1 tools) would use `mcp_authorization`.

### Transitions

```text
start
  → mcp_authentication fail → AUTHENTICATION_ERROR (stop)
  → mcp_authentication pass
      → mcp_authorization fail (argument-level; v1 tools pass) → AUTHORIZATION_ERROR (stop, no Drive I/O)
      → mcp_authorization pass
          → google_authorization fail (no grant) → FILE_NOT_FOUND (stop, no existence leak)
          → google_authorization: granted file_id outside folder_id → AUTHORIZATION_ERROR (stop, no content I/O)
          → google_authorization pass → ALLOW → resource
```

No default-allow. No transition from document text.

## ErrorEnvelope (shared wire type)

| Field | Type | Rules |
| --- | --- | --- |
| `status` | `ERROR` | |
| `category` | enum | See [contracts/error-taxonomy.md](./contracts/error-taxonomy.md) |
| `message` | string | Safe for agents; no tokens, no unauthorized metadata |
| `request_id` | string | Correlation |

Access Control may emit: `AUTHENTICATION_ERROR`, `AUTHORIZATION_ERROR`, `FILE_NOT_FOUND`.
