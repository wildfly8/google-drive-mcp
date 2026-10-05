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

3a. Customer portal (so subscribers can cancel): Stripe Dashboard → Settings → Billing → Customer portal. Allow cancelling subscriptions **at the end of the billing period**, allow updating the payment method, save in **live mode**, and turn on the portal link in customer emails. Until it is saved in live mode, **Manage or cancel subscription** answers 503 and points subscribers to their receipt email.
3b. Also in Secret Manager: `MCP_AUTH_TOKEN` (at least 32 random characters; it derives the signing key unless `MCP_OAUTH_SIGNING_KEY` is set, and the server refuses to start with less) and `DRIVE_ALLOWED_FOLDER_ID` (the kb folder id; the deploy reads it from there, never from the repo).
3c. Terms consent (FR-019): Stripe Dashboard → Settings → Business → Public details → Terms of service URL = `https://wisdomspringtech.github.io/terms.html` (and the Privacy policy URL). Checkout then shows a required box that accepts the Terms and asks for access to start at once. Without the URL Stripe answers 400 to every Checkout and `/subscribe/checkout` answers 503 (`stripe_checkout_failed` with `http_status` 400 in Cloud Logging; the message is in Stripe's Developers → Logs). Test mode shares this setting with live mode, but a Stripe Sandbox does not: set the URL in each Sandbox too.
4. Webhook endpoint: `https://<origin>/webhooks/stripe` events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`.
5. Deploy. Open `/setup` with no payment cookie — fee and `/subscribe` only. After Checkout, `/setup` shows Claude, ChatGPT, and Cursor steps. An assistant that already connected keeps working while Stripe shows the subscription active. Another browser continues the same subscription through an emailed one-time sign-in link. Each Connect asks the subscriber to click Allow.
6. Test mode: pay, then Claude Connect. Unpaid Connect must fail.

Automated: `uv run pytest tests/contract/test_subscription_http.py tests/contract/test_subscription_cancel.py tests/unit/billing -q` (the cancel file drives the real Stripe gateway against a faked Stripe HTTP API through cancel at period end, immediate cancel, failed renewal, trial and outages)

## Email sign-in links (continue a subscription in another browser)

1. In the GCP project: enable `identitytoolkit.googleapis.com` and `apikeys.googleapis.com`, initialize Identity Platform (`identityPlatform:initializeAuth`), enable Email sign-in without a password, and add the Cloud Run host to authorized domains.
2. Create an API key restricted to `identitytoolkit.googleapis.com` and store it as the `IDENTITY_TOOLKIT_API_KEY` secret. `scripts/deploy-cloud-run.sh` binds it when present.
3. Google sends the email from `noreply@<project>.firebaseapp.com`; the link passes through Google's handler on `<project>.firebaseapp.com` to `/subscribe/email/verify`.

