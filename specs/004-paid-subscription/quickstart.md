# Quickstart: 004 Paid Subscription

1. Create a Stripe account. Complete identity + payout onboarding (Stripe Dashboard — not this repo).
2. Create a product **onto-kb** with a **USD 20 / month** recurring price. Copy `price_…`.
3. Secret Manager (or env):

```
STRIPE_SECRET_KEY=sk_test_…
STRIPE_WEBHOOK_SECRET=whsec_…
STRIPE_PRICE_ID=price_…
MCP_SUBSCRIPTION_REQUIRED=true
```

4. Webhook endpoint: `https://<origin>/webhooks/stripe` events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`.
5. Deploy. Open `/setup` — pay wall copy + `/subscribe`.
6. Test mode: pay, then Claude Connect. Unpaid Connect must fail.

Automated: `uv run pytest tests/contract/test_subscription_http.py tests/unit/billing -q`
