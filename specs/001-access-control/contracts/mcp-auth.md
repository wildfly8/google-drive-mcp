# Contract: MCP caller authentication

Production transport: MCP Streamable HTTP.

## Request

```http
Authorization: Bearer <MCP_AUTH_TOKEN>
```

- Compare to the deployment secret with a constant-time equality check.
- Missing header, empty token, or mismatch → `AUTHENTICATION_ERROR` before any Drive I/O.
- The bearer is not a Google token and MUST NOT be forwarded to Google.

## Secrets (environment)

| Name | Role |
| --- | --- |
| `MCP_AUTH_TOKEN` | MCP caller shared secret |
| `MCP_PRINCIPAL_ID` | Non-secret log label for the deployment identity |
| `GOOGLE_CLIENT_ID` | OAuth client (infrastructure) |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | Deployment Drive identity refresh token |

Stdio local inspector MAY read the same env; it MUST still refuse tools if `MCP_AUTH_TOKEN` is unset in non-dev mode.

## Logging

Allowed: `request_id`, `MCP_PRINCIPAL_ID`, chain `step_failed`, error `category`.
Forbidden: bearer value, refresh token, access token, `Authorization` header.
