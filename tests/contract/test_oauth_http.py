"""OAuth 2.1 on Streamable HTTP: metadata, DCR+PKCE, consent, reject static secret."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from pydantic import SecretStr
from starlette.testclient import TestClient

from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import streamable_app

HEADERS_JSON = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _client(runtime: Runtime) -> TestClient:
    return TestClient(streamable_app(runtime, json_response=True))


def test_protected_resource_and_as_metadata_advertise_oauth(runtime):
    with _client(runtime) as client:
        pr = client.get("/.well-known/oauth-protected-resource/mcp")
        assert pr.status_code == 200
        body = pr.json()
        assert body["resource"].rstrip("/") == "http://127.0.0.1/mcp"
        assert any(s.rstrip("/") == "http://127.0.0.1" for s in body["authorization_servers"])
        as_meta = client.get("/.well-known/oauth-authorization-server")
        assert as_meta.status_code == 200
        meta = as_meta.json()
        assert meta["authorization_endpoint"].endswith("/authorize")
        assert meta["token_endpoint"].endswith("/token")
        assert meta["registration_endpoint"].endswith("/register")
        assert "S256" in meta["code_challenge_methods_supported"]
        assert "drive.read" in (meta.get("scopes_supported") or [])


def test_static_shared_secret_is_not_an_access_token(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    with _client(runtime) as client:
        response = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": "Bearer test-token"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "drive_read", "arguments": {"file_id": "nested-doc"}},
            },
        )
    assert response.status_code == 401
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count == 0
    www = response.headers.get("www-authenticate", "").lower()
    assert "resource_metadata" in www or "invalid_token" in response.text.lower()


def test_dcr_pkce_issues_access_token_that_calls_tools(runtime):
    verifier, challenge = _pkce()
    redirect = "http://127.0.0.1/callback"
    with _client(runtime) as client:
        registered = client.post(
            "/register",
            json={
                "redirect_uris": [redirect],
                "client_name": "contract-test",
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "client_secret_post",
                "scope": "drive.read",
            },
        )
        assert registered.status_code == 201, registered.text
        info = registered.json()
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": info["client_id"],
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "state-1",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}
        location = authorize.headers["location"]
        assert location.startswith(redirect)
        code = parse_qs(urlparse(location).query)["code"][0]
        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": info["client_id"],
                "client_secret": info["client_secret"],
                "code_verifier": verifier,
                "resource": "http://127.0.0.1/mcp",
            },
        )
        assert token.status_code == 200, token.text
        access = token.json()["access_token"]
        assert token.json().get("refresh_token")
        listed = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {access}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200, listed.text
        payload = listed.json()
        names = [t["name"] for t in payload["result"]["tools"]]
        assert names == ["drive_ls", "drive_find", "drive_read", "drive_grep"]


def test_consent_password_required_when_auto_approve_disabled(fake_drive: FakeDrive):
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
    verifier, challenge = _pkce()
    redirect = "http://127.0.0.1/callback"
    with _client(runtime) as client:
        info = client.post(
            "/register",
            json={
                "redirect_uris": [redirect],
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "client_secret_post",
            },
        ).json()
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": info["client_id"],
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}
        consent_url = authorize.headers["location"]
        assert "/consent" in consent_url
        page = client.get(consent_url)
        assert page.status_code == 200
        assert "password" in page.text.lower()
        denied = client.post(
            "/consent",
            data={"ticket": parse_qs(urlparse(consent_url).query)["ticket"][0], "password": "wrong"},
            follow_redirects=False,
        )
        assert denied.status_code == 400
        allowed = client.post(
            "/consent",
            data={
                "ticket": parse_qs(urlparse(consent_url).query)["ticket"][0],
                "password": "test-token",
            },
            follow_redirects=False,
        )
        assert allowed.status_code in {302, 303, 307}
        location = allowed.headers["location"]
        assert location.startswith(redirect)
        code = parse_qs(urlparse(location).query)["code"][0]
        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": info["client_id"],
                "client_secret": info["client_secret"],
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200, token.text
        assert token.json()["access_token"]
