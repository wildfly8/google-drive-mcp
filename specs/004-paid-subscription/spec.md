# Feature Specification: Mandatory Paid Subscription (Go-Live Paywall)

**Branch**: `main`

**Spec directory**: `specs/004-paid-subscription`

**Created**: 2026-09-27

**Status**: Implemented (live Stripe secrets bound on Cloud Run revision `onto-kb-00009-dbw`; Connect requires an active subscription)

**Input**: User description: "Add brand new feat 004 to get ready go live to accept mandatory $20 monthly subscription fee via Stripe/PayPal or whatever secure payment approach you recommend as the best payment approach based on the entire context while I don't want to disclose my credit card/bank account or any other PII data to receive mandatory $20/month subscription fee to use my MCP Server."

**Constitution**: Ratified v1.0.0. **MINOR** (Article XIV): paywall on existing MCP Connect. Does not change Drive as source of truth, read-only tools, one Google identity per deployment, or document-as-data. Subscription records are operational entitlements (Article III exception: not a retrieval cache or RAG index). Per-subscriber Google accounts remain out of scope (MAJOR).

**Bounded Context**: Paid entitlement (upstream of Access Control token issuance; does not authorize Drive itself)

**Payment approach (chosen)**: Hosted checkout and recurring billing through a PCI-compliant card processor that is the merchant of record for card data (**Stripe Checkout + Stripe Billing**). Subscribers pay the processor; the processor pays the deployment owner. **PayPal is not the primary processor** (weaker recurring billing, weaker webhook contract, worse binding to MCP Connect). Subscribers never see the owner's bank or card. The owner never sees subscriber card numbers. The owner **must** still complete the processor's legal identity and payout onboarding (that is how USD lands in a bank; this origin cannot and MUST NOT invent an anonymous cash-out).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pay $20/month before Connect works (Priority: P1)

A person who wants onto-kb in Claude (or any MCP host) must complete a **mandatory USD 20 per month** recurring payment on this origin before MCP authorization-code issuance succeeds. Drive tools stay unchanged. Unpaid visitors cannot finish Connect.

**Why this priority**: Go-live income depends on the gate, not on ads or the host vendor sharing revenue.

**Independent Test**: Without an active subscription, start OAuth Connect; it does not yield a usable access token. Complete paid checkout for $20/month, then Connect; an access token is issued and `drive_*` works as today (same deployment Drive identity).

**Acceptance Scenarios**:

1. **Given** no active paid period, **When** a host starts MCP OAuth `/authorize`, **Then** the browser is sent to pay (or shown a pay wall) and no authorization code is issued.
2. **Given** an active $20/month period for that browser session, **When** the host completes authorization-code + PKCE, **Then** an access token is issued as in 001.
3. **Given** a paid subscriber, **When** they call `drive_ls` / `find` / `read` / `grep`, **Then** tools behave as 002 (same one Google identity).
4. **Given** a probe of `/authorize` that never pays, **When** it stops, **Then** `oauth_connects` does not increase.

---

### User Story 2 - Owner never shows bank details; subscriber never shows cards to this origin (Priority: P1)

Payment happens on the processor's hosted checkout. This origin never displays the owner's credit card, bank account, or government id. This origin never collects or stores subscriber primary account numbers (full card numbers) or bank account numbers. Checkout and customer-portal links are the only payment UI.

**Why this priority**: The owner asked not to disclose bank/card/PII **to users of the connector**. Hosted checkout is how that is done.

**Independent Test**: Walk `/setup` and `/subscribe` and the processor checkout. Pages on this origin contain no owner bank/card. Logs and `/stats` contain no subscriber card, bank, email, or processor customer id.

**Acceptance Scenarios**:

1. **Given** `/setup` or `/subscribe`, **When** a visitor reads the page, **Then** they see price ($20/month), what they get, and a pay button — not owner banking details.
2. **Given** checkout, **When** the subscriber enters a card, **Then** that happens on the processor's page, not as card fields hosted by this MCP.
3. **Given** success or failure logs, **When** inspected, **Then** they MUST NOT contain PANs, bank numbers, owner KYC documents, or subscriber emails.

---

### User Story 3 - Cancel and lapse stop new access (Priority: P1)

A subscriber can cancel renewal on the processor's customer portal. Access continues through the already-paid period, then MCP token refresh and new Connect fail until they pay again.

**Why this priority**: Mandatory monthly fee is meaningless if cancel still mints tokens forever.

**Independent Test**: Mark a subscription canceled or unpaid in the processor test environment. Refresh of an old access/refresh token fails. A new Connect fails. Paying again restores Connect.

**Acceptance Scenarios**:

1. **Given** an active subscription, **When** the subscriber cancels renewal, **Then** existing access tokens may work until expiry of the current paid period, and refresh after that period MUST fail.
2. **Given** past_due / unpaid / revoked, **When** `/authorize` or refresh runs, **Then** no new access token is issued.
3. **Given** a later successful $20/month payment, **When** they Connect again, **Then** access is restored.

---

### User Story 4 - Setup page tells hosts to pay first (Priority: P2)

`GET /setup` states that onto-kb is **$20 USD per month** and links to checkout. The connector URL, copy control, Claude steps, OAuth notes, usage counts, and Google Cloud console links are shown only when the request has a valid entitlement cookie and Stripe reports that subscription active. Public `/stats` stays non-PII and MUST NOT list subscribers.

**Why this priority**: Claude users will otherwise Connect and fail without explanation.

**Independent Test**: Open `/setup`. Price and pay link are visible. `/stats` still has only counts and host families.

**Acceptance Scenarios**:

1. **Given** `/setup` without an active entitlement, **When** loaded, **Then** it states the mandatory $20/month fee and links to checkout, and it does not include the connector URL or Claude steps.
2. **Given** `/setup` with a valid entitlement cookie for an active subscription, **When** loaded, **Then** it shows the connector URL and Claude steps.
3. **Given** `/stats`, **When** loaded, **Then** it is unchanged in kind (no emails, customer ids, or payment fields).

---

### User Story 5 - Public business page for processor verification (Priority: P1)

The payment processor requires a public, non-password-protected website whose visible name matches the business **WisdomSpringTech** and that describes what is sold. That page is free to host, separate from the MCP origin, and does not show bank or card details.

**Why this priority**: Account activation blocks go-live until this URL exists. A placeholder such as `www.example.com` is rejected.

**Independent Test**: Open the public business URL in a browser with no login. The page shows WisdomSpringTech, a hosted read-only MCP subscription at USD 20 per month (onto-kb), and a link to the connector setup page. No password prompt. No bank or card numbers.

**Acceptance Scenarios**:

1. **Given** the published business page, **When** a reviewer loads it without credentials, **Then** the business name WisdomSpringTech is visible and the page describes the $20/month onto-kb subscription.
2. **Given** that page, **When** inspected, **Then** it links to the public connector setup URL and does not contain owner bank accounts, card numbers, or a login wall.
3. **Given** the processor business-website field, **When** the owner pastes this URL, **Then** it is a real HTTPS page, not `www.example.com`.

---

### Edge Cases

- Processor webhook delayed: `/authorize` MUST ask the processor for current status (or a short-lived signed entitlement from a completed checkout), not trust only an in-memory flag.
- Cloud Run instance restart: entitlement MUST still be verifiable (processor is source of truth; signed cookies/tokens may cache a customer id, not a homemade ledger of Drive files).
- Auto-approve OAuth without payment: MUST NOT issue a code when the paywall is on.
- Live E2E / owner override: a documented test or owner bypass MAY exist for automated tests; production go-live MUST keep the paywall on.
- Failed or abandoned checkout: no code, no Drive I/O.
- Refunds: treated as not entitled once the processor marks the subscription inactive.
- Currency: USD 20; no other prices in this feature.
- One Google identity: paying does not attach the subscriber's own Drive.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the paywall is enabled, MCP authorization-code issuance MUST require an **active** $20 USD / month entitlement from the payment processor. Token refresh MUST re-check that entitlement.
- **FR-002**: The advertised price MUST be **USD 20 per calendar month**, auto-renewing, cancelable by the subscriber via the processor's customer portal (or equivalent hosted billing portal).
- **FR-003**: Card collection MUST occur on the processor's hosted checkout (PCI). This origin MUST NOT accept card numbers, CVC, or bank account numbers in its own forms.
- **FR-004**: Pages, JSON, logs, metrics, and `/stats` MUST NOT expose owner bank/card/KYC, subscriber PAN/bank, subscriber email, or processor customer ids.
- **FR-005**: Unpaid `/authorize` MUST NOT mint an authorization code. Unpaid refresh MUST NOT mint a new access token.
- **FR-006**: When the paywall is on, `GET /setup` without a valid entitlement cookie for an active subscription MUST show only the fee and a link to checkout. It MUST NOT include the connector URL, copy control, host connection steps, the “knowing this URL is enough” note, usage counts, or Google Cloud console links. Those appear only for an active entitlement. A `GET /subscribe` (or equivalent) MUST start checkout.
- **FR-007**: Drive tools, one deployment Google identity, and Retrieval Core contracts MUST remain as in 001–002. Payment does not expand Google grant.
- **FR-008**: Connect telemetry (003) MUST still count only successful paid Connects (authorization-code token issuance after entitlement).
- **FR-009**: Go-live deploy MUST run with the paywall **on**. `MCP_OAUTH_AUTO_APPROVE` MUST NOT bypass the paywall.
- **FR-010**: Processor webhook (or equivalent signed events) MUST update or confirm entitlement; spoofed unsigned POSTs MUST be rejected.
- **FR-011**: After successful checkout in the subscriber's browser, that browser MUST be able to complete MCP OAuth (cookie or one-time entitlement bound to the checkout) without pasting a card. A displayed one-time code is allowed as fallback if the cookie is missing.
- **FR-012**: The owner MUST be able to open the processor dashboard to see payouts. That dashboard is not this MCP. This origin MUST NOT print payout bank details.
- **FR-013**: A free public HTTPS page MUST show the business name **WisdomSpringTech**, state that the product is a hosted read-only MCP subscription (onto-kb) at USD 20 per month, and link to the connector setup URL. The page MUST be viewable without a password and MUST NOT show owner bank or card details.

### Key Entities

- **Subscription entitlement**: Opaque proof that the current browser/session is tied to an **active** $20/month period. Not a person directory on this origin. Not a Google identity.
- **Paid period**: The current billing interval the processor reports as paid/active.
- **Hosted checkout**: Processor-hosted page that collects subscriber payment instruments.
- **Customer billing portal**: Processor-hosted cancel / update-card page.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new visitor cannot obtain a working MCP access token in under 5 minutes without completing a $20/month payment (test mode allowed in CI).
- **SC-002**: After a successful test payment, a visitor can finish Connect and complete one `drive_*` call within 5 minutes using the existing connector steps.
- **SC-003**: A reviewer of `/setup`, `/subscribe`, `/stats`, and application logs finds zero owner bank/card numbers and zero subscriber card numbers.
- **SC-004**: After the processor marks a subscription inactive, new Connect and token refresh fail within one token lifetime (≤ 1 hour for access tokens).
- **SC-005**: 100% of production Connects that mint tokens have an active paid period at issuance time when the paywall is on.
- **SC-006**: A reviewer can open the public business page with no login and see WisdomSpringTech plus the $20/month onto-kb offer within one page load.

## Assumptions

- Stripe Checkout + Stripe Billing is the processor (best fit: subscriptions, hosted PCI checkout, Customer Portal, signed webhooks). PayPal is deferred.
- The deployment owner will create a Stripe account and complete Stripe's identity + bank **payout** onboarding. That disclosure is to Stripe, not to MCP users. There is no lawful way for this server to receive USD 20/month into a usable account with zero identity to any regulated processor.
- Still one Google Drive identity per deployment (the owner's library). Subscribers pay for **access to that library**, not for linking their own Drive.
- USD only, $20/month, no annual plan in this feature.
- Public `/stats` remains anonymous connect counts.
- Test mode keys are used in automated tests; live keys only on Cloud Run go-live after the owner adds them as secrets.
- Existing Claude connector URL stays `/mcp`. Paywall is extra steps on this origin, not a new MCP protocol.
