"""Request body caps and per-address rate limits, ahead of every route.

The outermost ASGI middleware. A body over its path's cap gets 413 before any route
(or the /mcp wrapper, which buffers the whole body) sees it. OAuth endpoints anyone
can call without a token are rate-limited per client address, in this instance's
memory (best effort, like the billing limits).
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from google_drive_mcp.infra.billing.routes import _client_ip, _RateLimit

MCP_BODY_LIMIT = 4 * 1024 * 1024
WEBHOOK_BODY_LIMIT = 1024 * 1024
DEFAULT_BODY_LIMIT = 64 * 1024

# (method, path) -> (requests, window in seconds) per client address.
RATE_LIMITS: dict[tuple[str, str], tuple[int, int]] = {
    ("POST", "/register"): (20, 3600),
    ("POST", "/token"): (120, 60),
    ("POST", "/authorize"): (120, 60),
    # GET too: a new CIMD client_id on /authorize makes this server fetch a URL.
    ("GET", "/authorize"): (120, 60),
}


def body_limit(path: str) -> int:
    if path == "/mcp" or path.startswith("/mcp/"):
        return MCP_BODY_LIMIT
    if path == "/webhooks/stripe":
        return WEBHOOK_BODY_LIMIT
    return DEFAULT_BODY_LIMIT


async def _reply(send: Send, status: int, text: bytes, headers: list[tuple[bytes, bytes]]) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(text)).encode("ascii")),
                (b"cache-control", b"no-store"),
                # Lets browser-based clients read the status (this runs outside CORS).
                (b"access-control-allow-origin", b"*"),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": text})


def _replay(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # Later calls wait for the disconnect, as they would without this middleware.
        return await receive()

    return replay


class RequestLimits:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._hits = _RateLimit()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        rule = RATE_LIMITS.get((scope.get("method") or "", path))
        if rule is not None:
            limit, window = rule
            if not self._hits.allow(f"{path} {_client_ip(Request(scope))}", limit, window):
                retry = [(b"retry-after", str(window).encode("ascii"))]
                await _reply(send, 429, b"Too many requests", retry)
                return
        cap = body_limit(path)
        try:
            declared = int(Headers(scope=scope).get("content-length") or "0")
        except ValueError:
            declared = 0
        if declared > cap:
            await _reply(send, 413, b"Request body too large", [])
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client went away before the body was complete
            body.extend(message.get("body") or b"")
            if len(body) > cap:
                await _reply(send, 413, b"Request body too large", [])
                return
            if not message.get("more_body"):
                break
        await self.app(scope, _replay(bytes(body), receive), send)
