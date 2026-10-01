"""OAuth hardening: stateless DCR, metadata limits, CIMD bounds, body caps, rate limits,
consent-ticket privacy, and the loopback verdict on the Allow page."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from fakes.fake_billing import FakeBilling
from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    mint_entitlement,
    verify_entitlement,
)
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth import cimd
from google_drive_mcp.infra.mcp_auth.dcr import client_from_id
from google_drive_mcp.infra.mcp_auth.jwt import b64url_decode, b64url_encode, encode_jwt
from google_drive_mcp.infra.mcp_auth.provider import DriveMcpOAuthProvider, _ExpiringIds
from google_drive_mcp.infra.mcp_auth.tokens import (
    _now,
    verify_access_claims,
    verify_code_claims,
    verify_refresh_claims,
    verify_ticket_claims,
)
from google_drive_mcp.mcp.limits import RequestLimits
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import streamable_app

REDIRECT = "http://127.0.0.1/callback"
RESOURCE = "http://127.0.0.1/mcp"
HEADERS_JSON = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _client(runtime: Runtime) -> TestClient:
    return TestClient(streamable_app(runtime, json_response=True))


def _metadata(**overrides) -> dict:
    body = {
        "redirect_uris": [REDIRECT],
        "client_name": "limits-test",
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": "drive.read",
    }
    body.update(overrides)
    return body


def _payload(token: str) -> bytes:
    return b64url_decode(token.split(".")[1])


# --- metadata limits ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_name": "x" * 201},
        {"redirect_uris": [f"http://127.0.0.1/callback/{n}" for n in range(6)]},
        {"redirect_uris": ["http://127.0.0.1/" + "a" * 600]},
        {"contacts": [f"ops{n}@example.com" for n in range(6)]},
        {"contacts": ["a" * 255]},
        {"jwks": {"keys": [{"kid": "k" * 1000, "n": "x" * 1000} for _ in range(10)]}},
    ],
    ids=["name", "six-uris", "long-uri", "six-contacts", "long-contact", "over-16kb"],
)
def test_oversized_metadata_is_invalid_client_metadata(runtime, overrides):
    with _client(runtime) as client:
        refused = client.post("/register", json=_metadata(**overrides))
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"] == "invalid_client_metadata"


def test_client_name_is_kept_to_100_characters(runtime):
    with _client(runtime) as client:
        registered = client.post("/register", json=_metadata(client_name="n" * 200))
    assert registered.status_code == 201, registered.text
    info = registered.json()
    assert info["client_name"] == "n" * 100
    assert client_from_id(runtime.settings, info["client_id"]).client_name == "n" * 100


# --- stateless DCR -----------------------------------------------------------------------


def _authorize(client: TestClient, client_id: str, challenge: str) -> str:
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s1",
            "scope": "drive.read",
            "resource": RESOURCE,
        },
        follow_redirects=False,
    )
    assert authorize.status_code in {302, 303, 307}, authorize.text
    location = authorize.headers["location"]
    assert location.startswith(REDIRECT), location
    return parse_qs(urlparse(location).query)["code"][0]


def _client_auth(info: dict) -> tuple[dict, dict]:
    """Form fields and headers for the client's registered token auth method."""
    method = info["token_endpoint_auth_method"]
    if method == "client_secret_basic":
        raw = f"{info['client_id']}:{info['client_secret']}".encode()
        return {"client_id": info["client_id"]}, {
            "authorization": "Basic " + base64.b64encode(raw).decode()
        }
    if method == "client_secret_post":
        return {"client_id": info["client_id"], "client_secret": info["client_secret"]}, {}
    return {"client_id": info["client_id"]}, {}


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic", "none"])
def test_client_registered_on_one_instance_connects_on_another(
    settings: Settings, fake_drive: FakeDrive, method: str
):
    with _client(Runtime(settings=settings, drive=fake_drive)) as app_a:
        registered = app_a.post("/register", json=_metadata(token_endpoint_auth_method=method))
    assert registered.status_code == 201, registered.text
    info = registered.json()
    assert info["token_endpoint_auth_method"] == method
    if method == "none":
        assert "client_secret" not in info
    else:
        assert info["client_secret"] and info["client_secret_expires_at"] == 0
    # A fresh app is a new instance: nothing from app A's memory is there.
    verifier, challenge = _pkce()
    with _client(Runtime(settings=settings, drive=fake_drive)) as app_b:
        code = _authorize(app_b, info["client_id"], challenge)
        form, headers = _client_auth(info)
        token = app_b.post(
            "/token",
            data={
                **form,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
                "resource": RESOURCE,
            },
            headers=headers,
        )
        assert token.status_code == 200, token.text
        issued = token.json()
        assert verify_access_claims(issued["access_token"], settings)["client_id"] == (
            info["client_id"]
        )
    with _client(Runtime(settings=settings, drive=fake_drive)) as app_c:
        form, headers = _client_auth(info)
        refreshed = app_c.post(
            "/token",
            data={**form, "grant_type": "refresh_token", "refresh_token": issued["refresh_token"]},
            headers=headers,
        )
        assert refreshed.status_code == 200, refreshed.text
        listed = app_c.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {refreshed.json()['access_token']}"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "drive_ls", "arguments": {}},
            },
        )
        assert listed.status_code == 200, listed.text


def test_each_registration_gets_its_own_client(runtime):
    with _client(runtime) as client:
        first = client.post("/register", json=_metadata()).json()
        second = client.post("/register", json=_metadata()).json()
    assert first["client_id"] != second["client_id"]
    assert first["client_secret"] != second["client_secret"]


def test_wrong_client_secret_is_refused(runtime):
    with _client(runtime) as client:
        info = client.post("/register", json=_metadata()).json()
        refused = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": "x",
                "client_id": info["client_id"],
                "client_secret": "0" * 64,
            },
        )
    assert refused.status_code == 401
    assert refused.json()["error"] == "invalid_client"


def _tampered(client_id: str) -> list[str]:
    header, payload, sig = client_id.split(".")
    claims = json.loads(b64url_decode(payload))
    claims["ru"] = ["https://attacker.example/cb"]
    forged = b64url_encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    other_key = encode_jwt(claims, hashlib.sha256(b"some other deployment").digest())
    flipped = sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")
    return [f"{header}.{forged}.{sig}", f"{header}.{payload}.{flipped}", other_key]


def test_tampered_client_id_is_invalid_client(runtime):
    _, challenge = _pkce()
    with _client(runtime) as client:
        client_id = client.post("/register", json=_metadata()).json()["client_id"]
        for bad in _tampered(client_id):
            assert client_from_id(runtime.settings, bad) is None
            authorize = client.get(
                "/authorize",
                params={
                    "response_type": "code",
                    "client_id": bad,
                    "redirect_uri": "https://attacker.example/cb",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "resource": RESOURCE,
                },
                follow_redirects=False,
            )
            assert authorize.status_code == 400
            assert "location" not in authorize.headers
            token = client.post(
                "/token",
                data={"grant_type": "refresh_token", "refresh_token": "x", "client_id": bad},
            )
            assert token.status_code == 401
            assert token.json()["error"] == "invalid_client"


def test_dcr_client_id_is_not_any_other_token(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    with _client(runtime) as client:
        client_id = client.post("/register", json=_metadata()).json()["client_id"]
        assert json.loads(_payload(client_id))["typ"] == "dcr"
        settings = runtime.settings
        for verify in (
            verify_access_claims,
            verify_refresh_claims,
            verify_code_claims,
            verify_ticket_claims,
        ):
            assert verify(client_id, settings) is None
        assert verify_entitlement(client_id, settings) is None
        called = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {client_id}"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "drive_ls", "arguments": {}},
            },
        )
    assert called.status_code == 401
    assert fake_drive.metadata_get_count == 0
    assert fake_drive.content_count == 0


# --- CIMD bounds ---------------------------------------------------------------------------


class _Fetches:
    """Counts CIMD document fetches; every fetch fails, so the fallback is used."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        outer = self

        class _Response:
            status_code = 503

            def json(self):
                raise ValueError("no document")

        class _Http:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, headers=None):
                outer.urls.append(url)
                return _Response()

        self.http = _Http


def test_cimd_client_id_over_512_characters_is_refused(runtime, monkeypatch):
    fetches = _Fetches()
    monkeypatch.setattr(cimd.httpx, "AsyncClient", fetches.http)
    provider = DriveMcpOAuthProvider(runtime.settings)
    long_id = "https://claude.ai/" + "p" * 500
    assert asyncio.run(provider.get_client(long_id)) is None
    assert fetches.urls == []
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": long_id,
                "redirect_uri": cimd.CLAUDE_WEB_REDIRECT,
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "resource": RESOURCE,
            },
            follow_redirects=False,
        )
    assert authorize.status_code == 400


def test_cimd_records_are_a_bounded_lru(monkeypatch):
    fetches = _Fetches()
    monkeypatch.setattr(cimd.httpx, "AsyncClient", fetches.http)
    clients = cimd.CimdClients(max_size=3)

    async def run() -> None:
        for n in range(10):
            assert await clients.get(f"https://claude.ai/oauth/{n}") is not None
        assert len(clients) == 3

    asyncio.run(run())


def test_cimd_fallback_is_kept_only_briefly(monkeypatch):
    fetches = _Fetches()
    monkeypatch.setattr(cimd.httpx, "AsyncClient", fetches.http)
    client_id = "https://chatgpt.com/oauth/aabbcc/client.json"

    async def run(ttl: float) -> int:
        fetches.urls.clear()
        clients = cimd.CimdClients(fallback_ttl=ttl)
        for _ in range(3):
            assert await clients.get(client_id) is not None
        return len(fetches.urls)

    assert asyncio.run(run(300.0)) == 1
    # Once the fallback expires, the real document is asked for again.
    assert asyncio.run(run(0.0)) == 3


# --- used / revoked jti ----------------------------------------------------------------------


def test_expired_jti_entries_are_dropped_on_insert():
    ids = _ExpiringIds()
    ids.add("old", _now() - 1)
    assert "old" in ids  # still there until the next insert
    ids.add("live", _now() + 60)
    ids.add("new", _now() + 60)
    assert "old" not in ids
    assert "live" in ids and "new" in ids and len(ids) == 2
    ids.discard("live")
    assert "live" not in ids and len(ids) == 1


def test_discard_and_re_add_keep_the_heap_bounded():
    ids = _ExpiringIds()
    for _ in range(1000):
        ids.add("jti", _now() + 3600)
        ids.discard("jti")
    assert len(ids) == 0
    assert len(ids._heap) <= 2 * len(ids) + 65


# --- body caps ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    async def __call__(self, scope, receive, send):
        message = await receive()
        self.bodies.append(message.get("body") or b"")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _call(app, path: str, chunks: list[bytes], headers: list[tuple[bytes, bytes]]) -> int:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("10.0.0.9", 1234),
    }
    queue = [
        {"type": "http.request", "body": chunk, "more_body": n < len(chunks) - 1}
        for n, chunk in enumerate(chunks)
    ]
    sent: list[dict] = []

    async def receive():
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent[0]["status"]


@pytest.mark.parametrize(
    ("path", "cap"),
    [("/mcp", 4 * 1024 * 1024), ("/webhooks/stripe", 1024 * 1024), ("/register", 64 * 1024)],
)
def test_body_over_the_cap_is_413_before_the_route(path: str, cap: int):
    inner = _Recorder()
    app = RequestLimits(inner)
    declared = [(b"content-length", str(cap + 1).encode())]
    assert _call(app, path, [b""], declared) == 413
    # No Content-Length: the streamed body is counted.
    assert _call(app, path, [b"x" * (cap // 2)] * 2 + [b"x"], []) == 413
    assert inner.bodies == []
    # At the cap, the route gets the whole body in one piece.
    assert _call(app, path, [b"x" * (cap // 2)] * 2, []) == 200
    assert inner.bodies == [b"x" * cap]


def test_oversized_bodies_get_413_on_the_real_app(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    with _client(runtime) as client:
        register = client.post(
            "/register", json=_metadata(client_name="x" * (64 * 1024)), follow_redirects=False
        )
        assert register.status_code == 413
        mcp = client.post(
            "/mcp",
            headers=HEADERS_JSON,
            content=b" " * (4 * 1024 * 1024 + 1),
        )
        assert mcp.status_code == 413
        # Small bodies still reach the routes.
        assert client.post("/register", json=_metadata()).status_code == 201
    assert fake_drive.metadata_get_count == 0


# --- rate limits -------------------------------------------------------------------------


def test_register_is_rate_limited_per_address(runtime):
    with _client(runtime) as client:
        for n in range(20):
            # Only the last X-Forwarded-For entry counts; earlier ones can be forged.
            forged = {"x-forwarded-for": f"198.51.100.{n}, 203.0.113.7"}
            assert client.post("/register", json=_metadata(), headers=forged).status_code == 201
        limited = client.post(
            "/register", json=_metadata(), headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"}
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "3600"
        other = client.post(
            "/register", json=_metadata(), headers={"x-forwarded-for": "203.0.113.8"}
        )
        assert other.status_code == 201


def test_token_and_authorize_are_rate_limited(runtime):
    with _client(runtime) as client:
        for _ in range(120):
            assert client.post("/token", data={"grant_type": "x"}).status_code != 429
        limited = client.post("/token", data={"grant_type": "x"})
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        for _ in range(120):
            assert client.post("/authorize", data={}).status_code != 429
        assert client.post("/authorize", data={}).status_code == 429
        assert client.get("/authorize", follow_redirects=False).status_code == 429


# --- consent ticket and Allow page ------------------------------------------------------------


def _paid_runtime(fake_drive: FakeDrive) -> tuple[Settings, Runtime, str]:
    settings = Settings.for_tests().model_copy(
        update={"mcp_subscription_required": True, "stripe_price_id": "price_test"}
    )
    billing = FakeBilling()
    billing.active.add("cus_live1")
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    return settings, runtime, mint_entitlement(settings, customer_id="cus_live1")


def _ticket(client: TestClient, cookie: str, redirect: str, challenge: str = "abc") -> str:
    client_id = client.post(
        "/register",
        json=_metadata(redirect_uris=[redirect], token_endpoint_auth_method="none"),
    ).json()["client_id"]
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "drive.read",
            "resource": RESOURCE,
        },
        cookies={COOKIE_NAME: cookie},
        follow_redirects=False,
    )
    location = authorize.headers["location"]
    assert "/consent?ticket=" in location
    return parse_qs(urlparse(location).query)["ticket"][0]


def test_consent_ticket_does_not_carry_the_customer_id(fake_drive: FakeDrive):
    settings, runtime, cookie = _paid_runtime(fake_drive)
    with _client(runtime) as client:
        ticket = _ticket(client, cookie, REDIRECT)
        assert b"cus_" not in _payload(ticket)
        assert "scid" not in verify_ticket_claims(ticket, settings)
        allowed = client.post(
            "/consent", data={"ticket": ticket}, cookies={COOKIE_NAME: cookie},
            follow_redirects=False,
        )
        assert allowed.status_code == 303
        code = parse_qs(urlparse(allowed.headers["location"]).query)["code"][0]
    # The code names the browser's own subscriber, so /token can re-check Stripe.
    assert verify_code_claims(code, settings)["scid"] == "cus_live1"


def test_ticket_for_another_subscriber_is_refused(fake_drive: FakeDrive):
    settings, runtime, cookie = _paid_runtime(fake_drive)
    runtime.billing.active.add("cus_other")
    other = mint_entitlement(settings, customer_id="cus_other")
    with _client(runtime) as client:
        ticket = _ticket(client, cookie, REDIRECT)
        client.cookies.clear()
        refused = client.post(
            "/consent", data={"ticket": ticket}, cookies={COOKIE_NAME: other},
            follow_redirects=False,
        )
    assert refused.status_code == 400
    assert "location" not in refused.headers


@pytest.mark.parametrize(
    "redirect",
    ["http://127.0.0.1/callback", "http://localhost:33418/callback", "http://[::1]:8080/cb"],
)
def test_loopback_return_address_is_a_program_on_this_computer(
    fake_drive: FakeDrive, redirect: str
):
    _, runtime, cookie = _paid_runtime(fake_drive)
    with _client(runtime) as client:
        ticket = _ticket(client, cookie, redirect)
        page = client.get("/consent", params={"ticket": ticket}, cookies={COOKIE_NAME: cookie})
    assert page.status_code == 200
    assert (
        "a program on this computer (for example Claude Code or Codex) — allow only if you "
        "just started Connect from it yourself"
    ) in page.text
    assert 'class="warn"' in page.text
    assert "a known AI chat app address" not in page.text


def test_known_chat_app_return_address_is_still_recognized(fake_drive: FakeDrive):
    _, runtime, cookie = _paid_runtime(fake_drive)
    with _client(runtime) as client:
        ticket = _ticket(client, cookie, "https://claude.ai/api/mcp/auth_callback")
        page = client.get("/consent", params={"ticket": ticket}, cookies={COOKIE_NAME: cookie})
    assert '<span class="ok">a known AI chat app address</span>' in page.text
    assert "a program on this computer" not in page.text


def test_password_page_still_works_without_the_paywall(fake_drive: FakeDrive):
    settings = Settings(
        mcp_auth_token=SecretStr("test-token"),
        mcp_principal_id="deployment-1",
        google_client_id="test-client-id",
        google_client_secret=SecretStr("test-client-secret"),
        google_refresh_token=SecretStr("test-refresh-token"),
        mcp_public_url="http://127.0.0.1",
        mcp_oauth_auto_approve=False,
    )
    runtime = Runtime(settings=settings, drive=fake_drive)
    with _client(runtime) as client:
        client_id = client.post("/register", json=_metadata()).json()["client_id"]
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "resource": RESOURCE,
            },
            follow_redirects=False,
        )
        ticket = parse_qs(urlparse(authorize.headers["location"]).query)["ticket"][0]
        assert "scid_hash" not in verify_ticket_claims(ticket, settings)
        page = client.get("/consent", params={"ticket": ticket})
    assert 'type="password"' in page.text
