# Contract: MCP caller authentication

Production transport: MCP Streamable HTTP.

## MCP caller authentication (this server)

This origin is both the OAuth 2.1 **authorization server** and the MCP **resource server**.

1. Hosts discover RFC 9728 protected-resource metadata at
   `/.well-known/oauth-protected-resource/mcp` (and origin
   `/.well-known/oauth-protected-resource`, which ChatGPT also fetches) and
   authorization-server metadata at `/.well-known/oauth-authorization-server`.
2. Hosts identify as an OAuth client via RFC 7591 DCR (`POST /register`) **or**
   Client ID Metadata Documents (CIMD). ChatGPT custom connectors use CIMD:
   `client_id` is an HTTPS URL on `chatgpt.com`; this server fetches that
   document on demand so Cloud Run scale-to-zero does not drop the registration.
   Authorization-server metadata advertises `client_id_metadata_document_supported`
   and `token_endpoint_auth_methods_supported` including `none` (public-client PKCE).
3. Hosts send the resource owner through authorization-code + PKCE S256 (`GET /authorize`).
   This public Cloud Run deployment sets `MCP_OAUTH_AUTO_APPROVE=true`, so `/authorize`
   mints a code without `/consent`. `MCP_AUTH_TOKEN` remains the JWT signing input (unless
   `MCP_OAUTH_SIGNING_KEY` is set) and MUST NOT be accepted as a `/mcp` Bearer.
   Private deploys MAY leave auto-approve off and use `/consent`.
   `GET /setup` is the Claude connector instruction page (Always allow and
   per-chat enable cannot be skipped by this server).
   Successful redirects include RFC 9207 `iss` matching the metadata issuer.
4. Hosts exchange the code at `POST /token` and call `/mcp` with:

```http
Authorization: Bearer <access_token>
```

The access token is a short-lived HS256 JWT bound to this deployment's `/mcp` resource
(`aud` / RFC 8707 `resource`). It is **not**:

| Mechanism | Used here? |
| --- | --- |
| **MCP OAuth 2.1 access token** (authorization code + PKCE, DCR) | Yes — required on `/mcp` |
| **Long-lived shared secret as `/mcp` Bearer** (`MCP_AUTH_TOKEN`) | **No.** Compared only on `/consent` (resource-owner password) |
| **Google OAuth** (`GOOGLE_*` / ADC JSON) | Yes, but only so *this deployment* talks to Drive as one identity. Never sent to MCP clients |

Hosts that implement MCP OAuth 2.1 (ChatGPT custom connectors, Claude connectors, Inspector) complete the redirect against this Cloud Run origin. Hosts that can only attach a static header cannot call `/mcp` with `MCP_AUTH_TOKEN`; they must obtain an access token via the dance (or a test helper that mints a JWT with the deployment signing key).

- `initialize` / `tools/list` / CORS preflight on `/mcp` MAY succeed without a Bearer so hosts (ChatGPT developer-mode plugins) can scan tool metadata. Each advertised tool includes `securitySchemes: [{type: oauth2, scopes: [drive.read]}]`.
- Missing/invalid Bearer on HTTP `tools/call` → **HTTP 401** + `WWW-Authenticate` with an absolute `resource_metadata` URL (Claude lazy-auth / MCP spec). In-process `handle_tool` without a valid access token still returns `AUTHENTICATION_ERROR` (and may wrap JSON-RPC `isError` + `_meta["mcp/www_authenticate"]`). No Drive I/O.
- CIMD clients (ChatGPT / Claude published identity URLs) are granted `scope=drive.read` even when their metadata document omits `scope`. Claude always sends `scope=drive.read` on `/authorize` from this server's `scopes_supported`; the MCP SDK otherwise redirects to the callback with `error=invalid_scope`.
- `GET /mcp` returns **405** (stateless Streamable HTTP). A hanging GET makes Claude's connector probe time out.
- The access token is not a Google token and MUST NOT be forwarded to Google.
- Never a tool argument.

## Secrets (environment)

| Name | Role |
| --- | --- |
| `MCP_AUTH_TOKEN` | Resource-owner consent password (HMAC-compared only on `POST /consent`). Also used to derive the JWT HMAC key unless `MCP_OAUTH_SIGNING_KEY` is set |
| `MCP_PUBLIC_URL` | HTTPS issuer origin for this service (no path, no `/mcp`). Required in production |
| `MCP_OAUTH_SIGNING_KEY` | Optional dedicated JWT HMAC material. If unset, key = `SHA-256("mcp-oauth-jwt-v1:" + MCP_AUTH_TOKEN)` |
| `MCP_OAUTH_AUTO_APPROVE` | If true, `/authorize` skips `/consent`. This public connector enables it so Claude users are not asked for `MCP_AUTH_TOKEN`. Tools still require a minted access token (AC-FR-010). |
| `MCP_PRINCIPAL_ID` | Non-secret log label for the deployment identity |
| `GOOGLE_CLIENT_ID` | Google Drive OAuth client (deployment identity), not MCP OAuth |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | Deployment Drive identity refresh token |

Stdio local inspector MAY read the same env; HTTP serving MUST refuse to start OAuth without `MCP_PUBLIC_URL`.

## Ephemeral protocol state (Article III)

Access, refresh, and authorization-code values are self-contained JWTs (not Drive documents). DCR client records and used-code / revocation `jti` sets are **in-memory auth protocol state**. They are discarded when the instance disappears. MCP hosts re-register (RFC 7591) **or** use CIMD (`chatgpt.com` client metadata URLs are fetched on demand and do not require a persisted DCR row). Residual authorization-code replay is bound by PKCE S256 and a ~2 minute code TTL. Refresh-token revocation is best-effort until expiry on that instance.

## Logging

Allowed: `request_id`, `MCP_PRINCIPAL_ID`, chain `step_failed`, error `category`.
Forbidden: bearer value, consent password, authorization code, refresh token, access token, `Authorization` header.
