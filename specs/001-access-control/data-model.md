# Data Model: Access Control Boundary

All **Drive** objects below are request-scoped. MCP OAuth access/refresh/authorization-code values and consent tickets are self-contained JWTs (not Drive documents). DCR and fetched CIMD client records are in-memory protocol state (Article III exception).

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
| `token` | secret string | HS256 JWT issued by this origin; `aud` / resource = `{issuer}/mcp`; scope `drive.read`; `typ` = `access`; lifetime 3600 s (`Settings.mcp_access_token_ttl_seconds`, not read from env) |
| `client_id` | string | DCR or CIMD client that received the token |
| `sub` | string | `MCP_PRINCIPAL_ID` |
| `jti` | string | Unique id; used for revocation and replay sets |
| `cid` | string? | Opaque Connect id for the 003 counters |
| `scid` | string? | Stripe customer id when the 004 paywall is on. Not a credential |

Presented as `Authorization: Bearer` on `/mcp`. Never a Google token. Never a tool argument. Tests may mint with the deployment signing key; production hosts obtain it via auth-code + PKCE. `/mcp` checks the JWT only (signature, `typ`, `iss`, `aud`, `exp`, scope, `client_id`, `jti`); it does not consult the in-memory revocation set or the processor. The `Bearer ` prefix is optional.

A refresh token has the same claims with `typ` = `refresh` and lifetime 30 days, or 400 days when it carries `scid`. Each refresh rotates it; with the paywall on, each refresh also re-checks the processor. An authorization code has `typ` = `code`, lifetime 120 s, and adds `redirect_uri`, `redirect_uri_provided_explicitly`, and `code_challenge`.

## ConsentPassword

| Field | Type | Rules |
| --- | --- | --- |
| `value` | secret string | Env `MCP_AUTH_TOKEN`. HMAC-compared only on `POST /consent` for a ticket without `scid` (paywall off) |

MUST NOT verify as `McpAccessToken`. Used to derive the JWT HMAC key unless `MCP_OAUTH_SIGNING_KEY` is set. With the paywall on, no page asks for it.

## ConsentTicket

| Field | Type | Rules |
| --- | --- | --- |
| `token` | string | HS256 JWT, `typ` = `ticket`, `aud` = `{issuer}/consent`, lifetime 600 s |
| `client_id`, `redirect_uri`, `redirect_uri_provided_explicitly`, `code_challenge`, `resource`, `state?` | | Copied from the pending `/authorize` request |
| `scid` | string? | Set when the paywall is on. `POST /consent` issues a code only when the browser’s entitlement cookie names this same subscriber and the processor reports it active |

Carried in the `/consent?ticket=` URL and the form. A ticket with `scid` shows the Allow page; without it, the password page. A missing, expired, or tampered ticket shows the expired page (HTTP 400).

## RegisteredClient

| Field | Type | Rules |
| --- | --- | --- |
| `client_id` | string | RFC 7591 id, or a CIMD HTTPS URL on `chatgpt.com` / `claude.ai` / `claude.com` |
| `client_name` | string? | Self-declared. Shown on the Allow page (first 80 characters); not trusted |
| `redirect_uris` | string[] | Validated by the MCP SDK. CIMD clients also accept the known ChatGPT, Claude, and loopback callback paths |

Stored in process memory only. Discarded when the instance disappears. DCR hosts re-register; CIMD clients are fetched again on demand.

## Credential

| Field | Type | Rules |
| --- | --- | --- |
| `scheme` | enum | `google_oauth_refresh` in v1 |
| `access_token` | secret string | Google access token; in-memory only for the request; never in logs, errors, or tool results |
| `scope` | string | Must be read-only Drive (`drive.readonly`) on the three-field refresh mint. With `GOOGLE_AUTHORIZED_USER_JSON`, the scopes already on that blob are kept |

The agent never receives this object. Adapter maps env secrets (`GOOGLE_AUTHORIZED_USER_JSON` first, else `GOOGLE_*`) → Credential. Per request, minted only after chain steps 2–3 pass; the startup allow-list check mints one before serving. Distinct from `McpAccessToken`.

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
| `default_whole_grant` | bool | True when neither folder nor file list named. Never allowed: the chain rewrites an omitted folder to `DRIVE_ALLOWED_FOLDER_ID` and refuses a scope still marked whole-grant (`whole_grant_refused`) |

A named id that is not proven to be `DRIVE_ALLOWED_FOLDER_ID` or a descendant is `AUTHORIZATION_ERROR` (`outside_allowed_folder`), whether it lies outside that folder, does not exist, or Google does not grant it. A caller-named `file_id` that Google grants but that lies outside `folder_id` is an MCP authorization failure (`AUTHORIZATION_ERROR`) after metadata `files.get` (not a content fetch). See [authorization-chain.md](./contracts/authorization-chain.md).

## AuthorizationDecision

| Field | Type | Rules |
| --- | --- | --- |
| `outcome` | enum | `ALLOW` \| `AUTHENTICATION_ERROR` \| `AUTHORIZATION_ERROR` \| `FILE_NOT_FOUND` |
| `step_failed` | enum? | `mcp_authentication` \| `mcp_authorization` \| `google_authorization` |
| `reason_code` | string | Machine-readable, no token material (`mcp_access_token_rejected`, `no_allowed_folder`, `whole_grant_refused`, `outside_allowed_folder`, `file_outside_folder`, `google_grant_miss`, `allow`). Internal: not in the reply and not logged |
| `principal_id` | string | Non-secret; for logs only |

`AUTHORIZATION_ERROR` from the allow-list check (`outside_allowed_folder`) or a folder ∩ file_ids miss (`file_outside_folder`) uses `step_failed = google_authorization` because it needs Drive metadata. Argument-level step-3 failures use `mcp_authorization`: `no_allowed_folder` (no `DRIVE_ALLOWED_FOLDER_ID`) and `whole_grant_refused` (no folder or file after the rewrite). `google_grant_miss` (`FILE_NOT_FOUND`) is only reached when listing the allow-list folder’s own tree gets 404/403. A Google 429 or other failure during step 4 is not a decision: it is raised as `RATE_LIMITED` / `DRIVE_API_ERROR` through `map_google_error()` and the tool body does not run.

### Transitions

```text
start
  → mcp_authentication fail → AUTHENTICATION_ERROR (stop)
  → mcp_authentication pass
      → mcp_authorization fail (no allow-list, or no folder/file after the rewrite) → AUTHORIZATION_ERROR (stop, no Drive I/O)
      → mcp_authorization pass → mint Google credentials
          → google_authorization: list the allow-list tree (skipped when only that folder is named)
              → 404/403 on that listing → FILE_NOT_FOUND (stop)
          → google_authorization: one metadata get per named id; id not proven inside the allow-list folder (outside, missing, or not granted) → AUTHORIZATION_ERROR (stop, same Drive calls, no existence leak)
          → google_authorization: granted file_id outside folder_id → AUTHORIZATION_ERROR (stop, no content I/O)
          → google_authorization pass → ALLOW → resource (a later 404 on a proven id → FILE_NOT_FOUND via map_google_error)
```

No default-allow. No transition from document text.

## ErrorEnvelope (shared wire type)

| Field | Type | Rules |
| --- | --- | --- |
| `status` | `ERROR` | |
| `category` | enum | See [contracts/error-taxonomy.md](./contracts/error-taxonomy.md) |
| `message` | string | Safe for agents; no tokens, no unauthorized metadata. The chain uses the fixed text for each category (`SAFE_MESSAGES`), so every `AUTHORIZATION_ERROR` reads the same |
| `request_id` | string | Correlation |

Access Control may emit: `AUTHENTICATION_ERROR`, `AUTHORIZATION_ERROR`, `FILE_NOT_FOUND`. A Google failure during step 4 surfaces as `RATE_LIMITED` or `DRIVE_API_ERROR` from the shared mapper.
