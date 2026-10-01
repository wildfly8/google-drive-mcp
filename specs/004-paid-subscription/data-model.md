# Data Model: 004 Paid Subscription

## EntitlementCookie (browser)

- `scid`: Stripe customer id (opaque)
- `exp`: 400 days; renewed when this browser visits the origin with a still-valid cookie
- `typ`: `entitlement`
- Signed with the same HMAC material as MCP JWTs
- Never logged
- Only ever the HttpOnly cookie: never shown on a page, never accepted from a URL (FR-015)
- Renewed on each response, except when that response sets a new entitlement

## ResumeCookie (browser)

- `onto_kb_resume`: the in-progress `/authorize` path and query, 1 hour, HttpOnly, SameSite=Lax
- Set when `/authorize` sends the browser to `/subscribe` (no cookie, or a lapsed subscription)
- Read by the Checkout return and the email link to continue Connect at the Allow page

## Token claim `scid`

Copied from entitlement into authorization code, access token, and refresh token when the paywall is on. A refresh token with `scid` expires in 400 days and is replaced on each refresh that still sees an active subscription.

## Stripe objects (not stored here)

- Customer
- Subscription (price = $20/month; statuses treated as entitled: `active`, `trialing`)
- Checkout Session (`mode=subscription`)

## Relationships

Checkout success, or a receipt-email lookup that finds an active customer → customer id → cookie → `/authorize` → code/tokens with `scid` → refresh re-checks Stripe for that customer and rotates the refresh token. The email is not stored on this origin. An in-progress `/authorize` is kept in a short-lived resume cookie so Connect finishes after payment or restore.
