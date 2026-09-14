"""OAuth 2.1 on Streamable HTTP: metadata, DCR+PKCE, consent, reject static secret."""

from __future__ import annotations

import base64
import hashlib
import json
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
        assert "none" in (meta.get("token_endpoint_auth_methods_supported") or [])
        assert meta.get("client_id_metadata_document_supported") is True
        assert meta.get("authorization_response_iss_parameter_supported") is True
        origin_pr = client.get("/.well-known/oauth-protected-resource")
        assert origin_pr.status_code == 200
        assert origin_pr.json()["resource"].rstrip("/") == "http://127.0.0.1/mcp"


def _rpc_payload(response) -> dict:
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
    return response.json()


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
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count == 0
    assert response.status_code == 401
    www = response.headers.get("www-authenticate", "")
    assert "resource_metadata" in www
    assert "invalid_token" in www


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
        assert parse_qs(urlparse(location).query)["iss"]
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
        assert "onto-kb" in page.text
        assert "Always allow" in page.text
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


def test_chatgpt_cimd_public_client_can_mint_access_token(runtime, monkeypatch):
    client_id = "https://chatgpt.com/oauth/aabbcc/client.json"
    redirect = "https://chatgpt.com/connector/oauth/aabbcc"
    document = {
        "redirect_uris": [redirect],
        "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
        "token_endpoint_auth_method": "private_key_jwt",
        "grant_types": ["authorization_code", "refresh_token"],
        "client_name": "ChatGPT",
    }

    class _Response:
        status_code = 200

        def json(self):
            return document

    class _Http:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            assert url == client_id
            return _Response()

    monkeypatch.setattr("google_drive_mcp.infra.mcp_auth.cimd.httpx.AsyncClient", _Http)
    verifier, challenge = _pkce()
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}, authorize.text
        location = authorize.headers["location"]
        assert location.startswith(redirect)
        code = parse_qs(urlparse(location).query)["code"][0]
        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": "http://127.0.0.1/mcp",
            },
        )
        assert token.status_code == 200, token.text
        listed = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {token.json()['access_token']}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200, listed.text


def test_cimd_rejects_non_chatgpt_https_client_id(runtime):
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "https://evil.example/oauth/client.json",
                "redirect_uri": "https://evil.example/callback",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {400, 401}


def test_claude_cimd_web_client_can_mint_access_token(runtime, monkeypatch):
    client_id = "https://claude.ai/oauth/mcp-oauth-client-metadata"
    redirect = "https://claude.ai/api/mcp/auth_callback"
    document = {
        "client_id": client_id,
        "client_name": "Claude",
        "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }

    class _Response:
        status_code = 200

        def json(self):
            return document

    class _Http:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            assert url == client_id
            return _Response()

    monkeypatch.setattr("google_drive_mcp.infra.mcp_auth.cimd.httpx.AsyncClient", _Http)
    verifier, challenge = _pkce()
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}, authorize.text
        location = authorize.headers["location"]
        assert location.startswith(redirect)
        assert "error=" not in location
        code = parse_qs(urlparse(location).query)["code"][0]
        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": "http://127.0.0.1/mcp",
            },
        )
        assert token.status_code == 200, token.text


def test_claude_cimd_authorize_accepts_drive_read_scope(runtime, monkeypatch):
    """Claude always sends scope=drive.read; CIMD metadata omits scope."""
    client_id = "https://claude.ai/oauth/mcp-oauth-client-metadata"
    redirect = "https://claude.ai/api/mcp/auth_callback"
    document = {
        "client_id": client_id,
        "client_name": "Claude",
        "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }

    class _Response:
        status_code = 200

        def json(self):
            return document

    class _Http:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            return _Response()

    monkeypatch.setattr("google_drive_mcp.infra.mcp_auth.cimd.httpx.AsyncClient", _Http)
    _, challenge = _pkce()
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "probe",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}, authorize.text
        location = authorize.headers["location"]
        assert location.startswith(redirect)
        query = parse_qs(urlparse(location).query)
        assert "code" in query
        assert query.get("error") is None


def test_claude_cimd_fallback_accepts_drive_read_scope(runtime, monkeypatch):
    client_id = "https://claude.ai/oauth/mcp-oauth-client-metadata"
    redirect = "https://claude.ai/api/mcp/auth_callback"

    class _Response:
        status_code = 403

        def json(self):
            raise ValueError("not json")

    class _Http:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            return _Response()

    monkeypatch.setattr("google_drive_mcp.infra.mcp_auth.cimd.httpx.AsyncClient", _Http)
    _, challenge = _pkce()
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "probe",
                "scope": "drive.read",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}, authorize.text
        location = authorize.headers["location"]
        assert location.startswith(redirect)
        assert parse_qs(urlparse(location).query).get("error") is None


def test_get_mcp_returns_405_without_hanging(runtime):
    with _client(runtime) as client:
        response = client.get("/mcp")
    assert response.status_code == 405
    www = response.headers.get("www-authenticate", "")
    assert "resource_metadata" in www


def test_setup_page_lists_minimum_claude_clicks(runtime):
    with _client(runtime) as client:
        setup = client.get("/setup")
    assert setup.status_code == 200
    assert "http://127.0.0.1/mcp" in setup.text
    assert "Always allow" in setup.text
    assert "Sign in when needed" in setup.text
    assert "no deployment password" in setup.text.lower()


def test_setup_page_mentions_consent_when_auto_approve_disabled(fake_drive: FakeDrive):
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
        page = client.get("/setup")
    assert page.status_code == 200
    assert "Always allow" in page.text
    assert "consent" in page.text.lower()


def test_chatgpt_mixed_auth_lists_tools_without_bearer(runtime):
    with _client(runtime) as client:
        preflight = client.options(
            "/mcp",
            headers={
                "origin": "https://chatgpt.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization,content-type,mcp-protocol-version",
            },
        )
        assert preflight.status_code in {200, 204}
        assert preflight.headers.get("access-control-allow-origin") == "*"
        initialized = client.post(
            "/mcp",
            headers=HEADERS_JSON,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "chatgpt", "version": "0"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        listed = client.post(
            "/mcp",
            headers=HEADERS_JSON,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200, listed.text
        tools = _rpc_payload(listed)["result"]["tools"]
        names = [t["name"] for t in tools]
        assert names == ["drive_ls", "drive_find", "drive_read", "drive_grep"]
        for tool in tools:
            schemes = tool.get("securitySchemes") or (tool.get("_meta") or {}).get("securitySchemes")
            assert schemes == [{"type": "oauth2", "scopes": ["drive.read"]}]


def test_chatgpt_tool_call_without_token_signals_www_authenticate(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    with _client(runtime) as client:
        response = client.post(
            "/mcp",
            headers=HEADERS_JSON,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "drive_ls", "arguments": {}},
            },
        )
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count == 0
    assert response.status_code == 401, response.text
    www = response.headers.get("www-authenticate", "")
    assert "resource_metadata" in www
    assert "error=" in www
    assert "error_description=" in www


def test_chatgpt_cimd_fallback_when_metadata_fetch_fails(runtime, monkeypatch):
    client_id = "https://chatgpt.com/oauth/aabbcc/client.json"
    redirect = "https://chatgpt.com/connector/oauth/aabbcc"

    class _Response:
        status_code = 403

        def json(self):
            raise ValueError("not json")

    class _Http:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            return _Response()

    monkeypatch.setattr("google_drive_mcp.infra.mcp_auth.cimd.httpx.AsyncClient", _Http)
    verifier, challenge = _pkce()
    with _client(runtime) as client:
        authorize = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "http://127.0.0.1/mcp",
            },
            follow_redirects=False,
        )
        assert authorize.status_code in {302, 303, 307}, authorize.text
        location = authorize.headers["location"]
        assert location.startswith(redirect)
        code = parse_qs(urlparse(location).query)["code"][0]
        token = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": "http://127.0.0.1/mcp",
            },
        )
        assert token.status_code == 200, token.text
