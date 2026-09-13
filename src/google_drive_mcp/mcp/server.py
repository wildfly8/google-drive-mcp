"""Composition root. Streamable HTTP MCP server; mounts tools.py.

Read-only: only drive_ls, drive_find, drive_read, drive_grep are registered.
Drive clients are constructed per request from env secrets (tests inject FakeDrive).
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from pydantic import Field

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.mcp.middleware import (
    Runtime,
    get_authorization,
    reset_request_drive,
    set_authorization,
)
from google_drive_mcp.mcp.tool_schema import (
    DRIVE_FIND_DESCRIPTION,
    DRIVE_FIND_TITLE,
    DRIVE_GREP_DESCRIPTION,
    DRIVE_GREP_TITLE,
    DRIVE_LS_DESCRIPTION,
    DRIVE_LS_TITLE,
    DRIVE_READ_DESCRIPTION,
    DRIVE_READ_TITLE,
    READ_ONLY_ANNOTATIONS,
    SERVER_DESCRIPTION,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_TITLE,
    SERVER_VERSION,
)
from google_drive_mcp.mcp.tools import handle_tool
from google_drive_mcp.mcp.validation import (
    CONTEXT_LINES_MAX,
    CONTEXT_LINES_MIN,
    FILE_ID_PATTERN,
    MAX_BYTES_MAX,
    MAX_BYTES_MIN,
    MAX_MATCHES_MAX,
    MAX_MATCHES_MIN,
    MAX_RESULTS_MAX,
    MAX_RESULTS_MIN,
)

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
    server = MCPServer(
        SERVER_NAME,
        title=SERVER_TITLE,
        description=SERVER_DESCRIPTION,
        instructions=SERVER_INSTRUCTIONS,
        version=SERVER_VERSION,
    )

    @server.tool(
        title=DRIVE_LS_TITLE,
        description=DRIVE_LS_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=False,
    )
    def drive_ls(
        folder_id: Annotated[
            str | None,
            Field(
                default=None,
                pattern=FILE_ID_PATTERN,
                description=(
                    "Drive folder id whose immediate children to list. Omit to use the "
                    "deployment default scope (My Drive root, or DRIVE_ALLOWED_FOLDER_ID "
                    "when configured). Not a filename."
                ),
            ),
        ] = None,
        max_results: Annotated[
            int | None,
            Field(
                default=None,
                ge=MAX_RESULTS_MIN,
                le=MAX_RESULTS_MAX,
                description=f"Page size {MAX_RESULTS_MIN}–{MAX_RESULTS_MAX}. More children → PARTIAL + next_page_token.",
            ),
        ] = None,
        page_token: Annotated[
            str | None,
            Field(
                default=None,
                description="Opaque token from a previous PARTIAL drive_ls (decimal integer string). Omit on the first page.",
            ),
        ] = None,
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

    @server.tool(
        title=DRIVE_FIND_TITLE,
        description=DRIVE_FIND_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=False,
    )
    def drive_find(
        name_pattern: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Case-insensitive substring of the filename only (not glob, not contents). "
                    "Example: 'activity-2025' matches activity-2025.mdx. Do not pass a user question."
                ),
            ),
        ] = None,
        mime_type: Annotated[
            str | None,
            Field(
                default=None,
                description="Exact Drive MIME type filter, e.g. application/vnd.google-apps.folder or application/octet-stream.",
            ),
        ] = None,
        folder_id: Annotated[
            str | None,
            Field(
                default=None,
                pattern=FILE_ID_PATTERN,
                description="Restrict to this folder and its descendants. Omit for the deployment default scope.",
            ),
        ] = None,
        modified_after: Annotated[
            str | None,
            Field(
                default=None,
                description="Inclusive ISO-8601 lower bound on file modifiedTime (e.g. 2025-01-01T00:00:00Z).",
            ),
        ] = None,
        modified_before: Annotated[
            str | None,
            Field(
                default=None,
                description="Inclusive ISO-8601 upper bound on file modifiedTime.",
            ),
        ] = None,
        trashed: Annotated[
            bool,
            Field(description="If true, include trashed files. Default false."),
        ] = False,
        max_results: Annotated[
            int | None,
            Field(
                default=None,
                ge=MAX_RESULTS_MIN,
                le=MAX_RESULTS_MAX,
                description=f"Max candidates {MAX_RESULTS_MIN}–{MAX_RESULTS_MAX}. Remaining descendants → PARTIAL.",
            ),
        ] = None,
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

    @server.tool(
        title=DRIVE_READ_TITLE,
        description=DRIVE_READ_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=False,
    )
    def drive_read(
        file_id: Annotated[
            str,
            Field(
                pattern=FILE_ID_PATTERN,
                description="Drive file id from ls/find/grep. Not a filename, folder id, URL, or search phrase.",
            ),
        ],
        content_format: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Optional export MIME. Omit for the default map (Docs/Slides text/plain, "
                    "Sheets text/csv, text blobs as stored). Unknown or type-incompatible → INVALID_ARGUMENT."
                ),
            ),
        ] = None,
        max_bytes: Annotated[
            int | None,
            Field(
                default=None,
                ge=MAX_BYTES_MIN,
                le=MAX_BYTES_MAX,
                description=f"Cap exported bytes ({MAX_BYTES_MIN}–{MAX_BYTES_MAX}). Truncation → PARTIAL with prefix.",
            ),
        ] = None,
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

    @server.tool(
        title=DRIVE_GREP_TITLE,
        description=DRIVE_GREP_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=False,
    )
    def drive_grep(
        pattern: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Exact phrase to find in exported file bytes (literal unless regex=true). "
                    "Use a short distinctive term from the user question, not the whole question."
                ),
            ),
        ],
        file_ids: Annotated[
            list[str] | None,
            Field(
                default=None,
                description="Specific Drive file ids to search. Prefer this over a whole-folder walk when ids are known.",
            ),
        ] = None,
        folder_id: Annotated[
            str | None,
            Field(
                default=None,
                pattern=FILE_ID_PATTERN,
                description=(
                    "Search this folder and descendants. Omit with no file_ids for the default scope. "
                    "If set together with file_ids, each id must lie in that folder."
                ),
            ),
        ] = None,
        case_sensitive: Annotated[
            bool,
            Field(description="Literal/regex case sensitivity. Default true. Use false for natural-language terms."),
        ] = True,
        regex: Annotated[
            bool,
            Field(description="If true, pattern is a regular expression. Default false (literal, re.escape)."),
        ] = False,
        context_lines: Annotated[
            int,
            Field(
                ge=CONTEXT_LINES_MIN,
                le=CONTEXT_LINES_MAX,
                description=f"Lines of context around each hit ({CONTEXT_LINES_MIN}–{CONTEXT_LINES_MAX}). Default 2.",
            ),
        ] = 2,
        max_matches: Annotated[
            int | None,
            Field(
                default=None,
                ge=MAX_MATCHES_MIN,
                le=MAX_MATCHES_MAX,
                description=f"Stop after this many hits ({MAX_MATCHES_MIN}–{MAX_MATCHES_MAX}). Hitting the cap → PARTIAL.",
            ),
        ] = None,
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
