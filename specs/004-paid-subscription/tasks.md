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

## Phase 5: US5 public business page

- [x] T011 Static public page `docs/index.html` named WisdomSpringTech, $20/month onto-kb, one subscribe link, no connector URL, no bank/card
- [x] T012 Publish `https://wisdomspringtech.github.io/` from `WisdomSpringTech/wisdomspringtech.github.io` (not `https://wildfly8.github.io/google-drive-mcp/`, which 404s). This repo's token cannot push that org repo.
- [x] T013 Test the page source contains the business name, price, one subscribe link, and no `/setup` URL
- [x] T014 Active subscribers keep access without another checkout: 400-day refresh rotation while Stripe is active, receipt-email restore with no second charge, resume in-progress `/authorize`

## Phase 6: Pickup

- [x] T010 Update `.specify/memory/project-status.md` and `.cursor/rules/spec-kit-sdd.mdc`

## Phase 7: Close paywall bypasses found in the public-repo audit (2026-10-01)

- [x] T018 Remove `POST /subscribe/restore` (email alone granted a subscriber's access) and all passkey routes, code and storage
- [x] T019 `GET /subscribe/complete` grants only the customer who paid in that Checkout Session; no email-based switch, cancel or refund
- [x] T020 Paid `/authorize` always goes to an Allow page (client name, return host, known/unknown); `POST /consent` issues a code only for the same entitled browser while Stripe reports it active; consent pages are not frameable (FR-014)
- [x] T021 Continue a subscription in another browser through a one-time sign-in link emailed by Google Identity Platform: same reply for every email, link sent only to active subscribers after the reply, button landing page, email must match, Identity Platform user deleted, rate limits; `IDENTITY_TOOLKIT_API_KEY` secret bound by deploy
- [x] T022 `scripts/deploy-cloud-run.sh` refuses to deploy without the Stripe key and price instead of deploying a free server (FR-009)
- [x] T023 Security review fixes: rate limiter memory bounded (LRU, idle keys pruned); `/subscribe/complete` checks the session id shape and is rate limited; subscriber lookup by email ignores case (Stripe Search fallback, stored email must match); non-ASCII emails rejected
- [x] T024 Remove the `?entitlement=` URL fallback (middleware and `/setup` / `/subscribe`) and the token shown on `/subscribe/complete`; the cookie is the only source (FR-015)
- [x] T025 Prove cancellation end to end (`tests/contract/test_subscription_cancel.py`, real Stripe gateway, faked Stripe HTTP): cancel at period end, immediate cancel, past_due, unpaid, trialing, Stripe 500/429/unreachable/non-JSON (SC-004)
- [x] T026 Fix re-subscribe after a lapse: cookie renewal no longer overwrites an entitlement a route just set; the resume cookie is also set when a lapsed cookie is sent to `/subscribe` (US cancel scenario 3, FR-011)
- [x] T027 Stripe calls retry 429/5xx/connect errors briefly and fail closed on malformed replies; the refresh token rotates only after a successful refresh (FR-016)
- [x] T028 `POST /subscribe/manage` opens the Stripe customer portal for this browser's subscriber; **Manage or cancel subscription** on the entitled `/setup`; wording on `/subscribe` and the business page (FR-002)
- [x] T029 Paid `/setup` skips the log scan; paid `/stats` omits console links; the server refuses to start with signing material under 32 characters (FR-006, AC-FR-010)
- [x] T030 Review fixes (2026-10-01): Checkout bound to the browser that started it (`client_reference_id` + `onto_kb_checkout`); cross-site POSTs to `/subscribe/*` refused; `POST /subscribe/signout`; Manage and Sign out for lapsed subscribers on `/subscribe` and `/setup`; Stripe checks off the event loop; refresh tokens reserved during the check and released on failure; 503 `temporarily_unavailable` when Stripe cannot be asked (FR-016, FR-017)
- [x] T031 Web hardening: `SecurityHeadersMiddleware` (`src/google_drive_mcp/mcp/headers.py`) adds frame, CSP, nosniff, referrer and no-store headers to HTML pages that lack them and no-store to any response that sets a cookie; `POST /subscribe/checkout` rate limited per address (10/hour), a lapsed cookie's Stripe customer reused, failures logged by exception type; `POST /subscribe/email` looks up and sends before replying with a 3 s reply floor; `/stats` snapshot off the event loop, stale scan served while one runs; tests in `tests/contract/test_subscription_http.py` (FR-018)

## Phase 8: Logs without emails or keys (2026-10-01)

- [x] T032 Keep typed emails, the Identity Toolkit API key and one-time codes out of Cloud Logging: `httpx`/`httpcore` at `WARNING` (Stripe's email lookup URL), the key sent as `x-goog-api-key` for send, verify and delete, no uvicorn access log; log `stripe_subscription_check_failed` and `stripe_checkout_failed` as JSON `WARNING`s with only the HTTP status or exception type; docstrings say how emails stay out of logs; `tests/unit/test_logging_hygiene.py` drives `/subscribe/email` and its verify step through the real Stripe and Identity Platform adapters over `httpx.MockTransport` at `DEBUG` (FR-004)
- [x] T033 HTML and billing pages send `Referrer-Policy: same-origin` (not `no-referrer`), so browsers without Sec-Fetch-Site (Safari before 16.4, Firefox before 90) still send a real Origin on this site's own forms and pass the same-site check; cross-site navigations still carry no referrer
