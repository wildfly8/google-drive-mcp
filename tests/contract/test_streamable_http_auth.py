"""Streamable HTTP contract tests: Bearer must be present before Drive I/O."""

from __future__ import annotations

from starlette.testclient import TestClient

from fakes.fake_drive import FakeDrive
from google_drive_mcp.mcp.server import streamable_app


HEADERS_JSON = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


def _tool_call(file_id: str = "nested-doc") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "drive_read",
            "arguments": {"file_id": file_id},
        },
    }


def _post(app, headers: dict, body: dict):
    with TestClient(app) as client:
        return client.post("/mcp", headers=headers, json=body)


def test_http_missing_bearer_never_hits_drive(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    app = streamable_app(runtime, json_response=True)
    response = _post(app, HEADERS_JSON, _tool_call())
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count == 0
    assert response.status_code in {200, 401, 400}


def test_http_invalid_bearer_never_hits_drive(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    app = streamable_app(runtime, json_response=True)
    headers = {**HEADERS_JSON, "authorization": "Bearer wrong-token"}
    response = _post(app, headers, _tool_call())
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count == 0
    body = response.text.lower()
    assert response.status_code in {200, 401, 400} or "authentication" in body
