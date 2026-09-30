# Data Model: 004 Paid Subscription

## EntitlementCookie (browser)

- `scid`: Stripe customer id (opaque)
- `exp`: 400 days; renewed when this browser visits the origin with a still-valid cookie
- `typ`: `entitlement`
- Signed with the same HMAC material as MCP JWTs
- Never logged

## Token claim `scid`

Copied from entitlement into authorization code, access token, and refresh token when the paywall is on. A refresh token with `scid` expires in 400 days and is replaced on each refresh that still sees an active subscription.

## Stripe objects (not stored here)

- Customer
- Subscription (price = $10/month; statuses treated as entitled: `active`, `trialing`)
- Checkout Session (`mode=subscription`)

## Relationships

Checkout success, or a receipt-email lookup that finds an active customer → customer id → cookie → `/authorize` → code/tokens with `scid` → refresh re-checks Stripe for that customer and rotates the refresh token. The email is not stored on this origin. An in-progress `/authorize` is kept in a short-lived resume cookie so Connect finishes after payment or restore.
