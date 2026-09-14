"""Non-PII connect counter: /stats, auth-code vs refresh, first drive_*."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

from starlette.testclient import TestClient

from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt
from google_drive_mcp.infra.mcp_auth.tokens import signing_key
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import streamable_app

HEADERS_JSON = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}

_FORBIDDEN = {
    "email",
    "ip",
    "remoteip",
    "user_agent",
    "useragent",
    "authorization",
    "access_token",
    "client_id",
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


def _assert_non_pii(obj: object) -> None:
    if isinstance(obj, dict):
        keys = {str(k).lower() for k in obj}
        assert keys.isdisjoint(_FORBIDDEN)
        for value in obj.values():
            _assert_non_pii(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_non_pii(item)


def _connect(client: TestClient) -> dict:
    verifier, challenge = _pkce()
    redirect = "http://127.0.0.1/callback"
    registered = client.post(
        "/register",
        json={
            "redirect_uris": [redirect],
            "client_name": "stats-test",
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
            "state": "st",
            "scope": "drive.read",
            "resource": "http://127.0.0.1/mcp",
        },
        follow_redirects=False,
    )
    assert authorize.status_code in {302, 303, 307}
    code = parse_qs(urlparse(authorize.headers["location"]).query)["code"][0]
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
    body = token.json()
    body["client_id"] = info["client_id"]
    body["client_secret"] = info["client_secret"]
    return body


def _rpc_payload(response) -> dict:
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
    return response.json()


def test_stats_empty_then_connect_then_first_drive(runtime):
    with _client(runtime) as client:
        empty = client.get("/stats")
        assert empty.status_code == 200
        body = empty.json()
        assert body["oauth_connects"] == 0
        assert body["drive_first_uses"] == 0
        assert body["lookback"] == "30d"
        _assert_non_pii(body)
        if "gcp" in body:
            assert "dashboards" in body["gcp"]
            assert "metrics_explorer" in body["gcp"]
            assert "client_id" not in str(body["gcp"])

        tokens = _connect(client)
        after_connect = client.get("/stats").json()
        assert after_connect["oauth_connects"] == 1
        assert after_connect["drive_first_uses"] == 0
        claims = decode_jwt(tokens["access_token"], signing_key(runtime.settings))
        assert claims and claims.get("cid")

        listed = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {tokens['access_token']}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200
        assert client.get("/stats").json()["drive_first_uses"] == 0

        ls = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {tokens['access_token']}"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "drive_ls", "arguments": {"folder_id": "folder-a"}},
            },
        )
        assert ls.status_code == 200, ls.text
        payload = _rpc_payload(ls)
        assert payload.get("error") is None
        after_ls = client.get("/stats").json()
        assert after_ls["oauth_connects"] == 1
        assert after_ls["drive_first_uses"] == 1
        _assert_non_pii(after_ls)

        ls2 = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {tokens['access_token']}"},
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "drive_ls", "arguments": {"folder_id": "folder-a"}},
            },
        )
        assert ls2.status_code == 200
        again = client.get("/stats").json()
        assert again["oauth_connects"] == 1
        assert again["drive_first_uses"] == 1

        setup = client.get("/setup")
        assert setup.status_code == 200
        assert "1 successful Connects" in setup.text
        assert "1 first Drive tool uses" in setup.text
        assert "JSON" in setup.text


def test_refresh_does_not_increment_oauth_connects(runtime):
    with _client(runtime) as client:
        tokens = _connect(client)
        assert client.get("/stats").json()["oauth_connects"] == 1
        refreshed = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": tokens["client_id"],
                "client_secret": tokens["client_secret"],
                "resource": "http://127.0.0.1/mcp",
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        new_access = refreshed.json()["access_token"]
        claims = decode_jwt(new_access, signing_key(runtime.settings))
        old = decode_jwt(tokens["access_token"], signing_key(runtime.settings))
        assert claims and old and claims.get("cid") == old.get("cid")
        assert client.get("/stats").json()["oauth_connects"] == 1

        ls = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": f"Bearer {new_access}"},
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "drive_ls", "arguments": {"folder_id": "folder-a"}},
            },
        )
        assert ls.status_code == 200
        assert client.get("/stats").json()["drive_first_uses"] == 1


def test_failed_auth_does_not_count_first_use(runtime):
    with _client(runtime) as client:
        _connect(client)
        bad = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": "Bearer not-a-token"},
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "drive_ls", "arguments": {"folder_id": "folder-a"}},
            },
        )
        assert bad.status_code == 401
        stats = client.get("/stats").json()
        assert stats["oauth_connects"] == 1
        assert stats["drive_first_uses"] == 0
