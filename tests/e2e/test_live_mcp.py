"""Live Cloud Run smoke. Skipped unless LIVE_MCP_URL and MCP_AUTH_TOKEN are set.

Uses JSON-RPC over Streamable HTTP (no MCP client session) so teardown cannot
fail the run. Does not log secret values. Optional LIVE_DOC_FILE_ID /
LIVE_FOLDER_ID / LIVE_PHRASE exercise read/grep; unknown-id, missing-bearer,
and default-scope listing always run when the URL is set.

MCP callers authenticate with an OAuth 2.1 access token. MCP_AUTH_TOKEN is the
resource-owner consent password used to finish the authorization-code + PKCE
dance, not the /mcp Bearer value.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

LIVE_URL = os.environ.get("LIVE_MCP_URL", "").rstrip("/")
LIVE_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
LIVE_DOC = os.environ.get("LIVE_DOC_FILE_ID", "")
LIVE_FOLDER = os.environ.get("LIVE_FOLDER_ID", "")
LIVE_PHRASE = os.environ.get("LIVE_PHRASE", "idempotency")

pytestmark = pytest.mark.skipif(
    not LIVE_URL or not LIVE_TOKEN,
    reason="Set LIVE_MCP_URL and MCP_AUTH_TOKEN for live Cloud Run E2E",
)

_ACCESS: str | None = None


def _oauth_ready() -> bool:
    origin = _origin()
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{origin}/.well-known/oauth-authorization-server")
    return response.status_code == 200


@pytest.fixture(scope="module")
def live_oauth():
    if not _oauth_ready():
        pytest.skip("LIVE_MCP_URL is not serving MCP OAuth 2.1 yet")


def _origin() -> str:
    url = LIVE_URL.rstrip("/")
    if url.endswith("/mcp"):
        url = url[:-4]
    return url.rstrip("/")


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _live_access_token() -> str:
    global _ACCESS
    if _ACCESS:
        return _ACCESS
    origin = _origin()
    verifier, challenge = _pkce()
    redirect = "http://127.0.0.1/oauth-e2e/callback"
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        registered = client.post(
            f"{origin}/register",
            json={
                "redirect_uris": [redirect],
                "client_name": "live-e2e",
                "grant_types": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_method": "client_secret_post",
                "scope": "drive.read",
            },
        )
        assert registered.status_code == 201, registered.text
        info = registered.json()
        authorize = client.get(
            f"{origin}/authorize",
            params={
                "response_type": "code",
                "client_id": info["client_id"],
                "redirect_uri": redirect,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "drive.read",
                "resource": f"{origin}/mcp",
            },
        )
        assert authorize.status_code in {302, 303, 307}, authorize.text
        consent_loc = authorize.headers["location"]
        if consent_loc.startswith("/"):
            consent_loc = origin + consent_loc
        ticket = parse_qs(urlparse(consent_loc).query).get("ticket", [None])[0]
        if ticket:
            allowed = client.post(
                f"{origin}/consent",
                data={"ticket": ticket, "password": LIVE_TOKEN},
            )
            assert allowed.status_code in {302, 303, 307}, allowed.text
            location = allowed.headers["location"]
        else:
            location = consent_loc
        code = parse_qs(urlparse(location).query)["code"][0]
        token = client.post(
            f"{origin}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": info["client_id"],
                "client_secret": info["client_secret"],
                "code_verifier": verifier,
                "resource": f"{origin}/mcp",
            },
        )
        assert token.status_code == 200, token.text
        access = token.json()["access_token"]
        assert isinstance(access, str) and access
        assert LIVE_TOKEN not in token.text
    _ACCESS = access
    return access


def _sse_payload(response: httpx.Response) -> dict:
    ctype = (response.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        body = response.json()
        if isinstance(body, dict):
            return body
        raise AssertionError(f"JSON body was not an object: {type(body)}")
    for line in response.text.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            if not raw:
                continue
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
    raise AssertionError("SSE response had no JSON data frame")


def _tool_body_from_rpc(payload: dict) -> dict:
    error = payload.get("error")
    if isinstance(error, dict):
        return error
    result = payload.get("result")
    if not isinstance(result, dict):
        raise AssertionError(f"RPC result was not an object: {payload!r}")
    structured = result.get("structuredContent") or result.get("structured_content")
    if isinstance(structured, dict) and structured:
        return structured
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"tool result was not a JSON object: {payload!r}")


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def _call_tool(name: str, arguments: dict, *, token: str | None = "") -> dict:
    if token == "":
        token = _live_access_token()
    rpc = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.post(LIVE_URL, headers=_headers(token), json=rpc)
    assert LIVE_TOKEN not in response.text
    payload = _sse_payload(response)
    return _tool_body_from_rpc(payload)


def test_missing_bearer_is_http_401(live_oauth):
    rpc = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "drive_read", "arguments": {"file_id": "does-not-exist"}},
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(LIVE_URL, headers=_headers(None), json=rpc)
    assert response.status_code == 401
    assert LIVE_TOKEN not in response.text
    assert "nested" not in response.text.lower()


def test_static_shared_secret_is_not_an_access_token(live_oauth):
    rpc = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "drive_read", "arguments": {"file_id": "does-not-exist"}},
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(LIVE_URL, headers=_headers(LIVE_TOKEN), json=rpc)
    assert response.status_code == 401
    assert LIVE_TOKEN not in response.text


def test_unknown_file_is_file_not_found(live_oauth):
    body = _call_tool(
        "drive_read", {"file_id": "00000000000000000000000000000000"}
    )
    assert body.get("category") == "FILE_NOT_FOUND"
    dumped = json.dumps(body)
    assert LIVE_TOKEN not in dumped
    assert "refresh" not in dumped.lower()


def test_live_ls_my_drive_root(live_oauth):
    listed = _call_tool("drive_ls", {"max_results": 5})
    assert listed.get("status") in {"COMPLETE", "PARTIAL", "EMPTY"}
    dumped = json.dumps(listed)
    assert LIVE_TOKEN not in dumped
    for child in listed.get("children") or []:
        assert "content" not in child
        assert child.get("id")


@pytest.mark.skipif(
    not LIVE_DOC,
    reason="Set LIVE_DOC_FILE_ID to a throwaway Doc the deployment identity can read",
)
def test_live_read_and_grep_known_doc(live_oauth):
    read = _call_tool("drive_read", {"file_id": LIVE_DOC})
    assert read.get("status") in {"COMPLETE", "PARTIAL"}
    assert read.get("file_id") == LIVE_DOC
    assert LIVE_PHRASE in (read.get("content") or "")
    grep = _call_tool("drive_grep", {"pattern": LIVE_PHRASE, "file_ids": [LIVE_DOC]})
    assert grep.get("matches")
    empty = _call_tool(
        "drive_grep",
        {"pattern": "no-such-phrase-xyz-live-e2e", "file_ids": [LIVE_DOC]},
    )
    assert empty.get("status") == "EMPTY"
    assert empty.get("matches") == []


@pytest.mark.skipif(
    not LIVE_FOLDER,
    reason="Set LIVE_FOLDER_ID to a folder the deployment identity can list",
)
def test_live_ls_folder(live_oauth):
    listed = _call_tool("drive_ls", {"folder_id": LIVE_FOLDER})
    assert listed.get("status") in {"COMPLETE", "PARTIAL", "EMPTY"}
    for child in listed.get("children") or []:
        assert "content" not in child
        assert child.get("id")
