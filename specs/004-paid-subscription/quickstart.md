# Quickstart: 004 Paid Subscription

0. Business website for Stripe: `https://wildfly8.github.io/google-drive-mcp/` — visible name **WisdomSpringTech**. Do not enter `www.example.com`. One-time (repo admin): GitHub → Settings → Pages → Deploy from branch → `gh-pages` → `/ (root)` → Save. The page is already on that branch.
1. Create a Stripe account. Complete identity + payout onboarding (Stripe Dashboard — not this repo). Use that Pages URL as the business website.
2. Create a product **onto-kb** with a **USD 20 / month** recurring price. Copy `price_…`.
3. Secret Manager (or env):

```
STRIPE_SECRET_KEY=sk_test_…
STRIPE_WEBHOOK_SECRET=whsec_…
STRIPE_PRICE_ID=price_…
MCP_SUBSCRIPTION_REQUIRED=true
```

4. Webhook endpoint: `https://<origin>/webhooks/stripe` events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`.
5. Deploy. Open `/setup` with no payment cookie — fee and `/subscribe` only. After Checkout, the same browser shows the connector URL.
6. Test mode: pay, then Claude Connect. Unpaid Connect must fail.

Automated: `uv run pytest tests/contract/test_subscription_http.py tests/unit/billing -q`
