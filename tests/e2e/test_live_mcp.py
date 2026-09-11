"""Live Cloud Run smoke. Skipped unless LIVE_MCP_URL and MCP_AUTH_TOKEN are set.

Uses JSON-RPC over Streamable HTTP (no MCP client session) so teardown cannot
fail the run. Does not log secret values. Optional LIVE_DOC_FILE_ID /
LIVE_FOLDER_ID / LIVE_PHRASE exercise read/grep; unknown-id, missing-bearer,
and My Drive root listing always run when the URL is set.
"""

from __future__ import annotations

import json
import os

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


def _call_tool(name: str, arguments: dict, *, token: str | None = LIVE_TOKEN) -> dict:
    rpc = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.post(LIVE_URL, headers=_headers(token), json=rpc)
    assert token is None or LIVE_TOKEN not in response.text
    payload = _sse_payload(response)
    return _tool_body_from_rpc(payload)


def test_missing_bearer_is_authentication_error():
    body = _call_tool("drive_read", {"file_id": "does-not-exist"}, token=None)
    assert body.get("category") == "AUTHENTICATION_ERROR"
    assert "nested" not in json.dumps(body).lower()


def test_unknown_file_is_file_not_found():
    body = _call_tool(
        "drive_read", {"file_id": "00000000000000000000000000000000"}
    )
    assert body.get("category") == "FILE_NOT_FOUND"
    dumped = json.dumps(body)
    assert LIVE_TOKEN not in dumped
    assert "refresh" not in dumped.lower()


def test_live_ls_my_drive_root():
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
def test_live_read_and_grep_known_doc():
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
def test_live_ls_folder():
    listed = _call_tool("drive_ls", {"folder_id": LIVE_FOLDER})
    assert listed.get("status") in {"COMPLETE", "PARTIAL", "EMPTY"}
    for child in listed.get("children") or []:
        assert "content" not in child
        assert child.get("id")
