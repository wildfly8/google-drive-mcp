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

**Rationale**: Claude's `/token` and `/mcp` run from Anthropic's cloud (no cookie). The user's browser hits `/authorize` after checkout, so a signed cookie works there. Access/refresh JWTs carry `scid` so refresh can re-query Stripe.

**Alternatives considered**: License key paste on `/consent` — allowed as fallback (`entitlement` query param / form field).

## Decision: Paywall is independent of `MCP_OAUTH_AUTO_APPROVE`

**Rationale**: FR-009. Auto-approve without payment would zero the fee.

## Decision: Fake Stripe in unit/contract tests

**Rationale**: CI must not need live Stripe. Production uses secret keys in Secret Manager.
