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
- [x] T009 Tests that `/setup` mentions $20 and `/stats` has no billing PII

## Phase 5: Pickup

- [x] T010 Update `.specify/memory/project-status.md` and `.cursor/rules/spec-kit-sdd.mdc`
