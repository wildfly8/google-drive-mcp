"""Composition root. Streamable HTTP MCP server; mounts tools.py.

Read-only: only drive_ls, drive_find, drive_read, drive_grep are registered.
Drive clients are constructed per request from env secrets (tests inject FakeDrive).
"""

from __future__ import annotations

import os
from typing import Any

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.mcp.middleware import (
    Runtime,
    get_authorization,
    reset_request_drive,
    set_authorization,
)
from google_drive_mcp.mcp.tools import handle_tool

try:
    from mcp.server.mcpserver import Context, MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[assignment]

    Context = Any  # type: ignore[assignment,misc]


def build_runtime(settings: Settings | None = None, drive: Any | None = None) -> Runtime:
    settings = settings or Settings.from_env()
    return Runtime(settings=settings, drive=drive)


def _authorization_from_ctx(ctx: Any) -> str | None:
    if ctx is not None:
        try:
            headers = ctx.headers
        except Exception:
            headers = None
        if headers:
            for key, value in headers.items():
                if str(key).lower() == "authorization":
                    set_authorization(value)
                    return value
    return get_authorization()


def create_server(runtime: Runtime | None = None) -> MCPServer:
    runtime = runtime or build_runtime()
    server = MCPServer("google-drive-mcp")

    @server.tool()
    def drive_ls(
        folder_id: str | None = None,
        max_results: int | None = None,
        page_token: str | None = None,
        ctx: Context | None = None,
    ) -> dict:
        return handle_tool(
            runtime,
            "drive_ls",
            {
                "folder_id": folder_id,
                "max_results": max_results,
                "page_token": page_token,
            },
            _authorization_from_ctx(ctx),
        )

    @server.tool()
    def drive_find(
        name_pattern: str | None = None,
        mime_type: str | None = None,
        folder_id: str | None = None,
        modified_after: str | None = None,
        modified_before: str | None = None,
        trashed: bool = False,
        max_results: int | None = None,
        ctx: Context | None = None,
    ) -> dict:
        return handle_tool(
            runtime,
            "drive_find",
            {
                "name_pattern": name_pattern,
                "mime_type": mime_type,
                "folder_id": folder_id,
                "modified_after": modified_after,
                "modified_before": modified_before,
                "trashed": trashed,
                "max_results": max_results,
            },
            _authorization_from_ctx(ctx),
        )

    @server.tool()
    def drive_read(
        file_id: str,
        content_format: str | None = None,
        max_bytes: int | None = None,
        ctx: Context | None = None,
    ) -> dict:
        return handle_tool(
            runtime,
            "drive_read",
            {
                "file_id": file_id,
                "content_format": content_format,
                "max_bytes": max_bytes,
            },
            _authorization_from_ctx(ctx),
        )

    @server.tool()
    def drive_grep(
        pattern: str,
        file_ids: list[str] | None = None,
        folder_id: str | None = None,
        case_sensitive: bool = True,
        regex: bool = False,
        context_lines: int = 2,
        max_matches: int | None = None,
        ctx: Context | None = None,
    ) -> dict:
        return handle_tool(
            runtime,
            "drive_grep",
            {
                "pattern": pattern,
                "file_ids": file_ids,
                "folder_id": folder_id,
                "case_sensitive": case_sensitive,
                "regex": regex,
                "context_lines": context_lines,
                "max_matches": max_matches,
            },
            _authorization_from_ctx(ctx),
        )

    server._runtime = runtime  # type: ignore[attr-defined]
    return server


class _AuthorizationHeaderMiddleware:
    """Capture Bearer from Streamable HTTP and isolate request-scoped Drive clients.

    Registered on the Starlette app (not a raw ASGI wrap) so lifespan still
    starts the MCP session manager.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
            set_authorization(headers.get("authorization"))
            reset_request_drive()
        await self.app(scope, receive, send)


def streamable_app(runtime: Runtime | None = None, *, json_response: bool = False):
    server = create_server(runtime)
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=json_response,
        host="0.0.0.0",
    )
    app.add_middleware(_AuthorizationHeaderMiddleware)
    return app


def main() -> None:
    import uvicorn

    runtime = build_runtime()
    app = streamable_app(runtime)
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
