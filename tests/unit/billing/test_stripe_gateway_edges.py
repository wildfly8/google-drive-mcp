"""StripeHttpGateway on the replies that decide access.

A subscription check that Stripe cannot answer is never "active", and a Checkout session
grants access only when it is complete and paid and carries this browser's reference. The
contract tests use a fake gateway; these run the real one against canned Stripe replies.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from google_drive_mcp.infra.billing import stripe_api
from google_drive_mcp.infra.billing.stripe_api import StripeHttpGateway
from google_drive_mcp.infra.config import Settings

REFERENCE = "ref-browser-1"


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stripe_api, "_RETRY_DELAYS", (0.0, 0.0))


def _gateway(handler) -> StripeHttpGateway:
    settings = Settings.for_tests().model_copy(
        update={
            "mcp_subscription_required": True,
            "stripe_secret_key": SecretStr("sk_test_gateway_edges"),
            "stripe_price_id": "price_test",
        }
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return StripeHttpGateway(settings, client=http)


def _answers(status: int, payload=None, *, text: str | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status, text=text, request=request)
        return httpx.Response(status, json=payload, request=request)

    return handler


def _times_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        _answers(500, {"error": {}}),
        _answers(503, {"error": {}}),
        _answers(401, {"error": {}}),
        _times_out,
        _answers(200, text="<html>not json</html>"),
        _answers(200, {"object": "list"}),
        _answers(200, {"data": "nope"}),
    ],
    ids=["500", "503", "401", "timeout", "html", "no-data", "data-not-a-list"],
)
def test_a_check_stripe_cannot_answer_is_not_active(handler):
    gateway = _gateway(handler)
    assert gateway.is_subscription_active("cus_x") is False
    assert gateway.subscription_state("cus_x") is None


@pytest.mark.parametrize(
    ("status", "entitled"),
    [
        ("active", True),
        ("trialing", True),
        ("canceled", False),
        ("past_due", False),
        ("unpaid", False),
        ("incomplete", False),
        ("incomplete_expired", False),
        ("paused", False),
    ],
)
def test_only_active_and_trialing_subscriptions_count(status: str, entitled: bool):
    gateway = _gateway(_answers(200, {"data": [{"status": status}]}))
    assert gateway.is_subscription_active("cus_x") is entitled


def _session(**changes) -> dict:
    body = {
        "id": "cs_test_1",
        "status": "complete",
        "payment_status": "paid",
        "client_reference_id": REFERENCE,
        "customer": "cus_paid1",
    }
    body.update(changes)
    return body


@pytest.mark.parametrize(
    ("changes", "customer"),
    [
        ({}, "cus_paid1"),
        ({"payment_status": "no_payment_required"}, "cus_paid1"),
        ({"status": "open"}, None),
        ({"status": "open", "payment_status": "no_payment_required"}, None),
        ({"status": "expired", "payment_status": "unpaid"}, None),
        ({"payment_status": "unpaid"}, None),
        ({"client_reference_id": "someone-elses-browser"}, None),
        ({"client_reference_id": None}, None),
        ({"customer": None}, None),
        ({"customer": "acct_not_a_customer"}, None),
    ],
    ids=[
        "complete-paid",
        "complete-free",
        "open-paid",
        "open-free",
        "expired",
        "unpaid",
        "other-browser",
        "no-reference",
        "no-customer",
        "not-a-customer-id",
    ],
)
def test_a_checkout_session_grants_access_only_when_complete_paid_and_ours(changes, customer):
    gateway = _gateway(_answers(200, _session(**changes)))
    assert gateway.customer_id_from_checkout_session("cs_test_1", reference=REFERENCE) == customer


def test_a_checkout_session_stripe_cannot_find_grants_nothing():
    gateway = _gateway(_answers(404, {"error": {}}))
    assert gateway.customer_id_from_checkout_session("cs_test_1", reference=REFERENCE) is None
    assert _gateway(_times_out).customer_id_from_checkout_session("cs_test_1", reference=REFERENCE) is None
