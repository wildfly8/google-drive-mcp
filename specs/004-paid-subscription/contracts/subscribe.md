# Contract: Subscription HTTP

## `GET /subscribe`

HTML. States USD 20/month. Pay button is the only action. No Setup link, no owner bank, no card fields. After payment, `GET /subscribe/complete` links to `/setup`.

## `POST /subscribe/checkout`

Starts hosted Checkout (`mode=subscription`). Redirects to Stripe. 503 if Stripe is not configured.

## `GET /subscribe/complete?session_id=`

Retrieves Checkout Session. If paid/complete, Set-Cookie entitlement. HTML: return to Claude and Connect. Optional one-time `entitlement` code displayed.

## `POST /webhooks/stripe`

Stripe-Signature required. Invalid signature → 400. Valid → 200. Body not logged.

## `GET /setup`

When the paywall is on and the request has no valid entitlement cookie, or Stripe says that subscription is inactive: HTML is only the $20 fee and a link to `/subscribe`. No connector URL, copy control, Claude steps, OAuth note, usage counts, or Google Cloud console links.

When the entitlement cookie verifies and Stripe reports the subscription active: existing connector instructions, including the URL.

## `GET /authorize` (existing)

If paywall on and no active entitlement → 302 `/subscribe`. If entitled → existing OAuth code/consent behavior.

## `POST /token` refresh

If paywall on and Stripe says not active (or missing `scid`) → `invalid_grant`.
