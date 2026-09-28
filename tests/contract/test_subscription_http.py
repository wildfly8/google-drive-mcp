"""Paid subscription gate on MCP OAuth."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

from starlette.testclient import TestClient

from fakes.fake_billing import FakeBilling
from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    ENTITLEMENT_TTL,
    RESUME_COOKIE,
    mint_entitlement,
)
from google_drive_mcp.infra.mcp_auth.provider import DriveMcpOAuthProvider
from google_drive_mcp.infra.mcp_auth.tokens import verify_refresh_claims
from google_drive_mcp.infra.billing.stripe_api import verify_stripe_signature
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import streamable_app


def _paid_settings(**kwargs) -> Settings:
    base = Settings.for_tests()
    return base.model_copy(
        update={
            "mcp_subscription_required": True,
            "stripe_price_id": "price_test",
            **kwargs,
        }
    )


def _client(runtime: Runtime) -> TestClient:
    return TestClient(streamable_app(runtime, json_response=True))


def test_unpaid_authorize_redirects_to_subscribe(fake_drive: FakeDrive):
    settings = _paid_settings()
    runtime = Runtime(settings=settings, drive=fake_drive, billing=FakeBilling())
    with _client(runtime) as client:
        registered = client.post(
            "/register",
            json={
                "redirect_uris": ["http://127.0.0.1/callback"],
                "client_name": "paywall-test",
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "none",
                "scope": "drive.read",
            },
        )
        assert registered.status_code == 201
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": registered.json()["client_id"],
                "redirect_uri": "http://127.0.0.1/callback",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}
        assert "/subscribe" in authorize.headers["location"]
        assert "code=" not in authorize.headers["location"]
        page = client.get("/subscribe")
        assert page.status_code == 200
        assert "Pay $20 / month" in page.text
        assert 'href="/setup"' not in page.text


def test_entitled_cookie_allows_connect(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.add("cus_live1")
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    token = mint_entitlement(settings, customer_id="cus_live1")
    with _client(runtime) as client:
        registered = client.post(
            "/register",
            json={
                "redirect_uris": ["http://127.0.0.1/callback"],
                "client_name": "paywall-test",
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "none",
                "scope": "drive.read",
            },
        )
        info = registered.json()
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": info["client_id"],
                "redirect_uri": "http://127.0.0.1/callback",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            cookies={COOKIE_NAME: token},
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}
        loc = authorize.headers["location"]
        assert loc.startswith("http://127.0.0.1/callback")
        assert parse_qs(urlparse(loc).query)["code"]


def test_setup_mentions_fee_when_paywall_on(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    with _client(runtime) as client:
        page = client.get("/setup")
        assert page.status_code == 200
        assert "$20" in page.text
        assert 'href="/subscribe"' in page.text
        assert "/mcp" not in page.text
        assert "Always allow" not in page.text
        assert "Knowing this URL" not in page.text
        assert "Copy" not in page.text
        assert "console.cloud.google.com" not in page.text
        billing.active.add("cus_live1")
        token = mint_entitlement(settings, customer_id="cus_live1")
        paid = client.get("/setup", cookies={COOKIE_NAME: token})
        assert "/mcp" in paid.text
        assert "Always allow" in paid.text
        assert "ChatGPT" in paid.text
        assert "Cursor" in paid.text
        assert "only after payment" in paid.text.lower()
        billing.active.clear()
        inactive = client.get("/setup", cookies={COOKIE_NAME: token})
        assert "/mcp" not in inactive.text
        assert 'href="/subscribe"' in inactive.text
        stats = client.get("/stats")
        body = stats.json()
        assert "stripe" not in json.dumps(body).lower()
        assert "email" not in body
        assert "customer" not in json.dumps(body).lower()


def test_checkout_complete_sets_cookie(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    with _client(runtime) as client:
        started = client.post("/subscribe/checkout", follow_redirects=False)
        assert started.status_code in {302, 303}
        loc = started.headers["location"]
        assert "session_id=" in loc
        done = client.get(loc.replace("http://127.0.0.1", ""), follow_redirects=False)
        if not loc.startswith("/"):
            path = loc.split("127.0.0.1")[-1]
            done = client.get(path)
        assert done.status_code == 200
        assert COOKIE_NAME in done.cookies
        assert "Payment received" in done.text
        assert 'href="/setup"' in done.text


def test_active_email_resumes_connect_without_a_new_charge(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.add("cus_live9")
    billing.emails["payer@example.com"] = "cus_live9"
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "paywall-test",
                "redirect_uri": "http://127.0.0.1/callback",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code == 302
        assert authorize.headers["location"].endswith("/subscribe")
        assert RESUME_COOKIE in authorize.cookies
        before = billing.checkouts
        restored = client.post(
            "/subscribe/restore",
            data={"email": "payer@example.com"},
            follow_redirects=False,
        )
        assert restored.status_code == 303
        assert restored.headers["location"].startswith("/authorize?")
        assert "payer@example.com" not in restored.text
        assert COOKIE_NAME in restored.cookies
        assert billing.checkouts == before
        missing = client.post(
            "/subscribe/restore",
            data={"email": "nobody@example.com"},
            follow_redirects=False,
        )
        assert missing.status_code == 404
        assert "nobody@example.com" not in missing.text
        assert "Pay $20 / month" in missing.text


def test_paid_refresh_token_lasts_while_subscription_can_stay_active():
    settings = _paid_settings()
    provider = DriveMcpOAuthProvider(settings, billing=FakeBilling())
    issued = provider._issue_tokens("host", scid="cus_live1")
    claims = verify_refresh_claims(issued.refresh_token, settings)
    assert claims is not None
    assert claims["exp"] - claims["iat"] == ENTITLEMENT_TTL


def test_webhook_rejects_bad_signature(fake_drive: FakeDrive):
    from pydantic import SecretStr

    settings = _paid_settings(stripe_webhook_secret=SecretStr("whsec_test"))
    runtime = Runtime(settings=settings, drive=fake_drive, billing=FakeBilling())
    with _client(runtime) as client:
        bad = client.post(
            "/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=deadbeef"},
        )
        assert bad.status_code == 400
        payload = b"{}"
        ts = int(time.time())
        sig = hmac.new(
            b"whsec_test",
            f"{ts}.".encode() + payload,
            hashlib.sha256,
        ).hexdigest()
        ok = client.post(
            "/webhooks/stripe",
            content=payload,
            headers={"stripe-signature": f"t={ts},v1={sig}"},
        )
        assert ok.status_code == 200


def test_verify_stripe_signature_unit():
    payload = b'{"type":"ping"}'
    ts = 1_700_000_000
    sig = hmac.new(b"secret", f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    assert verify_stripe_signature(payload, f"t={ts},v1={sig}", "secret", now=ts)
    assert not verify_stripe_signature(payload, f"t={ts},v1=nope", "secret", now=ts)
