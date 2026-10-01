# Contract: MCP caller authentication

Production transport: MCP Streamable HTTP.

## MCP caller authentication (this server)

This origin is both the OAuth 2.1 **authorization server** and the MCP **resource server**.

1. Hosts discover RFC 9728 protected-resource metadata at
   `/.well-known/oauth-protected-resource/mcp` (and origin
   `/.well-known/oauth-protected-resource`, which ChatGPT also fetches) and
   authorization-server metadata at `/.well-known/oauth-authorization-server`.
2. Hosts identify as an OAuth client via RFC 7591 DCR (`POST /register`) **or**
   Client ID Metadata Documents (CIMD). ChatGPT and Claude connectors use CIMD:
   `client_id` is an HTTPS URL on `chatgpt.com`, `claude.ai`, or `claude.com`
   (or their `www.` hosts); this server fetches that document on demand (5 s
   timeout, no redirects) so Cloud Run scale-to-zero does not drop the
   registration. Other hosts are never fetched. If the fetch fails, a public
   client with that host’s known callback URIs is synthesized. CIMD clients are
   public (`none`). Authorization-server metadata advertises
   `client_id_metadata_document_supported`, `authorization_response_iss_parameter_supported`,
   and `token_endpoint_auth_methods_supported` = `none`, `client_secret_post`,
   `client_secret_basic`.
3. Hosts send the resource owner through authorization-code + PKCE S256 (`GET /authorize`).
   Only scope `drive.read` is accepted (`invalid_scope` otherwise). A `resource`
   other than `{issuer}/mcp` is `invalid_target`.
   This public Cloud Run deployment runs the 004 paywall; `scripts/deploy-cloud-run.sh`
   refuses to deploy without the Stripe key and price. With the paywall on:
   - A browser without a valid entitlement cookie, or whose subscription is not active, is
     sent to `/subscribe`. A resume cookie (1 hour) remembers the `/authorize` request so
     Connect can continue after payment.
   - An entitled browser is sent to `/consent?ticket=` (AC-FR-013). The ticket is a signed,
     10-minute JWT that names the subscriber (`scid`). The Allow page shows the client’s
     self-declared name and the return host, marked as a known AI chat app address or not
     (`claude.ai`, `claude.com`, `chatgpt.com`, `chat.openai.com`, their subdomains,
     `localhost`, `127.0.0.1`). There is no password.
   - `POST /consent` issues the code only when the browser’s entitlement cookie names the
     same subscriber as the ticket and the processor reports it active. Otherwise it shows
     the expired page (HTTP 400) and no code.
   - `MCP_OAUTH_AUTO_APPROVE` is ignored. The deploy sets it to true; it matters only
     when the paywall is off.
   Without the paywall, `MCP_OAUTH_AUTO_APPROVE=true` issues the code at `/authorize`
   with no page, and `false` shows the `/consent` password page (`MCP_AUTH_TOKEN`).
   Consent pages send `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
   `X-Frame-Options: DENY`, and `Content-Security-Policy: frame-ancestors 'none'`.
   `MCP_AUTH_TOKEN` remains the JWT signing input (unless `MCP_OAUTH_SIGNING_KEY` is set)
   and MUST NOT be accepted as a `/mcp` Bearer.
   `GET /setup` is the connector instruction page (Always allow and per-chat enable cannot
   be skipped by this server). With the paywall on, it shows the connector URL only to a
   browser with an active subscription; others see a subscribe page.
   Successful redirects include RFC 9207 `iss` matching the metadata issuer.
4. Hosts exchange the code at `POST /token` (single use; PKCE verifier required; with the
   paywall on, the subscriber in the code must still be active, else `invalid_grant`) and
   call `/mcp` with:

```http
Authorization: Bearer <access_token>
```

The access token is a short-lived (1 hour) HS256 JWT bound to this deployment's `/mcp` resource
(`aud` / RFC 8707 `resource`). The token response also carries a refresh token (30 days, or
400 days when the paywall is on; each refresh rotates it and, with the paywall on, re-checks
the processor). It is **not**:

| Mechanism | Used here? |
| --- | --- |
| **MCP OAuth 2.1 access token** (authorization code + PKCE, DCR or CIMD) | Yes — required on `/mcp` `drive_*` tool calls |
| **Long-lived shared secret as `/mcp` Bearer** (`MCP_AUTH_TOKEN`) | **No.** Compared only on the `/consent` password page (paywall off) |
| **Google OAuth** (`GOOGLE_*` / ADC JSON) | Yes, but only so *this deployment* talks to Drive as one identity. Never sent to MCP clients |

Hosts that implement MCP OAuth 2.1 (ChatGPT custom connectors, Claude connectors, Inspector) complete the redirect against this Cloud Run origin. Hosts that can only attach a static header cannot call `/mcp` with `MCP_AUTH_TOKEN`; they must obtain an access token via the dance (or a test helper that mints a JWT with the deployment signing key).

- `initialize` / `tools/list` / CORS preflight on `/mcp` MAY succeed without a Bearer so hosts (ChatGPT developer-mode plugins) can scan tool metadata. Each advertised tool includes `securitySchemes: [{type: oauth2, scopes: [drive.read]}]`.
- Missing/invalid Bearer on HTTP `tools/call` of a `drive_*` tool → **HTTP 401** + `WWW-Authenticate` (`error="invalid_token"`, absolute `resource_metadata` = origin `/.well-known/oauth-protected-resource`) (Claude lazy-auth / MCP spec). In-process `handle_tool` without a valid access token still returns `AUTHENTICATION_ERROR` (and may wrap JSON-RPC `isError` + `_meta["mcp/www_authenticate"]`). No Drive I/O.
- `/mcp` checks the access JWT only: signature, `typ`, `iss`, `aud`, `exp`, scope, `client_id`, `jti`. The `Bearer ` prefix is optional. It does not consult the revocation set or the processor, so a revoked access token, or one whose subscription lapsed, works until it expires (at most 1 hour). Refresh and new Connects re-check the subscription.
- CIMD clients (ChatGPT / Claude published identity URLs) are granted `scope=drive.read` even when their metadata document omits `scope`. Claude always sends `scope=drive.read` on `/authorize` from this server's `scopes_supported`; the MCP SDK otherwise redirects to the callback with `error=invalid_scope`.
- `GET /mcp` returns **405** (stateless Streamable HTTP). A hanging GET makes Claude's connector probe time out.
- The access token is not a Google token and MUST NOT be forwarded to Google.
- Never a tool argument.

## Secrets (environment)

| Name | Role |
| --- | --- |
| `MCP_AUTH_TOKEN` | Resource-owner consent password (HMAC-compared only on `POST /consent` for a ticket without `scid`, i.e. paywall off). Also used to derive the JWT HMAC key unless `MCP_OAUTH_SIGNING_KEY` is set |
| `MCP_PUBLIC_URL` | HTTPS issuer origin for this service (no path, no `/mcp`). Required in production |
| `MCP_OAUTH_SIGNING_KEY` | Optional dedicated JWT HMAC material; key = `SHA-256(value)`. If unset, key = `SHA-256("mcp-oauth-jwt-v1:" + MCP_AUTH_TOKEN)`. The same key signs consent tickets and the 004 entitlement and email-link cookies (`typ` and `aud` keep them apart) |
| `MCP_OAUTH_AUTO_APPROVE` | Paywall off: if true, `/authorize` skips the `/consent` password page. Paywall on: ignored; every Connect shows the subscriber an Allow page (no password), because any site can register a client and send a subscriber's browser to `/authorize`. Tools still require a minted access token (AC-FR-010). |
| `MCP_PRINCIPAL_ID` | Non-secret log label for the deployment identity |
| `GOOGLE_CLIENT_ID` | Google Drive OAuth client (deployment identity), not MCP OAuth |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | Deployment Drive identity refresh token |
| `GOOGLE_AUTHORIZED_USER_JSON` | Alternative to the three fields above, preferred when set. Keeps the scopes on the blob, so its grant must be read-only |
| `DRIVE_ALLOWED_FOLDER_ID` | Required. The only readable folder (`kb`). The deploy reads it from Secret Manager. See [authorization-chain.md](./authorization-chain.md) |
| `MCP_SUBSCRIPTION_REQUIRED` | Turns on the 004 paywall and the Allow page. Set by the deploy, which refuses to run without `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID`. Billing secrets are listed in `specs/004-paid-subscription/` |

Stdio local inspector MAY read the same env; HTTP serving MUST refuse to start OAuth without `MCP_PUBLIC_URL`.

## Ephemeral protocol state (Article III)

Access, refresh, authorization-code, and consent-ticket values are self-contained JWTs (not Drive documents). DCR client records, fetched CIMD records, and used-code / revocation `jti` sets are **in-memory auth protocol state**. They are discarded when the instance disappears. MCP hosts re-register (RFC 7591) **or** use CIMD (`chatgpt.com`, `claude.ai`, and `claude.com` client metadata URLs are fetched on demand and do not require a persisted DCR row). Residual authorization-code replay is bound by PKCE S256 and a ~2 minute code TTL. `POST /revoke` (RFC 7009) and each refresh rotation add the old `jti` to that instance’s set; code and refresh exchange on that instance honor it. Revocation is best-effort: it holds only on that instance and only while it lives, and `/mcp` never consults the set (see above). The MCP SDK `/revoke` handler requires a `client_secret` form field, so a public client (CIMD, or DCR with `none`) that omits it gets HTTP 400 `invalid_request`; an empty value is accepted.

## Logging

Allowed: `request_id`, `MCP_PRINCIPAL_ID`, chain `step_failed`, error `category`.
Forbidden: bearer value, consent password, authorization code, refresh token, access token, `Authorization` header.
