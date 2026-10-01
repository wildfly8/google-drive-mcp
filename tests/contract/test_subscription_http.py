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
        assert "not charged again" not in page.text
        assert "passkey" not in page.text.lower()
        # Email sign-in is offered only when the email-link service is configured.
        assert "/subscribe/email" not in page.text
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
        # A paid Connect never issues a code without the subscriber's click.
        assert "/consent?ticket=" in loc
        assert "code=" not in loc
        ticket = parse_qs(urlparse(loc).query)["ticket"][0]
        page = client.get("/consent", params={"ticket": ticket}, cookies={COOKIE_NAME: token})
        assert page.status_code == 200
        assert "Allow this app to use your onto-kb subscription?" in page.text
        assert "paywall-test" in page.text
        assert "127.0.0.1" in page.text and "a known AI chat app address" in page.text
        assert page.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert 'type="password"' not in page.text  # no deployment password for subscribers
        allowed = client.post(
            "/consent",
            data={"ticket": ticket},
            cookies={COOKIE_NAME: token},
            follow_redirects=False,
        )
        assert allowed.status_code == 303
        code_loc = allowed.headers["location"]
        assert code_loc.startswith("http://127.0.0.1/callback")
        assert parse_qs(urlparse(code_loc).query)["code"]


def _authorize_ticket(client, cookie: str, redirect: str = "http://127.0.0.1/callback") -> str:
    registered = client.post(
        "/register",
        json={
            "redirect_uris": [redirect],
            "client_name": "Claude",
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",
            "scope": "drive.read",
        },
    )
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registered.json()["client_id"],
            "redirect_uri": redirect,
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            "scope": "drive.read",
            "resource": "http://127.0.0.1/mcp",
        },
        cookies={COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    return parse_qs(urlparse(authorize.headers["location"]).query)["ticket"][0]


def test_allow_needs_the_same_paying_browser(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.update({"cus_victim", "cus_other"})
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    victim = mint_entitlement(settings, customer_id="cus_victim")
    other = mint_entitlement(settings, customer_id="cus_other")
    with _client(runtime) as client:
        ticket = _authorize_ticket(client, victim)
        for cookies in ({}, {COOKIE_NAME: other}):
            client.cookies.clear()  # only the cookie under test is sent
            refused = client.post(
                "/consent", data={"ticket": ticket}, cookies=cookies, follow_redirects=False
            )
            assert refused.status_code == 400
            assert "code=" not in refused.headers.get("location", "")
        billing.active.discard("cus_victim")
        client.cookies.clear()
        lapsed = client.post(
            "/consent",
            data={"ticket": ticket},
            cookies={COOKIE_NAME: victim},
            follow_redirects=False,
        )
        assert lapsed.status_code == 400


def test_allow_page_flags_an_unknown_return_address(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.add("cus_victim")
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    victim = mint_entitlement(settings, customer_id="cus_victim")
    with _client(runtime) as client:
        ticket = _authorize_ticket(client, victim, redirect="https://claude.ai.evil.example/cb")
        page = client.get("/consent", params={"ticket": ticket}, cookies={COOKIE_NAME: victim})
        assert "claude.ai.evil.example" in page.text
        assert "not a known AI chat app address" in page.text


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
        assert "AI chat app" in paid.text
        assert "only after payment" in paid.text.lower()
        assert "MCP_AUTH_TOKEN" not in paid.text
        assert "Non-PII usage" not in paid.text
        assert "not unique people" not in paid.text
        assert ">JSON</a>" not in paid.text
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
        # The entitlement lives only in the HttpOnly cookie, never on the page.
        assert done.cookies[COOKIE_NAME] not in done.text
        assert "Fallback entitlement" not in done.text


def test_entitlement_in_the_url_is_ignored(fake_drive: FakeDrive):
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
                "entitlement": token,
            },
            follow_redirects=False,
        )
        assert authorize.headers["location"] == "/subscribe"
        assert COOKIE_NAME not in authorize.cookies
        setup = client.get("/setup", params={"entitlement": token})
        assert "/mcp" not in setup.text
        assert COOKIE_NAME not in setup.cookies
        subscribe = client.get(
            "/subscribe", params={"entitlement": token}, follow_redirects=False
        )
        assert subscribe.status_code == 200
        assert COOKIE_NAME not in subscribe.cookies
        # A valid Allow ticket still needs the cookie; the URL value does not count.
        ticket = _authorize_ticket(client, token)
        client.cookies.clear()
        refused = client.post(
            "/consent",
            params={"entitlement": token},
            data={"ticket": ticket},
            follow_redirects=False,
        )
        assert refused.status_code == 400


def _email_runtime(fake_drive: FakeDrive):
    from fakes.fake_billing import FakeEmailLink

    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.add("cus_live9")
    billing.emails["payer@example.com"] = "cus_live9"
    email_link = FakeEmailLink()
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing, email_link=email_link)
    return settings, billing, email_link, runtime


def test_email_alone_never_grants_access(fake_drive: FakeDrive):
    settings, billing, email_link, runtime = _email_runtime(fake_drive)
    with _client(runtime) as client:
        page = client.get("/subscribe")
        assert 'action="/subscribe/email"' in page.text
        for email in ("payer@example.com", "nobody@example.com"):
            sent = client.post("/subscribe/email", data={"email": email}, follow_redirects=False)
            # Same reply either way, no entitlement, the email is not echoed.
            assert sent.status_code == 200
            assert COOKIE_NAME not in sent.cookies
            assert email not in sent.text
            assert "one-time sign-in link" in sent.text
        # Only the subscriber's address got a link.
        assert [address for address, _ in email_link.sent] == ["payer@example.com"]
        assert email_link.sent[0][1].endswith("/subscribe/email/verify")
        # The removed shortcuts are gone.
        restore = client.post("/subscribe/restore", data={"email": "payer@example.com"})
        assert restore.status_code in {404, 405}
        assert client.post("/subscribe/passkey/options").status_code in {404, 405}


def test_email_link_continues_the_subscription_in_this_browser(fake_drive: FakeDrive):
    settings, billing, email_link, runtime = _email_runtime(fake_drive)
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
        assert authorize.headers["location"].endswith("/subscribe")
        client.post("/subscribe/email", data={"email": "payer@example.com"})
        code = next(iter(email_link.codes))
        landing = client.get("/subscribe/email/verify", params={"oobCode": code, "mode": "signIn"})
        # Opening the link does not sign in by itself (mail scanners open links).
        assert landing.status_code == 200
        assert COOKIE_NAME not in landing.cookies
        assert "Continue in this browser" in landing.text
        assert landing.headers["referrer-policy"] == "no-referrer"
        before = billing.checkouts
        done = client.post(
            "/subscribe/email/verify", data={"oobCode": code}, follow_redirects=False
        )
        assert done.status_code == 303
        assert done.headers["location"].startswith("/authorize?")
        from google_drive_mcp.infra.billing.entitlement import verify_entitlement

        assert verify_entitlement(done.cookies[COOKIE_NAME], settings) == "cus_live9"
        assert billing.checkouts == before
        # The link works once.
        again = client.post(
            "/subscribe/email/verify", data={"oobCode": code}, follow_redirects=False
        )
        assert again.status_code == 400


def test_email_link_needs_the_address_it_was_sent_to(fake_drive: FakeDrive):
    settings, billing, email_link, runtime = _email_runtime(fake_drive)
    with _client(runtime) as client:
        client.post("/subscribe/email", data={"email": "payer@example.com"})
        code = next(iter(email_link.codes))
    # A different browser (no email cookie) must type the address, and only that one works.
    with _client(runtime) as other:
        landing = other.get("/subscribe/email/verify", params={"oobCode": code})
        assert 'name="email"' in landing.text
        wrong = other.post(
            "/subscribe/email/verify",
            data={"oobCode": code, "email": "attacker@example.com"},
            follow_redirects=False,
        )
        assert wrong.status_code == 400
        assert COOKIE_NAME not in wrong.cookies
        right = other.post(
            "/subscribe/email/verify",
            data={"oobCode": code, "email": "payer@example.com"},
            follow_redirects=False,
        )
        assert right.status_code == 303


def test_email_requests_are_rate_limited(fake_drive: FakeDrive):
    from google_drive_mcp.infra.billing import routes

    routes._LIMITS = routes._RateLimit()
    settings, billing, email_link, runtime = _email_runtime(fake_drive)
    with _client(runtime) as client:
        for _ in range(5):
            reply = client.post("/subscribe/email", data={"email": "payer@example.com"})
            assert reply.status_code == 200
    assert len(email_link.sent) == 3


def test_repeat_checkout_grants_only_the_paying_customer(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.update({"cus_old", "cus_new"})
    billing.emails["payer@example.com"] = "cus_old"
    billing.sessions["cs_test_duplicate000001"] = "cus_new"
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    with _client(runtime) as client:
        done = client.get("/subscribe/complete", params={"session_id": "cs_test_duplicate000001"})
        assert done.status_code == 200
        assert "Payment received" in done.text
        assert "refunded" not in done.text
        from google_drive_mcp.infra.billing.entitlement import verify_entitlement

        assert verify_entitlement(done.cookies[COOKIE_NAME], settings) == "cus_new"


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


def test_rate_limiter_stays_bounded_under_many_addresses():
    from google_drive_mcp.infra.billing.routes import _RateLimit

    limiter = _RateLimit(max_keys=100)
    for n in range(5000):
        assert limiter.allow(f"ip:10.0.{n // 256}.{n % 256}", 3, 3600)
    assert len(limiter) <= 100
    for _ in range(3):
        limiter.allow("email:x", 3, 900)
    assert not limiter.allow("email:x", 3, 900)


def test_malformed_checkout_session_ids_never_reach_stripe(fake_drive: FakeDrive):
    settings = _paid_settings()

    class _Spy(FakeBilling):
        def __init__(self) -> None:
            super().__init__()
            self.lookups = 0

        def customer_id_from_checkout_session(self, session_id: str) -> str | None:
            self.lookups += 1
            return super().customer_id_from_checkout_session(session_id)

    billing = _Spy()
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    with _client(runtime) as client:
        for bad in ("", "cs_x", "cus_123", "cs_live_" + "a" * 300, "cs_test_abc/../x"):
            page = client.get("/subscribe/complete", params={"session_id": bad})
            assert page.status_code == 400
            assert COOKIE_NAME not in page.cookies
    assert billing.lookups == 0


def test_non_ascii_emails_are_rejected(fake_drive: FakeDrive):
    settings, billing, email_link, runtime = _email_runtime(fake_drive)
    with _client(runtime) as client:
        # U+212A KELVIN SIGN lower-cases to "k".
        reply = client.post("/subscribe/email", data={"email": "Kate@example.com"})
        assert reply.status_code == 400
    assert email_link.sent == []


def _jar_customer(client: TestClient, settings: Settings) -> str | None:
    from google_drive_mcp.infra.billing.entitlement import verify_entitlement

    return verify_entitlement(client.cookies.get(COOKIE_NAME), settings)


def test_lapsed_subscriber_who_pays_again_gets_the_new_subscription(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    lapsed = mint_entitlement(settings, customer_id="cus_old")  # canceled, period over
    with _client(runtime) as client:
        client.cookies.set(COOKIE_NAME, lapsed, domain="testserver.local")
        registered = client.post(
            "/register",
            json={
                "redirect_uris": ["http://127.0.0.1/callback"],
                "client_name": "Claude",
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "none",
                "scope": "drive.read",
            },
        )
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
        assert urlparse(authorize.headers["location"]).path == "/subscribe"
        # The in-progress Connect is remembered even though the browser has a cookie.
        assert "onto_kb_resume" in authorize.cookies
        started = client.post("/subscribe/checkout", follow_redirects=False)
        done = client.get(started.headers["location"].replace("http://127.0.0.1", ""))
        assert done.status_code == 200
        # The new subscription's cookie wins over the renewal of the lapsed one.
        assert _jar_customer(client, settings) == "cus_test_1"
        assert "/authorize?" in done.text  # back to the Connect that was started
        resumed = client.get(
            "/authorize?" + str(authorize.request.url.query, "ascii"), follow_redirects=False
        )
        assert "/consent?ticket=" in resumed.headers["location"]


def test_email_link_replaces_a_lapsed_cookie(fake_drive: FakeDrive):
    settings, billing, email_link, runtime = _email_runtime(fake_drive)
    with _client(runtime) as client:
        billing.emails["lapsed@example.com"] = "cus_live9"
        lapsed = mint_entitlement(settings, customer_id="cus_old")
        client.cookies.set(COOKIE_NAME, lapsed, domain="testserver.local")
        client.post("/subscribe/email", data={"email": "lapsed@example.com"})
        code = next(iter(email_link.codes))
        done = client.post(
            "/subscribe/email/verify",
            data={"oobCode": code, "email": "lapsed@example.com"},
            follow_redirects=False,
        )
        assert done.status_code == 303
        assert _jar_customer(client, settings) == "cus_live9"


def test_manage_opens_the_stripe_portal_for_this_browser_only(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.add("cus_live1")
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    token = mint_entitlement(settings, customer_id="cus_live1")
    with _client(runtime) as client:
        setup = client.get("/setup", cookies={COOKIE_NAME: token})
        assert 'action="/subscribe/manage"' in setup.text
        assert "Manage or cancel subscription" in setup.text
        client.cookies.clear()
        opened = client.post(
            "/subscribe/manage", cookies={COOKIE_NAME: token}, follow_redirects=False
        )
        assert opened.status_code == 303
        assert opened.headers["location"].startswith("https://billing.stripe.test/")
        assert billing.portals == ["cus_live1"]
        client.cookies.clear()
        stranger = client.post("/subscribe/manage", follow_redirects=False)
        assert stranger.status_code == 403
        assert billing.portals == ["cus_live1"]
        billing.portal_ready = False
        client.cookies.clear()
        missing = client.post(
            "/subscribe/manage", cookies={COOKIE_NAME: token}, follow_redirects=False
        )
        assert missing.status_code == 503
        assert "receipt email" in missing.text
        # The subscribe page tells people where to cancel.
        client.cookies.clear()
        assert "Manage or cancel" in client.get("/subscribe").text


def test_paid_connect_counts_once_and_a_lapsed_exchange_counts_nothing(fake_drive: FakeDrive):
    import base64
    import hashlib
    import secrets

    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.add("cus_live1")
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    token = mint_entitlement(settings, customer_id="cus_live1")

    def connect(client) -> int:
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        client.cookies.clear()
        registered = client.post(
            "/register",
            json={
                "redirect_uris": ["http://127.0.0.1/callback"],
                "client_name": "Claude",
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "none",
                "scope": "drive.read",
            },
        )
        client_id = registered.json()["client_id"]
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            cookies={COOKIE_NAME: token},
            follow_redirects=False,
        )
        ticket = parse_qs(urlparse(authorize.headers["location"]).query)["ticket"][0]
        allowed = client.post(
            "/consent",
            data={"ticket": ticket},
            cookies={COOKIE_NAME: token},
            follow_redirects=False,
        )
        code = parse_qs(urlparse(allowed.headers["location"]).query)["code"][0]
        client.cookies.clear()
        exchanged = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://127.0.0.1/callback",
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": "http://127.0.0.1/mcp",
            },
        )
        return exchanged.status_code

    with _client(runtime) as client:
        assert client.get("/stats").json()["oauth_connects"] == 0
        assert connect(client) == 200
        assert client.get("/stats").json()["oauth_connects"] == 1
        # The subscription lapses between the Allow click and the code exchange.
        original = billing.is_subscription_active
        calls = {"n": 0}

        def lapses_at_exchange(customer_id: str) -> bool:
            calls["n"] += 1
            return calls["n"] <= 2 and original(customer_id)  # authorize + Allow only

        billing.is_subscription_active = lapses_at_exchange  # type: ignore[method-assign]
        assert connect(client) == 400
        assert client.get("/stats").json()["oauth_connects"] == 1


def test_paid_stats_leave_out_console_links_and_setup_skips_the_log_scan(
    fake_drive: FakeDrive, monkeypatch
):
    from google_drive_mcp.infra.mcp_auth import stats as stats_module
    from google_drive_mcp.mcp import server as server_module

    monkeypatch.setattr(stats_module, "cloud_logging_project", lambda: "example-project")
    runtime = Runtime(settings=_paid_settings(), drive=fake_drive, billing=FakeBilling())
    with _client(runtime) as client:
        body = client.get("/stats").json()
        assert "gcp" not in body
        assert "example-project" not in json.dumps(body)

        def no_scan(*_args, **_kwargs):
            raise AssertionError("/setup must not scan logs when the paywall is on")

        monkeypatch.setattr(server_module, "stats_snapshot", no_scan)
        assert client.get("/setup").status_code == 200


def test_public_stats_reuse_one_log_scan_per_minute(monkeypatch):
    from google_drive_mcp.infra.mcp_auth import stats as stats_module
    from google_drive_mcp.infra.telemetry.recorder import ConnectRecorder

    scans = {"n": 0}

    def fake_scan(*, project: str):
        scans["n"] += 1
        return None, "no_project"

    monkeypatch.setattr(stats_module, "use_cloud_logging_stats", lambda: True)
    monkeypatch.setattr(stats_module, "fetch_cloud_logging_stats", fake_scan)
    monkeypatch.setattr(stats_module, "_log_scan", {"at": 0.0, "result": None})
    recorder = ConnectRecorder()
    for _ in range(5):
        assert stats_module.stats_snapshot(recorder, links=False)["log_store"] == "no_project"
    assert scans["n"] == 1
