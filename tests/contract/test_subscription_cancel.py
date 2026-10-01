"""A Stripe cancellation ends MCP tool access, end to end.

The real StripeHttpGateway parses Stripe's GET /v1/subscriptions replies; only the
network is faked (httpx.MockTransport). The AI chat app keeps a Drive tool working with
the Bearer access token and POST /token refresh, exactly as a host does after Connect.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.auth.handlers import token as sdk_token_handler
from mcp.server.auth.middleware import bearer_auth as sdk_bearer_auth
from pydantic import SecretStr
from starlette.testclient import TestClient

from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.billing import entitlement, routes, stripe_api
from google_drive_mcp.infra.billing.entitlement import COOKIE_NAME, mint_entitlement
from google_drive_mcp.infra.billing.stripe_api import StripeHttpGateway
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth import tokens
from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import streamable_app

CUSTOMER = "cus_QcancelTest0001"
REDIRECT = "http://127.0.0.1/callback"
RESOURCE = "http://127.0.0.1/mcp"
HEADERS_JSON = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}
DAY = 24 * 3600


class _Clock:
    """One frozen wall clock for every JWT exp check: this server's and the MCP SDK's."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._base = int(time.time())
        self._offset = 0
        # entitlement.py and routes.py import _now by name, so each copy is patched.
        for module in (tokens, entitlement, routes):
            monkeypatch.setattr(module, "_now", self.now)
        shim = SimpleNamespace(time=lambda: float(self.now()))
        for module in (sdk_bearer_auth, sdk_token_handler):
            monkeypatch.setattr(module, "time", shim)

    def now(self) -> int:
        return self._base + self._offset

    def advance(self, seconds: int) -> None:
        assert seconds >= 0
        self._offset += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    return _Clock(monkeypatch)


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gateway retries Stripe blips with short sleeps; tests need not wait."""
    monkeypatch.setattr(stripe_api, "_RETRY_DELAYS", (0.0, 0.0))


class FakeStripe:
    """Stripe's GET /v1/subscriptions for one customer. Tests mutate the subscription."""

    def __init__(self, clock: _Clock, *, status: str = "active", period_left: int = 20 * DAY):
        self.clock = clock
        self.lookups = 0
        self.outage: str | None = None
        self.blips = 0  # the next N lookups get a 503, then Stripe answers again
        start = clock.now() - 30 * DAY + period_left
        self.period_end = start + 30 * DAY
        self.subscription = {
            "id": "sub_1QcancelTestAbCdEf01",
            "object": "subscription",
            "customer": CUSTOMER,
            "status": status,
            "cancel_at_period_end": False,
            "cancel_at": None,
            "canceled_at": None,
            "ended_at": None,
            "cancellation_details": {"comment": None, "feedback": None, "reason": None},
            "collection_method": "charge_automatically",
            "current_period_start": start,
            "current_period_end": self.period_end,
            "trial_end": self.period_end if status == "trialing" else None,
            "livemode": False,
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": "si_QcancelTestItem01",
                        "object": "subscription_item",
                        "price": {"id": "price_test", "object": "price", "recurring": {}},
                        "current_period_start": start,
                        "current_period_end": self.period_end,
                    }
                ],
            },
        }

    def schedule_cancel(self) -> None:
        """Customer portal "Cancel plan": Stripe keeps it active until the period ends."""
        self.subscription.update(
            cancel_at_period_end=True,
            cancel_at=self.period_end,
            canceled_at=self.clock.now(),
            cancellation_details={
                "comment": None,
                "feedback": None,
                "reason": "cancellation_requested",
            },
        )

    def end_period(self) -> None:
        """Stripe ends a scheduled cancellation once current_period_end has passed."""
        assert self.clock.now() > self.period_end
        self.subscription.update(status="canceled", ended_at=self.period_end)

    def cancel_now(self) -> None:
        """Dashboard or API cancel with no period-end grace."""
        now = self.clock.now()
        self.subscription.update(
            status="canceled",
            cancel_at_period_end=False,
            canceled_at=now,
            ended_at=now,
            cancellation_details={
                "comment": None,
                "feedback": None,
                "reason": "cancellation_requested",
            },
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "api.stripe.com"
        assert request.url.path == "/v1/subscriptions"
        assert request.url.params["status"] == "all"
        assert request.headers["authorization"].startswith("Basic ")
        self.lookups += 1
        if self.blips:
            self.blips -= 1
            error = {"type": "api_error", "message": "Stripe is having trouble."}
            return httpx.Response(503, json={"error": error}, request=request)
        if self.outage == "unreachable":
            raise httpx.ConnectError("api.stripe.com unreachable", request=request)
        if self.outage == "html":
            return httpx.Response(200, text="<html>Service unavailable</html>", request=request)
        if self.outage is not None:
            code = int(self.outage)
            error = {"type": "api_error", "message": "Stripe is having trouble."}
            return httpx.Response(code, json={"error": error}, request=request)
        customer = request.url.params["customer"]
        data = [self.subscription] if customer == self.subscription["customer"] else []
        listing = {"object": "list", "url": "/v1/subscriptions", "has_more": False, "data": data}
        return httpx.Response(200, json=listing, request=request)


def _paid_settings(**kwargs) -> Settings:
    base = Settings.for_tests()
    return base.model_copy(
        update={
            "mcp_subscription_required": True,
            "stripe_price_id": "price_test",
            "stripe_secret_key": SecretStr("sk_test_contract_only"),
            **kwargs,
        }
    )


def _runtime(stripe: FakeStripe, fake_drive: FakeDrive) -> Runtime:
    settings = _paid_settings()
    http = httpx.Client(transport=httpx.MockTransport(stripe))
    billing = StripeHttpGateway(settings, client=http)
    return Runtime(settings=settings, drive=fake_drive, billing=billing)


def _client(runtime: Runtime) -> TestClient:
    return TestClient(streamable_app(runtime, json_response=True))


def _browser(client: TestClient, cookie: str) -> TestClient:
    """The subscriber's browser: it holds only the HttpOnly entitlement cookie."""
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, cookie)
    return client


def _chat_app(client: TestClient) -> TestClient:
    """The AI chat app's back end: Bearer tokens only, never the browser cookie."""
    client.cookies.clear()
    return client


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _register(client: TestClient) -> str:
    registered = _chat_app(client).post(
        "/register",
        json={
            "redirect_uris": [REDIRECT],
            "client_name": "Claude",
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",
            "scope": "drive.read",
        },
    )
    assert registered.status_code == 201, registered.text
    return registered.json()["client_id"]


def _authorize(client: TestClient, cookie: str, client_id: str, challenge: str):
    return _browser(client, cookie).get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st",
            "scope": "drive.read",
            "resource": RESOURCE,
        },
        follow_redirects=False,
    )


def _connect(client: TestClient, cookie: str) -> dict:
    """Connect as an AI chat app does: register, /authorize, Allow, then /token."""
    client_id = _register(client)
    verifier, challenge = _pkce()
    authorize = _authorize(client, cookie, client_id, challenge)
    assert authorize.status_code in {302, 303, 307}
    loc = authorize.headers["location"]
    assert "/consent?ticket=" in loc, loc
    ticket = parse_qs(urlparse(loc).query)["ticket"][0]
    allowed = _browser(client, cookie).post(
        "/consent", data={"ticket": ticket}, follow_redirects=False
    )
    assert allowed.status_code == 303, allowed.text
    code = parse_qs(urlparse(allowed.headers["location"]).query)["code"][0]
    token = _chat_app(client).post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )
    assert token.status_code == 200, token.text
    return {**token.json(), "client_id": client_id}


def _refresh(client: TestClient, issued: dict):
    return _chat_app(client).post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": issued["refresh_token"],
            "client_id": issued["client_id"],
            "resource": RESOURCE,
        },
    )


def _refreshed(client: TestClient, issued: dict) -> dict:
    refreshed = _refresh(client, issued)
    assert refreshed.status_code == 200, refreshed.text
    # The refresh token rotates, so the next refresh must use the new one.
    return {**issued, **refreshed.json()}


def _assert_retry_later(response) -> None:
    """Stripe could not be asked: no token, but not invalid_grant, which hosts treat
    as final. A 503 with Retry-After makes the AI chat app try the same token again."""
    assert response.status_code == 503, response.text
    assert response.json()["error"] == "temporarily_unavailable"
    assert response.headers.get("retry-after")
    assert "access_token" not in response.json()


def _assert_refused(response) -> None:
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"] == "invalid_grant"
    assert "access_token" not in body


def _call_tool(client: TestClient, access_token: str):
    return _chat_app(client).post(
        "/mcp",
        headers={**HEADERS_JSON, "authorization": f"Bearer {access_token}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "drive_read", "arguments": {"file_id": "nested-doc"}},
        },
    )


def _assert_tool_works(client: TestClient, access_token: str) -> None:
    response = _call_tool(client, access_token)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("error") is None
    result = payload["result"]
    assert not result.get("isError"), result
    assert "alpha idempotency" in json.dumps(result)


def _assert_tool_refused(client: TestClient, fake_drive: FakeDrive, access_token: str) -> None:
    fake_drive.reset_counters()
    response = _call_tool(client, access_token)
    assert response.status_code == 401, response.text
    assert "resource_metadata" in (response.headers.get("www-authenticate") or "")
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count == 0


def _assert_connect_goes_to_subscribe(client: TestClient, cookie: str) -> None:
    client_id = _register(client)
    _, challenge = _pkce()
    authorize = _authorize(client, cookie, client_id, challenge)
    assert authorize.status_code in {302, 303, 307}
    loc = urlparse(authorize.headers["location"])
    assert loc.path == "/subscribe"
    assert "ticket" not in parse_qs(loc.query)
    assert "code" not in parse_qs(loc.query)


def test_cancel_at_period_end_ends_tool_access_after_the_paid_period(
    fake_drive: FakeDrive, clock: _Clock
):
    stripe = FakeStripe(clock, period_left=1800)  # 30 minutes left in the paid month
    runtime = _runtime(stripe, fake_drive)
    settings = runtime.settings
    ttl = settings.mcp_access_token_ttl_seconds
    cookie = mint_entitlement(settings, customer_id=CUSTOMER)
    with _client(runtime) as client:
        # a) Active subscription: Connect succeeds and a Drive tool works.
        issued = _connect(client, cookie)
        _assert_tool_works(client, issued["access_token"])

        # b) The subscriber cancels in the Stripe portal. Stripe keeps the subscription
        #    "active" with cancel_at_period_end until the period they paid for ends.
        stripe.schedule_cancel()
        clock.advance(600)
        lookups = stripe.lookups
        issued = _refreshed(client, issued)
        assert stripe.lookups == lookups + 1  # every refresh asks Stripe
        _assert_tool_works(client, issued["access_token"])
        last_access = issued["access_token"]
        last_exp = decode_jwt(last_access, tokens.signing_key(settings))["exp"]

        # c) The period ends and Stripe marks the subscription "canceled".
        clock.advance(stripe.period_end - clock.now() + 1)
        stripe.end_period()
        _assert_refused(_refresh(client, issued))
        _assert_connect_goes_to_subscribe(client, cookie)
        setup = _browser(client, cookie).get("/setup")
        assert setup.status_code == 200
        assert RESOURCE not in setup.text and "/mcp" not in setup.text
        assert 'href="/subscribe"' in setup.text

        # d) The last access token, issued before the period ended, works only until
        #    its exp: at most one access-token lifetime after the period end.
        assert stripe.period_end < last_exp <= stripe.period_end + ttl
        _assert_tool_works(client, last_access)
        clock.advance(last_exp - clock.now())
        _assert_tool_works(client, last_access)  # exp itself is the last valid second
        clock.advance(1)
        _assert_tool_refused(client, fake_drive, last_access)
        # Refresh still cannot bring access back.
        _assert_refused(_refresh(client, issued))


def test_immediate_cancel_ends_refresh_at_once(fake_drive: FakeDrive, clock: _Clock):
    stripe = FakeStripe(clock)
    runtime = _runtime(stripe, fake_drive)
    cookie = mint_entitlement(runtime.settings, customer_id=CUSTOMER)
    with _client(runtime) as client:
        issued = _connect(client, cookie)
        _assert_tool_works(client, issued["access_token"])
        stripe.cancel_now()
        _assert_refused(_refresh(client, issued))
        _assert_connect_goes_to_subscribe(client, cookie)
        # The access token already held lapses at its exp, with no refresh to renew it.
        clock.advance(runtime.settings.mcp_access_token_ttl_seconds + 1)
        _assert_tool_refused(client, fake_drive, issued["access_token"])


@pytest.mark.parametrize("status", ["past_due", "unpaid"])
def test_failed_renewal_ends_refresh(fake_drive: FakeDrive, clock: _Clock, status: str):
    stripe = FakeStripe(clock)
    runtime = _runtime(stripe, fake_drive)
    cookie = mint_entitlement(runtime.settings, customer_id=CUSTOMER)
    with _client(runtime) as client:
        issued = _connect(client, cookie)
        clock.advance(stripe.period_end - clock.now() + 1)
        stripe.subscription["status"] = status  # the renewal charge failed
        _assert_refused(_refresh(client, issued))
        _assert_connect_goes_to_subscribe(client, cookie)


def test_trial_keeps_refresh_working(fake_drive: FakeDrive, clock: _Clock):
    stripe = FakeStripe(clock, status="trialing", period_left=7 * DAY)
    runtime = _runtime(stripe, fake_drive)
    cookie = mint_entitlement(runtime.settings, customer_id=CUSTOMER)
    with _client(runtime) as client:
        issued = _connect(client, cookie)
        clock.advance(runtime.settings.mcp_access_token_ttl_seconds + 1)
        _assert_tool_refused(client, fake_drive, issued["access_token"])
        issued = _refreshed(client, issued)
        _assert_tool_works(client, issued["access_token"])


@pytest.mark.parametrize("outage", ["500", "429", "unreachable"])
def test_stripe_outage_fails_closed(fake_drive: FakeDrive, clock: _Clock, outage: str):
    stripe = FakeStripe(clock)
    runtime = _runtime(stripe, fake_drive)
    cookie = mint_entitlement(runtime.settings, customer_id=CUSTOMER)
    with _client(runtime) as client:
        issued = _connect(client, cookie)
        stripe.outage = outage
        lookups = stripe.lookups
        _assert_retry_later(_refresh(client, issued))
        assert stripe.lookups == lookups + 3  # tried three times, then failed closed
        _assert_connect_goes_to_subscribe(client, cookie)
        # Once Stripe answers again, the same refresh token still works: an outage
        # does not use it up, so the AI chat app needs no new Connect.
        stripe.outage = None
        issued = _refreshed(client, issued)
        _assert_tool_works(client, issued["access_token"])


def test_a_stripe_blip_during_refresh_is_retried(fake_drive: FakeDrive, clock: _Clock):
    stripe = FakeStripe(clock)
    runtime = _runtime(stripe, fake_drive)
    cookie = mint_entitlement(runtime.settings, customer_id=CUSTOMER)
    with _client(runtime) as client:
        first = _connect(client, cookie)
        stripe.blips = 2
        issued = _refreshed(client, first)
        _assert_tool_works(client, issued["access_token"])
        # A successful refresh still rotates: the old refresh token is used up.
        _assert_refused(_refresh(client, first))


def test_malformed_stripe_reply_fails_closed(fake_drive: FakeDrive, clock: _Clock):
    stripe = FakeStripe(clock)
    runtime = _runtime(stripe, fake_drive)
    cookie = mint_entitlement(runtime.settings, customer_id=CUSTOMER)
    with _client(runtime) as client:
        issued = _connect(client, cookie)
        stripe.outage = "html"  # e.g. an egress proxy's 200 HTML page
        _assert_retry_later(_refresh(client, issued))
        stripe.outage = None
        _refreshed(client, issued)
