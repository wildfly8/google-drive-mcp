# Contract: Subscription HTTP

## `GET /subscribe`

HTML. States USD 20/month. Pay button. No owner bank, no card fields.

## `POST /subscribe/checkout`

Starts hosted Checkout (`mode=subscription`). Redirects to Stripe. 503 if Stripe is not configured.

## `GET /subscribe/complete?session_id=`

Retrieves Checkout Session. If paid/complete, Set-Cookie entitlement. HTML: return to Claude and Connect. Optional one-time `entitlement` code displayed.

## `POST /webhooks/stripe`

Stripe-Signature required. Invalid signature → 400. Valid → 200. Body not logged.

## `GET /setup`

Includes $20/month + link to `/subscribe` when paywall is on.

## `GET /authorize` (existing)

If paywall on and no active entitlement → 302 `/subscribe`. If entitled → existing OAuth code/consent behavior.

## `POST /token` refresh

If paywall on and Stripe says not active (or missing `scid`) → `invalid_grant`.
