"""/mcp answers stay near their UTF-8 size; only tools/list is rewritten.

Cloud Run caps an HTTP/1 response at 32 MiB. A 19.5 MB CJK drive_read must not
be re-encoded with \\uXXXX escapes (about 39 MB) on its way out.
"""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from fakes.fake_drive import FakeDrive, FakeFile
from google_drive_mcp.infra.mcp_auth.chatgpt_compat import (
    _ChatGptMcpHttp,
    oauth_security_schemes,
)
from google_drive_mcp.mcp.server import streamable_app

HEADERS_JSON = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}
CLOUD_RUN_RESPONSE_CAP = 32 * 1024 * 1024


def _cjk_text(target_bytes: int) -> str:
    line = "漢字かな交じり文の検索と読み取り。" * 20 + "\n"
    repeat = target_bytes // len(line.encode("utf-8")) + 1
    return (line * repeat)[: target_bytes // 3]


def test_cjk_drive_read_body_stays_near_its_utf8_size(runtime, fake_drive: FakeDrive, authz):
    text = _cjk_text(19_500_000)
    utf8_size = len(text.encode("utf-8"))
    assert 19_000_000 < utf8_size <= 19_500_000
    fake_drive.add(
        FakeFile(
            id="cjk-file", name="cjk.txt", mime_type="text/plain", parents=["root"], content=text
        )
    )
    with TestClient(streamable_app(runtime, json_response=True)) as client:
        response = client.post(
            "/mcp",
            headers={**HEADERS_JSON, "authorization": authz},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "drive_read", "arguments": {"file_id": "cjk-file"}},
            },
        )
    assert response.status_code == 200
    body = response.content
    assert len(body) < CLOUD_RUN_RESPONSE_CAP
    # Roughly the UTF-8 size: the text is never \uXXXX-escaped.
    assert len(body) < utf8_size * 1.05
    result = json.loads(json.loads(body)["result"]["content"][0]["text"])
    assert result["status"] == "COMPLETE"
    assert result["content"] == text


def test_tools_list_keeps_security_schemes_and_raw_utf8(runtime):
    with TestClient(streamable_app(runtime, json_response=True)) as client:
        listed = client.post(
            "/mcp",
            headers=HEADERS_JSON,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
    assert listed.status_code == 200
    assert int(listed.headers["content-length"]) == len(listed.content)
    tools = listed.json()["result"]["tools"]
    for tool in tools:
        assert tool["securitySchemes"] == oauth_security_schemes()
        assert tool["_meta"]["securitySchemes"] == oauth_security_schemes()
    # Descriptions use "→" and "—"; the rewrite keeps them as UTF-8.
    assert "→".encode() in listed.content
    assert b"\\u2192" not in listed.content


def test_401_and_405_challenges_name_the_scope(runtime):
    with TestClient(streamable_app(runtime, json_response=True)) as client:
        unauthenticated = client.post(
            "/mcp",
            headers=HEADERS_JSON,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "drive_read", "arguments": {"file_id": "nested-doc"}},
            },
        )
        get = client.get("/mcp")
    assert unauthenticated.status_code == 401
    assert 'scope="drive.read"' in unauthenticated.headers["www-authenticate"]
    assert "resource_metadata=" in unauthenticated.headers["www-authenticate"]
    assert get.status_code == 405
    assert 'scope="drive.read"' in get.headers["www-authenticate"]


def _receive_json(payload: object):
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            body = json.dumps(payload).encode()
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _scope(authorization: str | None = None) -> dict:
    headers = [(b"content-type", b"application/json")]
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}


async def test_tool_call_answer_streams_through_unbuffered(settings, authz):
    events: list[str] = []
    first = b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"'
    second = '漢字"}]}}'.encode()

    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": first, "more_body": True})
        events.append("downstream sent first chunk")
        await send({"type": "http.response.body", "body": second, "more_body": False})

    received: list[dict] = []

    async def send(message):
        events.append(f"client got {message['type']}")
        received.append(message)

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "drive_read", "arguments": {"file_id": "nested-doc"}},
    }
    await _ChatGptMcpHttp(downstream, settings)(_scope(authz), _receive_json(request), send)
    # The first chunk reached the client before the second was produced.
    assert events.index("client got http.response.body") < events.index(
        "downstream sent first chunk"
    )
    bodies = [m["body"] for m in received if m["type"] == "http.response.body"]
    assert bodies == [first, second]


async def test_batch_with_tools_list_is_stamped(settings):
    tool = {"name": "drive_ls", "description": "列 →"}
    answer = [
        {"jsonrpc": "2.0", "id": 1, "result": {"tools": [tool]}},
        {"jsonrpc": "2.0", "id": 2, "result": {}},
    ]

    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": json.dumps(answer).encode()})

    received: list[dict] = []

    async def send(message):
        received.append(message)

    request = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    await _ChatGptMcpHttp(downstream, settings)(_scope(), _receive_json(request), send)
    start = next(m for m in received if m["type"] == "http.response.start")
    body = b"".join(m["body"] for m in received if m["type"] == "http.response.body")
    assert dict(start["headers"])[b"content-length"] == str(len(body)).encode()
    stamped = json.loads(body)
    assert stamped[0]["result"]["tools"][0]["securitySchemes"] == oauth_security_schemes()
    assert stamped[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert "列 →".encode() in body
