# Data Model: Access Control Boundary

All objects below are request-scoped. None are persisted by the MCP.

## Principal

| Field | Type | Rules |
| --- | --- | --- |
| `id` | string | Non-secret deployment/identity label (`MCP_PRINCIPAL_ID`). Never a raw token. |
| `kind` | enum | `deployment_google_identity` in v1 |

v1: exactly one Principal per deployment. MCP authentication proves the caller may act *as* this principal; it does not select among Google users.

## Credential

| Field | Type | Rules |
| --- | --- | --- |
| `scheme` | enum | `google_oauth_refresh` in v1 |
| `access_token` | secret string | In-memory only for the request; never in logs, errors, or tool results |
| `scope` | string | Must be read-only Drive (`drive.readonly`) |

The agent never receives this object. Adapter maps env secrets → Credential.

## Grant

| Field | Type | Rules |
| --- | --- | --- |
| `oauth_scope` | string | Narrowest practical: `https://www.googleapis.com/auth/drive.readonly` |
| `identity` | Principal.id | Deployment identity |

## RetrievalScope

Defined fully in Retrieval Core. This context stores and enforces:

| Field | Type | Rules |
| --- | --- | --- |
| `folder_id` | string? | If set, allowed resources are this folder and (for find/grep) descendants |
| `file_ids` | string[]? | If set, only these ids |
| `unspecified` | bool | If no folder/file list, scope = whole Google grant for this identity |

A named resource outside this object is an MCP authorization failure (`AUTHORIZATION_ERROR`) before Google is called.

## AuthorizationDecision

| Field | Type | Rules |
| --- | --- | --- |
| `outcome` | enum | `ALLOW` \| `AUTHENTICATION_ERROR` \| `AUTHORIZATION_ERROR` \| `FILE_NOT_FOUND` |
| `step_failed` | enum? | `mcp_authentication` \| `mcp_authorization` \| `google_authorization` |
| `reason_code` | string | Machine-readable, no token material |
| `principal_id` | string | Non-secret; for logs only |

### Transitions

```text
start
  → mcp_authentication fail → AUTHENTICATION_ERROR (stop)
  → mcp_authentication pass
      → mcp_authorization fail (out of RetrievalScope) → AUTHORIZATION_ERROR (stop)
      → mcp_authorization pass
          → google_authorization fail → FILE_NOT_FOUND (stop, no existence leak)
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
