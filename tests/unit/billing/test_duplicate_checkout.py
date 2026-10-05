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


def test_checkout_requires_terms_consent_and_an_express_request_for_immediate_access():
    from urllib.parse import parse_qs

    from google_drive_mcp.infra.billing.stripe_api import CHECKOUT_TERMS_CONSENT, TERMS_URL

    sent: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == ("POST", "/v1/checkout/sessions")
        sent.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"url": "https://checkout.stripe.com/c/pay/cs_test_1"})

    url = _gateway(handler).create_checkout_url(
        success_url="https://example.test/ok", cancel_url="https://example.test/no", reference="r1"
    )
    assert url == "https://checkout.stripe.com/c/pay/cs_test_1"
    form = sent[0]
    assert form["consent_collection[terms_of_service]"] == ["required"]
    message = form["custom_text[terms_of_service_acceptance][message]"][0]
    assert message == CHECKOUT_TERMS_CONSENT
    # The text replaces Stripe's default Terms line, so it must link the Terms itself.
    assert f"]({TERMS_URL})" in message
    # The buyer asks for access to start at once, and is told what withdrawal costs.
    assert "access to start immediately" in message
    assert "legal right to withdraw within 14 days" in message
    assert "pro-rata charge for the days I had access" in message
    # For a subscription service a ticked box does not end the 14-day right (EU CRD Art. 16(a)
    # and 14(3)), so the text must never tell the buyer they lose it.
    assert "lose" not in message.lower() and "waive" not in message.lower()
    # Stripe caps this custom text at 1,200 characters.
    assert len(message) <= 1200
