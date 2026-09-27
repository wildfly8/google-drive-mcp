# Data Model: 004 Paid Subscription

## EntitlementCookie (browser)

- `scid`: Stripe customer id (opaque)
- `exp`: cookie/JWT expiry
- `typ`: `entitlement`
- Signed with the same HMAC material as MCP JWTs
- Never logged

## Token claim `scid`

Copied from entitlement into authorization code, access token, and refresh token when the paywall is on.

## Stripe objects (not stored here)

- Customer
- Subscription (price = $20/month; statuses treated as entitled: `active`, `trialing`)
- Checkout Session (`mode=subscription`)

## Relationships

Checkout success → customer id → cookie → `/authorize` → code/tokens with `scid` → refresh re-checks Stripe for that customer.
