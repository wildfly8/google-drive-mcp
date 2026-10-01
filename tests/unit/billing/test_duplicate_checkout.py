"""Checkout grants access only to the customer who paid in that session."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from google_drive_mcp.infra.billing.stripe_api import StripeHttpGateway
from google_drive_mcp.infra.config import Settings


def _settings() -> Settings:
    return Settings.for_tests().model_copy(
        update={
            "stripe_secret_key": SecretStr("sk_test_x"),
            "stripe_price_id": "price_test",
        }
    )


def _gateway(handler) -> StripeHttpGateway:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return StripeHttpGateway(_settings(), client=client)


def test_checkout_with_a_subscribers_email_never_switches_customers():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/checkout/sessions/cs_dup":
            return httpx.Response(
                200,
                json={
                    "status": "complete",
                    "payment_status": "paid",
                    "customer": "cus_new",
                    "client_reference_id": "browser-ref",
                    # An unverified email that belongs to another active subscriber.
                    "customer_details": {"email": "payer@example.com"},
                },
            )
        raise AssertionError(f"unexpected Stripe call {request.method} {request.url.path}")

    gateway = _gateway(handler)
    assert gateway.customer_id_from_checkout_session("cs_dup", reference="browser-ref") == "cus_new"
    # No customer search by email, no refund, no cancellation.
    assert calls == [("GET", "/v1/checkout/sessions/cs_dup")]
    # A browser that did not start this Checkout gets nothing from its success link.
    assert gateway.customer_id_from_checkout_session("cs_dup", reference="other") is None
    assert gateway.customer_id_from_checkout_session("cs_dup", reference="") is None


def test_unpaid_or_incomplete_checkout_grants_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.url.path.rsplit("/", 1)[-1]
        states = {
            "cs_open": {"status": "open", "payment_status": "unpaid", "customer": "cus_a"},
            "cs_unpaid": {"status": "complete", "payment_status": "unpaid", "customer": "cus_b"},
            "cs_nocus": {"status": "complete", "payment_status": "paid", "customer": None},
            "cs_noref": {"status": "complete", "payment_status": "paid", "customer": "cus_c"},
        }
        body = dict(states[sid])
        if sid != "cs_noref":
            body["client_reference_id"] = "ref"
        return httpx.Response(200, json=body)

    gateway = _gateway(handler)
    for sid in ("cs_open", "cs_unpaid", "cs_nocus", "cs_noref"):
        assert gateway.customer_id_from_checkout_session(sid, reference="ref") is None, sid


def test_email_lookup_ignores_case_through_search():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/customers":
            # Stripe's list filter matches the stored "Payer@Example.com" exactly.
            return httpx.Response(200, json={"data": []})
        if request.url.path == "/v1/customers/search":
            assert request.url.params["query"] == "email:'payer@example.com'"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "cus_other", "email": "someone@example.com"},
                        {"id": "cus_payer", "email": "Payer@Example.com"},
                    ]
                },
            )
        if request.url.path == "/v1/subscriptions":
            active = request.url.params["customer"] in {"cus_payer", "cus_other"}
            status = "active" if active else "canceled"
            return httpx.Response(200, json={"data": [{"status": status}]})
        raise AssertionError(request.url.path)

    gateway = _gateway(handler)
    # A search hit whose stored email differs is never used.
    assert gateway.active_customer_id_for_email("payer@example.com") == "cus_payer"
    assert gateway.active_customer_id_for_email("Kate@example.com") is None
