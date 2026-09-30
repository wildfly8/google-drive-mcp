# Tasks: Mandatory Paid Subscription

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Phase 1: Setup

- [x] T001 Spec directory `specs/004-paid-subscription/` + `.specify/feature.json`
- [x] T002 Add Settings fields (`MCP_SUBSCRIPTION_REQUIRED`, Stripe secrets, price id)

## Phase 2: Foundation

- [x] T003 Billing gateway protocol + Stripe HTTP implementation + entitlement JWT/cookie
- [x] T004 Pass `scid` through MCP code/access/refresh JWTs in `tokens.py`
- [x] T005 Gate `DriveMcpOAuthProvider.authorize` and `exchange_refresh_token`

## Phase 3: US1–US3 paywall

- [x] T006 HTTP routes `/subscribe`, `/subscribe/checkout`, `/subscribe/complete`, `/webhooks/stripe`
- [x] T007 Contract tests: unpaid authorize blocked; entitled Connect; webhook sig

## Phase 4: US4 setup copy

- [x] T008 `/setup` paywall copy + README + `.env.example` + deploy env/secrets
- [x] T009 Tests that `/setup` mentions $10 and `/stats` has no billing PII

## Phase 5: US5 public business page

- [x] T011 Static public page `docs/index.html` named WisdomSpringTech, $10/month onto-kb, one subscribe link, no connector URL, no bank/card
- [x] T012 Publish `https://wisdomspringtech.github.io/` from `WisdomSpringTech/wisdomspringtech.github.io` (not `https://wildfly8.github.io/google-drive-mcp/`, which 404s). This repo's token cannot push that org repo.
- [x] T013 Test the page source contains the business name, price, one subscribe link, and no `/setup` URL
- [x] T014 Active subscribers keep access without another checkout: 400-day refresh rotation while Stripe is active, receipt-email restore with no second charge, resume in-progress `/authorize`

## Phase 6: Pickup

- [x] T010 Update `.specify/memory/project-status.md` and `.cursor/rules/spec-kit-sdd.mdc`

## Phase 7: Price change to USD 10 (2026-09-30)

- [x] T015 Lower the advertised price from USD 20 to USD 10 per month in `/subscribe`, `/setup`, tests, `docs/index.html`, README, and the 004 artifacts
- [ ] T016 Operator: create a USD 10 / month recurring Price on the onto-kb product in Stripe, add it as a new `STRIPE_PRICE_ID` secret version, and redeploy. The code never sets the amount; Checkout charges whatever that Price says. Existing subscribers stay on the old Price until moved in Stripe.
- [ ] T017 Republish `index.html` on `WisdomSpringTech/wisdomspringtech.github.io` with the USD 10 copy from `docs/index.html` (this repo's token cannot push that org repo)
