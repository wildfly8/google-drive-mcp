# Contract: Subscription HTTP

## `GET /subscribe`

HTML. States USD 20/month. Controls: the Pay button (opens Stripe Checkout) and, when the email-link service is configured, an "Already subscribed?" form that posts an email to `/subscribe/email`. No passkeys, no Continue or Remember button, no Setup link, no owner bank, no card fields. If the browser already has an active entitlement, redirect to the in-progress `/authorize` or to `/setup`. If it holds an entitlement that is no longer active (cancelled, or a renewal failed), the page also shows **Manage or cancel subscription** and **Sign out of this browser**, so a failed card can be updated instead of paying twice.

## `POST /subscribe/email`

Form field `email`. Always the same 200 reply ("if that email has an active subscription, a one-time sign-in link is on its way"), with no entitlement and without echoing the email, so the endpoint does not reveal subscribers. Before replying, the server looks up an active processor customer for that email (off the event loop) and only then asks Google Identity Platform to email a one-time sign-in link (continue URL `/subscribe/email/verify`); the work is not left for after the reply, because Cloud Run throttles CPU once a reply is sent. Every reply to a well-formed address, subscriber or not and rate limited or not, takes at least 3 seconds from the start of the request, so timing does not reveal subscribers either. Sets a short-lived signed cookie (path `/subscribe/email`) holding the typed email so the link can be finished in this browser without retyping it. Rate limits per client address and per email (best effort, per instance, bounded memory). Only ASCII addresses are accepted; the subscriber lookup ignores letter case. An email address alone never grants access.

## `GET /subscribe/email/verify?oobCode=`

The landing page the email link reaches. Does not sign in by itself (mail scanners open links and would use up the one-time code): shows a "Continue in this browser" button, plus an email field when the email cookie is absent. `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, not frameable.

## `POST /subscribe/email/verify`

Fields `oobCode` and `email` (or the email cookie). Google confirms the code was issued for that email (proof of inbox ownership); the Identity Platform user it creates is deleted at once. Then the processor must report an active subscription for that email. Success → Set-Cookie entitlement, 303 to the in-progress `/authorize` or `/setup`. Wrong email, used or expired code → 400. No active subscription → 404 with the Pay button. Rate limited per client address.

## `POST /subscribe/checkout`

Starts hosted Checkout (`mode=subscription`) with `consent_collection[terms_of_service]=required` and `custom_text[terms_of_service_acceptance][message]` set to the consent sentence: a link to the Terms, an express request for access to start at once, and the statement that a buyer with a legal right to withdraw (14 days after paying in the EU and UK is given only as an example, since the right and its length depend on the buyer's country) who uses it in time gets the first payment back minus a pro-rata charge for the days used. The buyer cannot pay without ticking it (FR-019). The session also carries a random `client_reference_id` and sets the same value in a 24-hour HttpOnly cookie `onto_kb_checkout` (Path=/subscribe), which ties the session to this browser. Redirects to Stripe. When the browser holds an entitlement cookie (a lapsed subscriber), Checkout is started for that same Stripe customer (`customer`), so a returning subscriber does not become a second customer; if Stripe no longer has that customer (`resource_missing`), Checkout starts without it. Rate limited per client address (10 per hour) → 429. 503 if Stripe is not configured or Checkout cannot start; the failure is logged with the exception type only.

## `GET /subscribe/complete?session_id=`

A `session_id` that is not shaped like a Checkout Session id (`cs_live_…` or `cs_test_…`) → 400 without calling the processor; rate limited per client address. Retrieves the Checkout Session. Only `status=complete` with `payment_status` `paid` (or `no_payment_required`) counts. Set-Cookie entitlement for the customer who paid in that session, never another customer (the email typed at Checkout is not verified). HTML: return to the AI chat app. The entitlement is only set as an HttpOnly cookie; it is never shown on the page. The session's `client_reference_id` must equal this browser's `onto_kb_checkout` cookie, so a success link opened in another browser grants nothing (a browser that already holds an entitlement is sent on to `/setup`; one without gets 400). The checkout cookie is deleted on success.

## `POST /subscribe/manage`

Same-site form button on the entitled `/setup` page. Opens the processor's customer portal (manage card, cancel) for the customer in this browser's entitlement cookie: 303 to the portal session URL, which returns to `/setup`. No cookie → 403 with a pointer to the receipt email and `/subscribe`. Portal not configured or processor error → 503 with the same pointer. Rate limited per client address. Paywall off → 404. The SameSite=Lax cookie is not sent on cross-site POSTs, so other sites cannot open the portal for a subscriber.

## `POST /subscribe/signout`

Deletes the entitlement and resume cookies in this browser and redirects to `/subscribe`. Shown on the entitled `/setup` page and to lapsed subscribers.

## Same-site rule for every `/subscribe/*` POST

`/subscribe/checkout`, `/subscribe/email`, `/subscribe/email/verify`, `/subscribe/manage` and `/subscribe/signout` answer 403 when the browser reports another site: `Sec-Fetch-Site` other than `same-origin` or `none`, or else an `Origin` that is `null` or not this origin. Requests with neither header (non-browser clients) are not refused by this rule.

## Security headers (every response)

Any `text/html` response gets `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'; base-uri 'none'; object-src 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`, each only when the page does not set that header itself (consent and email-link pages keep their own `frame-ancestors 'none'`). The policy has no `default-src`, `script-src` or `form-action`: `/setup` has an inline script and Checkout and the portal are form redirects to Stripe. Any response that sets a cookie (the renewed entitlement too) gets `Cache-Control: no-store` unless its own says `no-store` or `private`; a public one (OAuth metadata) is replaced. Cookie-free JSON keeps its own caching.

## `POST /webhooks/stripe`

Stripe-Signature required. Invalid signature → 400. Valid → 200. Body not logged.

## `GET /setup`

When the paywall is on and the request has no active entitlement: HTML is only the $20 fee and a link to `/subscribe`. No connector URL, copy control, AI chat app steps, OAuth note, usage counts, or Google Cloud console links.

When the entitlement verifies and Stripe reports the subscription active: connector URL and setup steps for any AI chat app that can add a remote MCP server, including the Allow step, and a **Manage or cancel subscription** button (`POST /subscribe/manage`). No usage counts and no operator Google Cloud console links; the page does not scan logs while the paywall is on.

## `GET /stats` (003)

With the paywall on, the public JSON has the non-PII totals but no `gcp` console links (they name the cloud project). The snapshot and its one-minute cached Cloud Logging scan run off the event loop; while a scan runs, other requests get the previous result instead of waiting (only the first scan after start is waited for).

## `GET /authorize` (existing)

If paywall on and no entitlement cookie → 302 `/subscribe`. A cookie whose subscription is no longer active → 302 `/subscribe` too. Either way the in-progress `/authorize` URL is kept in a 1-hour resume cookie, so Checkout or the email link returns to it. If entitled → 302 `/consent?ticket=` (a signed, 10-minute ticket that names this subscriber). Never a code without the Allow click.

Cookie renewal: every response to a browser with a valid entitlement cookie renews it for 400 days, unless the route itself just set a new entitlement (Checkout return, email link); the new one is kept.

## `GET /consent?ticket=` / `POST /consent`

Paid ticket: an Allow page showing the client's self-declared name and the host the browser returns to, marked as a known AI chat app address, a program on this computer (loopback; shown as a warning), or not recognized. No password. `POST` issues the code only when the browser's own entitlement names the same subscriber and Stripe still reports it active; otherwise 400. All consent responses: `X-Frame-Options: DENY`, `Content-Security-Policy: frame-ancestors 'none'`, `Cache-Control: no-store`. Unpaid deployments keep the `MCP_AUTH_TOKEN` password page.

## `POST /token` refresh

If paywall on and Stripe says not active (or missing `scid`) → `invalid_grant`. Stripe 429, 5xx or connection errors are retried up to three attempts (about 1 s in all, off the request loop). If Stripe still cannot be asked (or replies with something that is not a subscription list) → HTTP 503 `{"error": "temporarily_unavailable"}` with `Retry-After: 30`, not `invalid_grant`, because hosts discard tokens on `invalid_grant`. The refresh token is reserved while Stripe is asked (two refreshes with one token never both succeed) and released if the refresh fails, so it works again once Stripe answers. The authorization-code exchange answers the same 503 when Stripe cannot be asked. Access tokens are not re-checked on `/mcp`; they expire within 1 hour.
