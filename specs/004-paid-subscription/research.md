# Research: 004 Paid Subscription

## Decision: Stripe Checkout + Billing (not PayPal)

**Rationale**: Recurring $20/month, PCI hosted card form, Customer Portal for cancel, signed webhooks, and a customer id we can bind to MCP OAuth in the subscriber's browser. PayPal subscriptions are weaker for webhook-driven entitlement and for this OAuth binding.

**Alternatives considered**: PayPal Subscriptions (deferred); crypto (no consumer checkout, poor Claude UX); invoicing with bank transfer (exposes owner bank — rejected).

## Decision: Operator KYC stays with Stripe, not with MCP users

**Rationale**: USD payouts require a verified Stripe account and a bank (or debit) payout destination. That is disclosure **to Stripe**, not to connector users. This origin will not collect or display owner bank details.

**Alternatives considered**: Anonymous cash-out — not offered (illegal/unworkable for a public $20 fee).

## Decision: Stripe is source of truth; no subscriber database

**Rationale**: Article III. Cloud Run stays ephemeral. `GET /v1/subscriptions?customer=…&status=active` on authorize/refresh. Cookie/JWT `scid` is only the Stripe customer id.

**Alternatives considered**: Firestore/SQL of subscribers — extra persistent store, out of v1 MINOR scope.

## Decision: Cookie on `/authorize`, `scid` on tokens for refresh

**Rationale**: Claude, ChatGPT, and Cursor call `/token` and `/mcp` from their own clouds (no browser cookie). The browser hits `/authorize` during Connect. A 400-day signed cookie covers that browser. Access and refresh JWTs carry `scid`. Each refresh re-queries Stripe and, while the subscription is active, rotates a 400-day refresh token so the assistant keeps working with no subscriber action. A different browser continues an active subscription by the email Stripe already stored; that lookup does not create a charge and this origin does not keep the email.

**Alternatives considered**: 30-day cookie only (forces checkout again while Stripe is still active — rejected); treating any visitor as paid when any subscription is active (lets unpaid people in — rejected); a local subscriber database (Article III — rejected).

## Decision: Paywall is independent of `MCP_OAUTH_AUTO_APPROVE`

**Rationale**: FR-009. Auto-approve without payment would zero the fee.

## Decision: Fake Stripe in unit/contract tests

**Rationale**: CI must not need live Stripe. Production uses secret keys in Secret Manager.

## Decision: Verified email links replace email-only restore and passkeys (2026-10-01)

**Rationale**: A public-repo audit showed `POST /subscribe/restore` granted a subscriber's access to anyone who typed that subscriber's email, and a repeat Checkout with that email was refunded and switched to the existing subscription. Stripe Checkout does not verify the email. Both are removed: Checkout always grants the paying customer, and another browser continues a subscription only through a one-time link that Google Identity Platform emails to the receipt address (free tier, no domain, sender `noreply@<project>.firebaseapp.com`). The link lands on a page with a button, because mail scanners open links and would consume the code. Passkeys were removed too: hand-written WebAuthn verification was extra attack surface, Chrome and Edge do not share passkeys, and the email link covers the same need. The audit also found that auto-approve plus open dynamic client registration let a link clicked by a subscriber hand a code to an attacker's client, so a paid Connect now always shows an Allow page bound to the paying browser.

**Alternatives considered**: A dedicated Gmail account sending codes (needs a human to create the account). Resend/Brevo/Mailjet free tiers (need a domain for deliverability). Keeping passkeys with a cross-device prompt (more surface for little gain).

## Decision: Cancellation is enforced by pull checks, tested end to end (2026-10-01)

**Rationale**: Stripe keeps a subscription `active` until the paid period ends when the subscriber cancels at period end, then sets it to `canceled`; an immediate cancel is `canceled` at once; failed renewals are `past_due` then `unpaid` or `canceled` (Stripe docs on cancel, subscription statuses and the list endpoint). Every step that issues a credential asks Stripe live (`status=all`, active or trialing only), so the webhook is not needed for revocation and access ends within one access-token lifetime. Testing this exposed three bugs, now fixed: renewal of the old cookie overwrote a new entitlement (a lapsed subscriber who paid again stayed locked out), a lapsed Connect was not resumed after paying, and a single Stripe 429/5xx used up the refresh token.

**Alternatives considered**: Webhook-driven revocation (needs shared state across instances; pull checks already bound the delay to one hour). Treating `past_due` as entitled during Stripe's retry window (Stripe's "leave as past_due" setting could then grant access forever). Per-request Stripe checks on `/mcp` (one Stripe call per tool call).

## Decision: Cancel through the Stripe customer portal from `/setup` (2026-10-01)

**Rationale**: FR-002 promised cancellation in the processor's portal, but nothing linked to it. A portal session for the customer in this browser's cookie needs no new account or stored data, and the SameSite=Lax cookie keeps other sites from opening it.

**Alternatives considered**: Publishing the no-code portal login link only (works, but subscribers must find it). A cancel button on this origin calling the API directly (re-implements what the portal already does, including retention and invoices).

## Decision: Checkout asks for an express request for immediate access, not a waiver (2026-10-05)

**Rationale**: The Terms and public pages say the first payment is not refunded, and consumers in the EU and UK have a 14-day right to withdraw from a distance contract. What an early start does to that right depends on the kind of contract. For a service (EU Consumer Rights Directive Art. 8(8), 14(3) and 16(a); UK Consumer Contracts Regulations reg 36), the buyer's express request lets access start at once but does not end the right: a buyer who withdraws within 14 days owes only an amount in proportion to the access used, and the right ends only when the service has been fully performed, which a monthly subscription is not within 14 days. Only digital content supplied once can be given up this way (Art. 16(m); reg 37), and then only with the buyer's consent, an acknowledgement and a confirmation on a durable medium. onto-kb is most likely a digital service in the EU (an ongoing hosted search service over a library that keeps changing); the UK position is less clear. That is a judgment, not a settled point, so the box says what is true under either reading: the buyer asks for access to start at once and, if they have a legal right to withdraw and use it within 14 days, gets the first payment back minus a pro-rata charge. "If I have a legal right" keeps the published no-refund rule for buyers who have none. A first draft, a box in which the buyer gave up the right, was dropped after review: the waiver does not bind an EU consumer (Art. 25), and telling consumers they have no right is a misleading statement about their rights. This is a design note, not legal advice.

**Alternatives considered**: A box that waives the right (the dropped draft; for digital content it would also need a confirmation email that nothing sends). A pro-rata 14-day refund for every buyer, with no "if I have a legal right" (changes the published policy for buyers with no such right). Not selling to EU and UK consumers (Stripe Checkout cannot screen residence before payment, so it would need a billing-country block in the Stripe Dashboard).

**Still open for EU and UK buyers, owner to decide** (T035, T036): a confirmation of the contract on a durable medium at payment (Art. 8(7); the Stripe receipt and Stripe's record of the ticked box are evidence for the seller, not that confirmation); an online "withdraw from contract here" function with a refund process (Art. 11a, applies from 19 June 2026); the trader's geographical address and telephone number in the Terms (Art. 6(1)(c)); the withdrawal information and model form in the Terms (Art. 6(1)(h)).
