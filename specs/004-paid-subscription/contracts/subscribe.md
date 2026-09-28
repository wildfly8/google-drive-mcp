# Contract: Subscription HTTP

## `GET /subscribe`

HTML. States USD 20/month. Pay button for a new subscription. A second form accepts the Stripe receipt email to continue an active subscription with no new charge. No Setup link, no owner bank, no card fields. If the browser already has an active entitlement, redirect to the in-progress `/authorize` or to `/setup`. After payment with no in-progress Connect, `GET /subscribe/complete` links to `/setup`. If Connect was in progress, completion redirects back to that `/authorize` URL.

## `POST /subscribe/restore`

Form field `email`. Looks up an active processor customer. On success, sets the entitlement cookie and redirects to the in-progress `/authorize` or `/setup`. Does not create a charge. Does not log, store, or echo the email. Unknown or inactive email → 404 and the pay button, still without echoing the email.

## `POST /subscribe/checkout`

Starts hosted Checkout (`mode=subscription`). Redirects to Stripe. 503 if Stripe is not configured.

## `GET /subscribe/complete?session_id=`

Retrieves Checkout Session. If paid/complete, Set-Cookie entitlement. HTML: return to Claude and Connect. Optional one-time `entitlement` code displayed.

## `POST /webhooks/stripe`

Stripe-Signature required. Invalid signature → 400. Valid → 200. Body not logged.

## `GET /setup`

When the paywall is on and the request has no active entitlement: HTML is only the $20 fee and a link to `/subscribe`. No connector URL, copy control, Claude / ChatGPT / Cursor steps, OAuth note, usage counts, or Google Cloud console links.

When the entitlement verifies and Stripe reports the subscription active: connector URL and setup steps for Claude, ChatGPT, and Cursor. No operator Google Cloud console links.

## `GET /authorize` (existing)

If paywall on and no active entitlement → 302 `/subscribe`. If entitled → existing OAuth code/consent behavior.

## `POST /token` refresh

If paywall on and Stripe says not active (or missing `scid`) → `invalid_grant`.
