"""Composition root. Streamable HTTP MCP server; mounts tools.py.

Read-only: no mutating tools are registered. Drive client is constructed
per request from env secrets (tests inject FakeDrive).
"""

from __future__ import annotations

import os
from typing import Any

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.google_auth.refresh_token import mint_readonly_credentials
from google_drive_mcp.mcp.middleware import Runtime, get_authorization, set_authorization
from google_drive_mcp.mcp.tools import READ_ONLY_TOOLS, handle_tool

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[assignment]


def build_runtime(settings: Settings | None = None, drive: Any | None = None) -> Runtime:
    settings = settings or Settings.from_env()
    if drive is None:
        from google_drive_mcp.infra.google_drive.client import GoogleDriveClient

        creds = mint_readonly_credentials(settings)
        drive = GoogleDriveClient(creds)
    return Runtime(settings=settings, drive=drive)


def create_server(runtime: Runtime | None = None) -> MCPServer:
    runtime = runtime or build_runtime()
    server = MCPServer("google-drive-mcp")

    @server.tool()
    def drive_ls(
        folder_id: str | None = None,
        max_results: int | None = None,
        page_token: str | None = None,
    ) -> dict:
        return handle_tool(
            runtime,
            "drive_ls",
            {
                "folder_id": folder_id,
                "max_results": max_results,
                "page_token": page_token,
            },
            get_authorization(),
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
            get_authorization(),
        )

    @server.tool()
    def drive_read(
        file_id: str,
        content_format: str | None = None,
        max_bytes: int | None = None,
    ) -> dict:
        return handle_tool(
            runtime,
            "drive_read",
            {
                "file_id": file_id,
                "content_format": content_format,
                "max_bytes": max_bytes,
            },
            get_authorization(),
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
            get_authorization(),
        )

    @server.tool()
    def scope_probe(folder_id: str | None = None, file_ids: list[str] | None = None) -> dict:
        """US1 AUTH test vehicle (same argument shape as drive_grep)."""
        return handle_tool(
            runtime,
            "scope_probe",
            {"folder_id": folder_id, "file_ids": file_ids},
            get_authorization(),
        )

    server._runtime = runtime  # type: ignore[attr-defined]
    assert all(t in READ_ONLY_TOOLS or t == "scope_probe" for t in ("drive_ls", "drive_find", "drive_read", "drive_grep"))
    return server


def _wrap_auth(app):
    async def asgi(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
            set_authorization(headers.get("authorization"))
        await app(scope, receive, send)

    return asgi


def streamable_app(runtime: Runtime | None = None):
    server = create_server(runtime)
    app = server.streamable_http_app(stateless_http=True)
    return _wrap_auth(app)


def main() -> None:
    runtime = build_runtime()
    server = create_server(runtime)
    port = int(os.environ.get("PORT", "8080"))
    server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
