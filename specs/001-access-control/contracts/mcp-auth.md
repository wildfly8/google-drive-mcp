# Contract: MCP caller authentication

Production transport: MCP Streamable HTTP.

## MCP caller authentication (this server)

```http
Authorization: Bearer <MCP_AUTH_TOKEN>
```

This is a **pre-shared static token** compared with constant-time equality. It is **not**:

| Mechanism | Used here? |
| --- | --- |
| **MCP caller Bearer** (`MCP_AUTH_TOKEN`) | Yes — required on tool calls |
| **Google OAuth** (`GOOGLE_*` / ADC JSON) | Yes, but only so *this deployment* talks to Drive as one identity. Never sent to MCP clients |
| **MCP OAuth 2.1** (authorization code, DCR, protected-resource metadata login dance) | **No** in v1 |

Hosts that can attach `Authorization: Bearer` (Cursor HTTP MCP, Claude Code `--header`, ChatGPT Desktop / Codex `bearer_token_env_var`) can call this server. Hosts that will only connect after an MCP OAuth authorization-code redirect against this origin cannot, until that is specified as a MAJOR change (Article XIV).

- Missing header, empty token, or mismatch → `AUTHENTICATION_ERROR` before any Drive I/O.
- The bearer is not a Google token and MUST NOT be forwarded to Google.
- Never a tool argument.

## Secrets (environment)

| Name | Role |
| --- | --- |
| `MCP_AUTH_TOKEN` | MCP caller shared secret (Bearer) |
| `MCP_PRINCIPAL_ID` | Non-secret log label for the deployment identity |
| `GOOGLE_CLIENT_ID` | Google Drive OAuth client (deployment identity), not MCP OAuth |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | Deployment Drive identity refresh token |

Stdio local inspector MAY read the same env; it MUST still refuse tools if `MCP_AUTH_TOKEN` is unset in non-dev mode.

## Logging

Allowed: `request_id`, `MCP_PRINCIPAL_ID`, chain `step_failed`, error `category`.
Forbidden: bearer value, refresh token, access token, `Authorization` header.
