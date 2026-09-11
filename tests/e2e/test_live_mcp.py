"""Live Cloud Run smoke. Skipped unless LIVE_MCP_URL and MCP_AUTH_TOKEN are set.

Does not log secret values. Optional LIVE_DOC_FILE_ID / LIVE_FOLDER_ID / LIVE_PHRASE
exercise read/grep; unknown-id and missing-bearer always run when the URL is set.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

LIVE_URL = os.environ.get("LIVE_MCP_URL", "").rstrip("/")
LIVE_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
LIVE_DOC = os.environ.get("LIVE_DOC_FILE_ID", "")
LIVE_FOLDER = os.environ.get("LIVE_FOLDER_ID", "")
LIVE_PHRASE = os.environ.get("LIVE_PHRASE", "idempotency")

pytestmark = pytest.mark.skipif(
    not LIVE_URL or not LIVE_TOKEN,
    reason="Set LIVE_MCP_URL and MCP_AUTH_TOKEN for live Cloud Run E2E",
)


def _tool_body(result) -> dict:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        return structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"tool result was not a JSON object: {result!r}")


@pytest.fixture
async def live_client() -> AsyncIterator[Client]:
    headers = {"Authorization": f"Bearer {LIVE_TOKEN}"}
    async with httpx.AsyncClient(headers=headers, timeout=60.0) as http:
        async with Client(streamable_http_client(LIVE_URL, http_client=http)) as client:
            yield client


@pytest.mark.asyncio
async def test_missing_bearer_is_authentication_error():
    async with httpx.AsyncClient(timeout=30.0) as http:
        async with Client(streamable_http_client(LIVE_URL, http_client=http)) as client:
            result = await client.call_tool("drive_read", {"file_id": "does-not-exist"})
    body = _tool_body(result)
    assert body.get("category") == "AUTHENTICATION_ERROR"
    assert "nested" not in json.dumps(body).lower()


@pytest.mark.asyncio
async def test_unknown_file_is_file_not_found(live_client: Client):
    result = await live_client.call_tool(
        "drive_read", {"file_id": "00000000000000000000000000000000"}
    )
    body = _tool_body(result)
    assert body.get("category") == "FILE_NOT_FOUND"
    dumped = json.dumps(body)
    assert LIVE_TOKEN not in dumped
    assert "refresh" not in dumped.lower()


@pytest.mark.asyncio
async def test_live_ls_my_drive_root(live_client: Client):
    listed = _tool_body(await live_client.call_tool("drive_ls", {"max_results": 5}))
    assert listed.get("status") in {"COMPLETE", "PARTIAL", "EMPTY"}
    dumped = json.dumps(listed)
    assert LIVE_TOKEN not in dumped
    for child in listed.get("children") or []:
        assert "content" not in child
        assert child.get("id")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not LIVE_DOC,
    reason="Set LIVE_DOC_FILE_ID to a throwaway Doc the deployment identity can read",
)
async def test_live_read_and_grep_known_doc(live_client: Client):
    read = _tool_body(await live_client.call_tool("drive_read", {"file_id": LIVE_DOC}))
    assert read.get("status") in {"COMPLETE", "PARTIAL"}
    assert read.get("file_id") == LIVE_DOC
    assert LIVE_PHRASE in (read.get("content") or "")
    grep = _tool_body(
        await live_client.call_tool(
            "drive_grep",
            {"pattern": LIVE_PHRASE, "file_ids": [LIVE_DOC]},
        )
    )
    assert grep.get("matches")
    empty = _tool_body(
        await live_client.call_tool(
            "drive_grep",
            {"pattern": "no-such-phrase-xyz-live-e2e", "file_ids": [LIVE_DOC]},
        )
    )
    assert empty.get("status") == "EMPTY"
    assert empty.get("matches") == []


@pytest.mark.asyncio
@pytest.mark.skipif(
    not LIVE_FOLDER,
    reason="Set LIVE_FOLDER_ID to a folder the deployment identity can list",
)
async def test_live_ls_folder(live_client: Client):
    listed = _tool_body(
        await live_client.call_tool("drive_ls", {"folder_id": LIVE_FOLDER})
    )
    assert listed.get("status") in {"COMPLETE", "PARTIAL", "EMPTY"}
    for child in listed.get("children") or []:
        assert "content" not in child
        assert child.get("id")
