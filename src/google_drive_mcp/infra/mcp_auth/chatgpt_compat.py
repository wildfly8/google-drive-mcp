"""HTTP routes and MCP wire tweaks ChatGPT and Claude connectors need.

ChatGPT developer-mode plugins and Claude custom connectors:

1. Fetch origin ``/.well-known/oauth-protected-resource`` (not only the RFC 9728
   path-suffixed URL) and prefer CIMD when authorization-server metadata
   advertises it. Token methods include ``none`` so CIMD intersection is
   public-client PKCE rather than ``private_key_jwt`` (which this AS cannot verify).
2. Use mixed authentication: ``initialize`` / ``tools/list`` without a Bearer so
   the host can scan tools, then OAuth on ``drive_*`` calls.
3. Advertise root-level ``securitySchemes``. Unauthenticated ``drive_*`` calls
   return HTTP 401 + ``WWW-Authenticate`` (Claude lazy-auth). JSON-RPC
   ``isError`` + ``_meta["mcp/www_authenticate"]`` remains the in-process fallback.
4. ``GET /mcp`` returns 405 immediately. Stateless Streamable HTTP has no SSE
   listen stream; a hanging GET makes Claude's connector probe time out.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.auth.handlers.metadata import MetadataHandler, ProtectedResourceMetadataHandler
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from mcp.server.auth.routes import build_metadata, cors_middleware
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import ProtectedResourceMetadata
from mcp_types import CallToolResult, TextContent
from pydantic import AnyHttpUrl
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.tokens import (
    MCP_OAUTH_SCOPE,
    issuer_url,
    resource_url,
    verify_authorization_header,
)

PROTECTED_TOOLS = frozenset({"drive_ls", "drive_find", "drive_read", "drive_grep"})

OAUTH2_SECURITY_SCHEMES: list[dict[str, Any]] = [{"type": "oauth2", "scopes": [MCP_OAUTH_SCOPE]}]

_CORS_HEADERS: list[tuple[bytes, bytes]] = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
    (
        b"access-control-allow-headers",
        b"authorization, content-type, accept, mcp-protocol-version, mcp-session-id, last-event-id",
    ),
    (b"access-control-expose-headers", b"mcp-session-id, www-authenticate"),
    (b"access-control-max-age", b"86400"),
]


def oauth_security_schemes() -> list[dict[str, Any]]:
    return [dict(scheme) for scheme in OAUTH2_SECURITY_SCHEMES]


def origin_resource_metadata_url(settings: Settings) -> str:
    return f"{issuer_url(settings).rstrip('/')}/.well-known/oauth-protected-resource"


def www_authenticate_challenge(
    settings: Settings,
    *,
    error: str = "invalid_token",
    description: str = "You need to login to continue",
) -> str:
    safe_error = error.replace('"', r"\"")
    safe_description = description.replace('"', r"\"")
    return (
        f'Bearer error="{safe_error}", error_description="{safe_description}", '
        f'resource_metadata="{origin_resource_metadata_url(settings)}"'
    )


def mcp_tool_result(payload: dict[str, Any], settings: Settings) -> dict[str, Any] | CallToolResult:
    """Keep success payloads as dicts; turn AUTHENTICATION_ERROR into ChatGPT's OAuth signal."""
    if payload.get("category") != "AUTHENTICATION_ERROR":
        return payload
    challenge = www_authenticate_challenge(settings)
    message = str(payload.get("message") or "Authentication required: no access token provided.")
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structured_content=payload,
        is_error=True,
        meta={"mcp/www_authenticate": [challenge]},
    )


def stamp_security_schemes(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return payload
    tools = result.get("tools")
    if not isinstance(tools, list):
        return payload
    schemes = oauth_security_schemes()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool["securitySchemes"] = schemes
        meta = tool.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
            tool["_meta"] = meta
        meta["securitySchemes"] = schemes
    return payload


def _rewrite_json_bytes(body: bytes) -> bytes:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body
    if not isinstance(payload, dict):
        return body
    stamped = stamp_security_schemes(payload)
    return json.dumps(stamped, separators=(",", ":")).encode("utf-8")


def _authorization_header(scope: Scope) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == b"authorization":
            return value.decode("latin-1")
    return None


def _calls_protected_tool(body: bytes) -> bool:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    messages = payload if isinstance(payload, list) else [payload]
    for message in messages:
        if not isinstance(message, dict) or message.get("method") != "tools/call":
            continue
        params = message.get("params")
        if isinstance(params, dict) and params.get("name") in PROTECTED_TOOLS:
            return True
    return False


async def _send_empty(send: Send, status: int, extra_headers: list[tuple[bytes, bytes]]) -> None:
    headers = list(_CORS_HEADERS)
    headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


async def _read_body(receive: Receive) -> bytes | None:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body") or b"")
        if not message.get("more_body"):
            return b"".join(chunks)


def _replay_body(body: bytes) -> Receive:
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _rewrite_sse_bytes(body: bytes) -> bytes:
    out: list[bytes] = []
    for raw_line in body.splitlines(keepends=True):
        line = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
        ended = raw_line.endswith(b"\n")
        if line.startswith(b"data:"):
            data = line[5:].lstrip()
            line = b"data: " + _rewrite_json_bytes(data)
        out.append(line + (b"\n" if ended else b""))
    return b"".join(out)


class _ChatGptMcpHttp:
    """Mixed-auth /mcp: CORS preflight, no Bearer on discovery, stamp securitySchemes."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method")
        if method == "OPTIONS":
            await _send_empty(send, 204, [])
            return
        if method == "GET":
            challenge = www_authenticate_challenge(self.settings)
            await _send_empty(
                send,
                405,
                [
                    (b"allow", b"POST, OPTIONS"),
                    (b"www-authenticate", challenge.encode("ascii")),
                ],
            )
            return

        body = await _read_body(receive)
        if body is None:
            return
        authed = verify_authorization_header(_authorization_header(scope), self.settings)
        if method == "POST" and not authed and _calls_protected_tool(body):
            challenge = www_authenticate_challenge(self.settings)
            payload = (
                b'{"error":"invalid_token",'
                b'"error_description":"Authentication required for this tool"}'
            )
            headers = list(_CORS_HEADERS)
            headers.extend(
                [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"www-authenticate", challenge.encode("ascii")),
                ]
            )
            await send({"type": "http.response.start", "status": 401, "headers": headers})
            await send({"type": "http.response.body", "body": payload})
            return

        start: dict[str, Any] | None = None
        content_type = b""
        buf = bytearray()

        async def send_wrapped(message: dict[str, Any]) -> None:
            nonlocal start, content_type
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])]
                keys = {k.lower() for k, _ in headers}
                for name, value in _CORS_HEADERS:
                    if name not in keys:
                        headers.append((name, value))
                content_type = b""
                for key, value in headers:
                    if key.lower() == b"content-type":
                        content_type = value.lower()
                start = {**message, "headers": headers}
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            buf.extend(message.get("body") or b"")
            if message.get("more_body"):
                return
            body = bytes(buf)
            if b"application/json" in content_type:
                body = _rewrite_json_bytes(body)
            elif b"text/event-stream" in content_type:
                body = _rewrite_sse_bytes(body)
            headers = []
            if start is not None:
                for key, value in start.get("headers", []):
                    if key.lower() == b"content-length":
                        continue
                    headers.append((key, value))
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, _replay_body(body), send_wrapped)


def install_chatgpt_mcp_http(app: Any, settings: Settings) -> None:
    """Drop RequireAuth on /mcp so hosts can scan tools, then stamp securitySchemes."""
    new_routes: list[Any] = []
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        path = getattr(route, "path", None)
        if path == "/mcp" and isinstance(endpoint, RequireAuthMiddleware):
            new_routes.append(Route("/mcp", endpoint=_ChatGptMcpHttp(endpoint.app, settings)))
        elif path == "/mcp":
            new_routes.append(Route("/mcp", endpoint=_ChatGptMcpHttp(endpoint, settings)))
        else:
            new_routes.append(route)
    app.router.routes = new_routes
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "WWW-Authenticate"],
    )


def chatgpt_compat_routes(settings: Settings) -> list[Route]:
    issuer = AnyHttpUrl(issuer_url(settings))
    resource = AnyHttpUrl(resource_url(settings))
    metadata = build_metadata(
        issuer,
        None,
        ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[MCP_OAUTH_SCOPE],
            default_scopes=[MCP_OAUTH_SCOPE],
        ),
        RevocationOptions(enabled=True),
    )
    metadata.token_endpoint_auth_methods_supported = [
        "none",
        "client_secret_post",
        "client_secret_basic",
    ]
    metadata.client_id_metadata_document_supported = True
    metadata.authorization_response_iss_parameter_supported = True
    prm = ProtectedResourceMetadata(
        resource=resource,
        authorization_servers=[issuer],
        scopes_supported=[MCP_OAUTH_SCOPE],
    )
    return [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(MetadataHandler(metadata).handle, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        ),
        Route(
            "/.well-known/oauth-protected-resource",
            endpoint=cors_middleware(
                ProtectedResourceMetadataHandler(prm).handle, ["GET", "OPTIONS"]
            ),
            methods=["GET", "OPTIONS"],
        ),
    ]
