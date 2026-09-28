"""A second Checkout for an email that already pays is refunded."""

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


def test_repeat_checkout_refunds_the_new_subscription_and_returns_the_original():
    refunds: list[dict[str, str]] = []
    canceled: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/checkout/sessions/cs_dup" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "status": "complete",
                    "payment_status": "paid",
                    "customer": "cus_new",
                    "customer_details": {"email": "payer@example.com"},
                },
            )
        if path == "/v1/customers" and request.method == "GET":
            assert request.url.params["email"] == "payer@example.com"
            return httpx.Response(200, json={"data": [{"id": "cus_new"}, {"id": "cus_old"}]})
        if path == "/v1/subscriptions" and request.method == "GET":
            customer = request.url.params["customer"]
            if customer == "cus_old":
                return httpx.Response(
                    200, json={"data": [{"id": "sub_old", "status": "active"}]}
                )
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "sub_new",
                            "status": "active",
                            "latest_invoice": "in_new",
                        }
                    ]
                },
            )
        if path == "/v1/invoices/in_new" and request.method == "GET":
            return httpx.Response(200, json={"payment_intent": "pi_new"})
        if path == "/v1/refunds" and request.method == "POST":
            refunds.append(dict(request.url.params) or _form(request))
            return httpx.Response(200, json={"id": "re_new"})
        if path == "/v1/subscriptions/sub_new" and request.method == "DELETE":
            canceled.append(path)
            return httpx.Response(200, json={"id": "sub_new", "status": "canceled"})
        return httpx.Response(404, json={"error": {"message": path}})

    gateway = StripeHttpGateway(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    found = gateway.customer_id_from_checkout_session("cs_dup")
    assert found == ("cus_old", True)
    assert refunds == [{"payment_intent": "pi_new"}]
    assert canceled == ["/v1/subscriptions/sub_new"]


def test_first_checkout_is_not_refunded():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/checkout/sessions/cs_first":
            return httpx.Response(
                200,
                json={
                    "status": "complete",
                    "payment_status": "paid",
                    "customer": "cus_only",
                    "customer_details": {"email": "new@example.com"},
                },
            )
        if path == "/v1/customers":
            return httpx.Response(200, json={"data": [{"id": "cus_only"}]})
        return httpx.Response(404, json={"error": {"message": path}})

    gateway = StripeHttpGateway(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert gateway.customer_id_from_checkout_session("cs_first") == ("cus_only", False)


def _form(request: httpx.Request) -> dict[str, str]:
    return dict(part.split("=", 1) for part in request.content.decode().split("&") if "=" in part)
