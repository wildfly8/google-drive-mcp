# Implementation Plan: Mandatory Paid Subscription

**Branch**: `main` | **Date**: 2026-09-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-paid-subscription/spec.md`

## Summary

Gate MCP Connect on an active **USD 20/month** Stripe Billing subscription. Hosted Checkout collects cards (PCI). This origin never displays the owner's bank or stores PANs. Stripe is the entitlement source of truth. One deployment Google identity is unchanged. PayPal is out of this feature.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: existing Starlette/MCP stack; Stripe API (Checkout Session, customer lookup by email, subscription retrieve, webhook signatures); HS256 JWTs already used for MCP OAuth

**Storage**: None on Cloud Run. Stripe stores customers, emails, and subscriptions. A 400-day signed cookie and the `scid` claim on access/refresh JWTs cache the Stripe customer id only (not Drive content, not email). Refresh tokens that carry `scid` last 400 days and rotate on each successful refresh while the subscription stays active.

**Testing**: pytest + Starlette TestClient; fake Stripe gateway (no live network)

**Target Platform**: Cloud Run (same service `onto-kb`)

**Project Type**: web-service (Streamable HTTP MCP)

**Performance Goals**: entitlement check on `/authorize` and refresh within existing 60s request timeout

**Constraints**: No PAN/bank in logs; `/stats` unchanged; `MCP_OAUTH_AUTO_APPROVE` must not skip the paywall or the subscriber's Allow click; continuing in another browser needs an emailed one-time link (Google Identity Platform)

**Scale/Scope**: one $20/month price; public connector

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Drive remains source of truth; no RAG index — PASS
- Read-only tools unchanged — PASS
- One Google identity per deployment — PASS (paywall is not multi-tenant Drive)
- Article III: Stripe-held billing + signed customer id is an explicit operational exception (like 003 log metrics), not a document cache — PASS
- Authorization independently enforced: unpaid callers never receive a code — PASS
- MINOR Article XIV — PASS

Post-design: same gates hold.

## Project Structure

### Documentation (this feature)

```text
specs/004-paid-subscription/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### Source Code (repository root)

```text
src/google_drive_mcp/infra/billing/
├── __init__.py
├── gateway.py
├── stripe_api.py
├── entitlement.py
└── routes.py
src/google_drive_mcp/infra/config.py
src/google_drive_mcp/infra/mcp_auth/provider.py
src/google_drive_mcp/infra/mcp_auth/tokens.py
src/google_drive_mcp/infra/mcp_auth/setup.py
src/google_drive_mcp/mcp/server.py
src/google_drive_mcp/mcp/middleware.py
tests/contract/test_subscription_http.py
tests/unit/billing/
```

## Complexity Tracking

No unjustified violations.
