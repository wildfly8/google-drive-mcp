"""Each HTTP request starts with no Drive binding from an earlier one (Article III).

A request binds its own Drive client and credentials. If the binding of an earlier request in
the same context were still in place, a later request that never bound its own would read
Drive as someone else's call.
"""

from __future__ import annotations

import asyncio

from google_drive_mcp.mcp import middleware
from google_drive_mcp.mcp.server import _AuthorizationHeaderMiddleware


def test_a_request_does_not_inherit_the_previous_requests_drive():
    seen: list[object] = []

    async def inner(scope, receive, send):
        seen.append(middleware._request_drive.get())

    wrapper = _AuthorizationHeaderMiddleware(inner)
    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
    middleware._request_drive.set("the drive an earlier request bound")
    try:
        asyncio.run(wrapper(scope, None, None))
    finally:
        middleware._request_drive.set(None)
    assert seen == [None]
