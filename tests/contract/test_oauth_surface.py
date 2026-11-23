"""The OAuth surface that faces strangers: no fetch for an arbitrary URL, no code to an arbitrary
redirect, no script on the Allow page, no account restored for another address (Article VII).

Everything here is reachable without a subscription: /authorize takes any client_id, /register
takes any metadata, and the sign-in link flow takes any address. Each test feeds the bad case
and checks the door stays shut.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import SecretStr
from starlette.testclient import TestClient

from fakes.fake_billing import FakeBilling
from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.billing.email_link import IdentityPlatformEmailLink
from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    RESUME_COOKIE,
    mint_entitlement,
    safe_resume,
)
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth import cimd, consent
from google_drive_mcp.infra.mcp_auth.dcr import client_from_id, mint_client_id
from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt, encode_jwt
from google_drive_mcp.infra.mcp_auth.provider import DriveMcpOAuthProvider
from google_drive_mcp.infra.mcp_auth.tokens import signing_key
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import streamable_app

REDIRECT = "http://127.0.0.1/callback"
RESOURCE = "http://127.0.0.1/mcp"
GONE = object()


# --- client metadata documents: which URLs the server will fetch -------------------------


class _Fetches:
    """Stands in for httpx.AsyncClient: records every fetch and how the client was built."""

    def __init__(self, document: dict | None = None) -> None:
        self.urls: list[str] = []
        self.built_with: list[dict] = []
        outer = self

        class _Response:
            status_code = 200 if document is not None else 503

            def json(self):
                if document is None:
                    raise ValueError("no document")
                return document

        class _Http:
            def __init__(self, *args, **kwargs):
                outer.built_with.append(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, headers=None):
                outer.urls.append(url)
                return _Response()

        self.http = _Http


@pytest.mark.parametrize(
    "client_id",
    [
        "https://evil.example/oauth/client.json",
        "https://claude.ai.evil.example/oauth/client.json",
        "https://evilclaude.ai/oauth/client.json",
        "https://claude.ai@evil.example/oauth/client.json",
        "https://chatgpt.com.evil.example/oauth/client.json",
        "http://claude.ai/oauth/client.json",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/client.json",
        "https://claude.ai",
    ],
)
async def test_a_client_id_on_any_other_host_is_never_fetched(monkeypatch, client_id: str):
    fetches = _Fetches()
    monkeypatch.setattr(cimd.httpx, "AsyncClient", fetches.http)
    assert await cimd.CimdClients().get(client_id) is None
    assert fetches.urls == []


async def test_an_allowed_host_is_fetched_without_following_redirects(monkeypatch):
    fetches = _Fetches()
    monkeypatch.setattr(cimd.httpx, "AsyncClient", fetches.http)
    client_id = "https://claude.ai/oauth/abc123/client.json"
    assert await cimd.CimdClients().get(client_id) is not None
    assert fetches.urls == [client_id]
    # An allowed host that answers with a redirect must not lead the fetch somewhere else.
    assert fetches.built_with[0]["follow_redirects"] is False


@pytest.mark.parametrize(
    ("uri", "allowed"),
    [
        ("https://claude.ai/api/mcp/auth_callback", True),
        ("https://claude.com/api/mcp/auth_callback", True),
        ("https://chatgpt.com/connector/oauth/abc123", True),
        ("https://chatgpt.com/connector_platform_oauth_redirect", True),
        ("http://127.0.0.1/callback", True),
        ("http://localhost:33418/callback/abc", True),
        ("https://claude.ai/some/other/path", False),
        ("https://evil.example/api/mcp/auth_callback", False),
        ("https://claude.ai.evil.example/api/mcp/auth_callback", False),
        ("http://evil.example/callback", False),
        ("http://claude.ai/api/mcp/auth_callback", False),
        ("http://127.0.0.1/elsewhere", False),
        ("ftp://127.0.0.1/callback", False),
        ("javascript:alert(1)", False),
        ("", False),
    ],
)
def test_the_redirect_allow_list_for_client_metadata_clients(uri: str, allowed: bool):
    assert cimd.cimd_redirect_allowed(uri) is allowed


# --- registered client ids ---------------------------------------------------------------


def _registration(settings: Settings) -> dict:
    info = OAuthClientInformationFull(
        client_id="placeholder", redirect_uris=[REDIRECT], token_endpoint_auth_method="none"
    )
    claims = decode_jwt(mint_client_id(settings, info, iat=int(time.time())), signing_key(settings))
    assert claims is not None
    return claims


@pytest.mark.parametrize(
    "change",
    [{"typ": "access"}, {"typ": "refresh"}, {"typ": GONE}, {"aud": "https://other.example/"}, {"aud": GONE}],
    ids=["typ-access", "typ-refresh", "typ-gone", "aud-other", "aud-gone"],
)
def test_only_a_registration_is_a_client_id(settings: Settings, change: dict):
    claims = _registration(settings)
    assert client_from_id(settings, encode_jwt(claims, signing_key(settings))) is not None
    for name, value in change.items():
        if value is GONE:
            claims.pop(name)
        else:
            claims[name] = value
    assert client_from_id(settings, encode_jwt(claims, signing_key(settings))) is None


# --- the Allow page ----------------------------------------------------------------------


def _paid_app(fake_drive: FakeDrive) -> tuple[Settings, TestClient, str]:
    settings = Settings.for_tests().model_copy(
        update={"mcp_subscription_required": True, "stripe_price_id": "price_test"}
    )
    billing = FakeBilling()
    billing.active.add("cus_live1")
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    client = TestClient(streamable_app(runtime, json_response=True))
    return settings, client, mint_entitlement(settings, customer_id="cus_live1")


def _register(client: TestClient, **overrides) -> str:
    body = {
        "redirect_uris": [REDIRECT],
        "client_name": "test",
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
        "scope": "drive.read",
    }
    body.update(overrides)
    return client.post("/register", json=body).json()["client_id"]


def _authorize_params(client_id: str) -> dict:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": "abc",
        "code_challenge_method": "S256",
        "scope": "drive.read",
        "resource": RESOURCE,
    }


def test_a_registered_name_with_markup_is_shown_as_text(fake_drive: FakeDrive):
    _settings, client, cookie = _paid_app(fake_drive)
    with client:
        client_id = _register(client, client_name="<script>alert(1)</script>")
        authorize = client.get(
            "/authorize",
            params=_authorize_params(client_id),
            cookies={COOKIE_NAME: cookie},
            follow_redirects=False,
        )
        location = authorize.headers["location"]
        assert "/consent?ticket=" in location
        page = client.get(location, cookies={COOKIE_NAME: cookie})
    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


async def test_the_pages_escape_everything_they_print(settings: Settings):
    provider = DriveMcpOAuthProvider(settings)
    hostile_ticket = '"><script>ticket()</script>'
    claims = {
        "client_id": "no-such-client",
        "redirect_uri": 'http://evil"><script>host()</script>.example/callback',
    }
    allow = (await consent._allow_page(hostile_ticket, claims, provider)).body.decode()
    password = consent._password_page(hostile_ticket, error="<b>bad</b>").body.decode()
    for page in (allow, password):
        assert "<script>" not in page
        assert "<b>bad</b>" not in page
    assert "&lt;script&gt;ticket()" in allow and "&lt;script&gt;ticket()" in password
    assert "&lt;script&gt;host()" in allow


# --- where a paused Connect resumes ------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        ("/authorize", True),
        ("/authorize?client_id=abc&state=s1", True),
        (None, False),
        ("", False),
        ("/subscribe", False),
        ("/authorizeX", False),
        ("https://evil.example/authorize", False),
        ("//evil.example/authorize", False),
        ("/authorize?next=https://evil.example", False),
        ("/authorize?x=a\\b", False),
        ("/authorize?x=//evil.example", True),  # a query string may hold slashes; no scheme
    ],
)
def test_only_an_authorize_path_on_this_origin_is_a_resume_target(value, kept: bool):
    assert safe_resume(value) == (value if kept else None)


def test_the_cookies_the_server_sets_cannot_be_read_by_scripts(fake_drive: FakeDrive):
    settings, client, cookie = _paid_app(fake_drive)
    with client:
        # No subscription yet: the in-progress Connect is parked in a cookie.
        parked = client.get(
            "/authorize", params=_authorize_params("anything"), follow_redirects=False
        )
        assert parked.status_code == 302 and parked.headers["location"] == "/subscribe"
        resume = [c for c in parked.headers.get_list("set-cookie") if c.startswith(RESUME_COOKIE)]
        assert len(resume) == 1 and "HttpOnly" in resume[0] and "SameSite=Lax" in resume[0]
        # A subscriber's cookie is renewed on every reply.
        renewed = client.get("/setup", cookies={COOKIE_NAME: cookie})
        entitlement = [c for c in renewed.headers.get_list("set-cookie") if c.startswith(COOKIE_NAME)]
        assert len(entitlement) == 1 and "HttpOnly" in entitlement[0]


# --- restoring a subscription by email link ----------------------------------------------


def _email_link(owner: str):
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append((method, json.loads(request.content or b"{}")))
        if method == "accounts:signInWithEmailLink":
            return httpx.Response(200, json={"email": owner, "idToken": "id-token-1"}, request=request)
        return httpx.Response(200, json={}, request=request)

    settings = Settings.for_tests().model_copy(
        update={"identity_toolkit_api_key": SecretStr("AIzaTestOnlyIdentityKey0123456789abcd")}
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return IdentityPlatformEmailLink(settings, client=http), calls


def test_a_link_restores_only_the_address_it_was_sent_to():
    link, _calls = _email_link("Owner@Example.com")
    assert link.verified_email("owner@example.com", "code-1") == "owner@example.com"
    assert link.verified_email("  OWNER@example.COM ", "code-1") == "owner@example.com"
    assert link.verified_email("someone.else@example.com", "code-1") is None


def test_the_address_is_not_kept_at_the_identity_provider():
    link, calls = _email_link("owner@example.com")
    assert link.verified_email("owner@example.com", "code-1") == "owner@example.com"
    assert link.verified_email("someone.else@example.com", "code-1") is None
    deletes = [body for method, body in calls if method == "accounts:delete"]
    assert deletes == [{"idToken": "id-token-1"}, {"idToken": "id-token-1"}]


def test_a_link_the_provider_rejects_restores_nothing():
    def refuses(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "INVALID_OOB_CODE"}}, request=request)

    settings = Settings.for_tests().model_copy(
        update={"identity_toolkit_api_key": SecretStr("AIzaTestOnlyIdentityKey0123456789abcd")}
    )
    link = IdentityPlatformEmailLink(
        settings, client=httpx.Client(transport=httpx.MockTransport(refuses))
    )
    assert link.verified_email("owner@example.com", "stale-code") is None
