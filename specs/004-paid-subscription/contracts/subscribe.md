# Contract: Subscription HTTP

## `GET /subscribe`

HTML. States USD 20/month. Controls: the Pay button (opens Stripe Checkout) and, when the email-link service is configured, an "Already subscribed?" form that posts an email to `/subscribe/email`. No passkeys, no Continue or Remember button, no Setup link, no owner bank, no card fields. If the browser already has an active entitlement, redirect to the in-progress `/authorize` or to `/setup`.

## `POST /subscribe/email`

Form field `email`. Always the same 200 reply ("if that email has an active subscription, a one-time sign-in link is on its way"), with no entitlement and without echoing the email, so the endpoint does not reveal subscribers. After the reply is sent, the server looks up an active processor customer for that email and only then asks Google Identity Platform to email a one-time sign-in link (continue URL `/subscribe/email/verify`). Sets a short-lived signed cookie (path `/subscribe/email`) holding the typed email so the link can be finished in this browser without retyping it. Rate limits per client address and per email (best effort, per instance, bounded memory). Only ASCII addresses are accepted; the subscriber lookup ignores letter case. An email address alone never grants access.

## `GET /subscribe/email/verify?oobCode=`

The landing page the email link reaches. Does not sign in by itself (mail scanners open links and would use up the one-time code): shows a "Continue in this browser" button, plus an email field when the email cookie is absent. `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, not frameable.

## `POST /subscribe/email/verify`

Fields `oobCode` and `email` (or the email cookie). Google confirms the code was issued for that email (proof of inbox ownership); the Identity Platform user it creates is deleted at once. Then the processor must report an active subscription for that email. Success → Set-Cookie entitlement, 303 to the in-progress `/authorize` or `/setup`. Wrong email, used or expired code → 400. No active subscription → 404 with the Pay button. Rate limited per client address.

## `POST /subscribe/checkout`

Starts hosted Checkout (`mode=subscription`). Redirects to Stripe. 503 if Stripe is not configured.

## `GET /subscribe/complete?session_id=`

A `session_id` that is not shaped like a Checkout Session id (`cs_live_…` or `cs_test_…`) → 400 without calling the processor; rate limited per client address. Retrieves the Checkout Session. Only `status=complete` with `payment_status` `paid` (or `no_payment_required`) counts. Set-Cookie entitlement for the customer who paid in that session, never another customer (the email typed at Checkout is not verified). HTML: return to the AI chat app. The entitlement is only set as an HttpOnly cookie; it is never shown on the page.

## `POST /subscribe/manage`

Same-site form button on the entitled `/setup` page. Opens the processor's customer portal (manage card, cancel) for the customer in this browser's entitlement cookie: 303 to the portal session URL, which returns to `/setup`. No cookie → 403 with a pointer to the receipt email and `/subscribe`. Portal not configured or processor error → 503 with the same pointer. Rate limited per client address. Paywall off → 404. The SameSite=Lax cookie is not sent on cross-site POSTs, so other sites cannot open the portal for a subscriber.

## `POST /webhooks/stripe`

Stripe-Signature required. Invalid signature → 400. Valid → 200. Body not logged.

## `GET /setup`

When the paywall is on and the request has no active entitlement: HTML is only the $20 fee and a link to `/subscribe`. No connector URL, copy control, AI chat app steps, OAuth note, usage counts, or Google Cloud console links.

When the entitlement verifies and Stripe reports the subscription active: connector URL and setup steps for any AI chat app that can add a remote MCP server, including the Allow step, and a **Manage or cancel subscription** button (`POST /subscribe/manage`). No usage counts and no operator Google Cloud console links; the page does not scan logs while the paywall is on.

## `GET /stats` (003)

With the paywall on, the public JSON has the non-PII totals but no `gcp` console links (they name the cloud project).

## `GET /authorize` (existing)

If paywall on and no entitlement cookie → 302 `/subscribe`. A cookie whose subscription is no longer active → 302 `/subscribe` too. Either way the in-progress `/authorize` URL is kept in a 1-hour resume cookie, so Checkout or the email link returns to it. If entitled → 302 `/consent?ticket=` (a signed, 10-minute ticket that names this subscriber). Never a code without the Allow click.

Cookie renewal: every response to a browser with a valid entitlement cookie renews it for 400 days, unless the route itself just set a new entitlement (Checkout return, email link); the new one is kept.

## `GET /consent?ticket=` / `POST /consent`

Paid ticket: an Allow page showing the client's self-declared name and the host the browser returns to, marked as a known AI chat app address or not. No password. `POST` issues the code only when the browser's own entitlement names the same subscriber and Stripe still reports it active; otherwise 400. All consent responses: `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'`, `Cache-Control: no-store`. Unpaid deployments keep the `MCP_AUTH_TOKEN` password page.

## `POST /token` refresh

If paywall on and Stripe says not active (or missing `scid`) → `invalid_grant`. Stripe 429, 5xx or connection errors are retried up to three attempts (about 1 s in all); a non-JSON or malformed reply counts as not active. The refresh token rotates only on success, so a refresh refused during a Stripe outage can be retried with the same token. Access tokens are not re-checked on `/mcp`; they expire within 1 hour.
