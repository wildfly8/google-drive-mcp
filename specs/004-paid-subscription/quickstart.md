# Quickstart: 004 Paid Subscription

0. Business website for Stripe: `https://wisdomspringtech.github.io/` — visible name **WisdomSpringTech**. Do not enter `www.example.com` or `https://wildfly8.github.io/google-drive-mcp/` (that URL 404s). The page is `index.html` on `WisdomSpringTech/wisdomspringtech.github.io` `main`. One subscribe link. No connector URL.
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
5. Deploy. Open `/setup` with no payment cookie — fee and `/subscribe` only. After Checkout, `/setup` shows Claude, ChatGPT, and Cursor steps. An assistant that already connected keeps working while Stripe shows the subscription active. Another browser continues the same subscription through an emailed one-time sign-in link. Each Connect asks the subscriber to click Allow.
6. Test mode: pay, then Claude Connect. Unpaid Connect must fail.

Automated: `uv run pytest tests/contract/test_subscription_http.py tests/unit/billing -q`

## Email sign-in links (continue a subscription in another browser)

1. In the GCP project: enable `identitytoolkit.googleapis.com` and `apikeys.googleapis.com`, initialize Identity Platform (`identityPlatform:initializeAuth`), enable Email sign-in without a password, and add the Cloud Run host to authorized domains.
2. Create an API key restricted to `identitytoolkit.googleapis.com` and store it as the `IDENTITY_TOOLKIT_API_KEY` secret. `scripts/deploy-cloud-run.sh` binds it when present.
3. Google sends the email from `noreply@<project>.firebaseapp.com`; the link passes through Google's handler on `<project>.firebaseapp.com` to `/subscribe/email/verify`.

