"""Composition root. Streamable HTTP MCP server; mounts tools.py.

Read-only: only drive_ls, drive_find, drive_read, drive_grep are registered.
Drive clients are constructed per request from env secrets (tests inject FakeDrive).
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from pydantic import AnyHttpUrl, Field

from google_drive_mcp.access_control.allowed_folder import check_allowed_folder
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    ENTITLEMENT_TTL,
    RESUME_COOKIE,
    mint_entitlement,
    safe_resume,
    set_current_scid,
    verify_entitlement,
)
from google_drive_mcp.infra.billing.routes import (
    entitlement_from_request,
    stripe_webhook_post,
    subscribe_checkout_post,
    subscribe_complete_get,
    subscribe_email_post,
    subscribe_email_verify_get,
    subscribe_email_verify_post,
    subscribe_get,
    subscribe_manage_post,
    subscribe_signout_post,
)
from google_drive_mcp.infra.billing.gateway import BillingUnavailable
from google_drive_mcp.infra.billing.stripe_api import StripeHttpGateway
from google_drive_mcp.infra.billing.email_link import IdentityPlatformEmailLink
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.chatgpt_compat import (
    chatgpt_compat_routes,
    install_chatgpt_mcp_http,
    mcp_tool_result,
    oauth_security_schemes,
)
from google_drive_mcp.infra.mcp_auth.consent import consent_get, consent_post
from google_drive_mcp.infra.mcp_auth.setup import setup_get
from google_drive_mcp.infra.mcp_auth.stats import stats_get, stats_snapshot
from google_drive_mcp.infra.mcp_auth.provider import DriveMcpOAuthProvider
from google_drive_mcp.infra.mcp_auth.tokens import MCP_OAUTH_SCOPE, issuer_url, resource_url
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


_LOG = logging.getLogger("google_drive_mcp")

def build_runtime(settings: Settings | None = None, drive: Any | None = None) -> Runtime:
    if settings is None:
        settings = Settings.from_env()
        # Only kb is readable: never serve from an environment without it.
        settings.require_allowed_folder()
        # Never sign tokens and cookies with a guessable key.
        settings.require_signing_material()
    billing = None
    if settings.stripe_secret_key.get_secret_value().strip():
        billing = StripeHttpGateway(settings)
    email_link = None
    if settings.identity_toolkit_api_key.get_secret_value().strip():
        email_link = IdentityPlatformEmailLink(settings)
    return Runtime(settings=settings, drive=drive, billing=billing, email_link=email_link)


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


def _auth_settings(settings: Settings):
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

    issuer = issuer_url(settings)
    if not issuer:
        raise ValueError(
            "MCP_PUBLIC_URL is required for Streamable HTTP OAuth "
            "(HTTPS origin, no path, no /mcp suffix)"
        )
    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(resource_url(settings)),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[MCP_OAUTH_SCOPE],
            default_scopes=[MCP_OAUTH_SCOPE],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[MCP_OAUTH_SCOPE],
        validate_token_resource=True,
    )


def create_server(runtime: Runtime | None = None) -> MCPServer:
    runtime = runtime or build_runtime()
    settings = runtime.settings
    provider = DriveMcpOAuthProvider(
        settings, telemetry=runtime.telemetry, billing=runtime.billing
    )
    server = MCPServer(
        SERVER_NAME,
        title=SERVER_TITLE,
        description=SERVER_DESCRIPTION,
        instructions=SERVER_INSTRUCTIONS,
        version=SERVER_VERSION,
        auth=_auth_settings(settings),
        auth_server_provider=provider,
    )

    @server.custom_route("/consent", methods=["GET", "POST"])
    async def consent(request):
        if request.method == "POST":
            return await consent_post(request, provider, settings)
        return await consent_get(request, settings, provider)

    @server.custom_route("/setup", methods=["GET"])
    async def claude_setup(request):
        scid = entitlement_from_request(request, settings)
        entitled = True
        if settings.mcp_subscription_required:
            entitled = bool(
                scid and await run_in_threadpool(runtime.billing.is_subscription_active, scid)
            )
        # The paid setup page never shows usage counts, so skip the log scan.
        stats = None if settings.mcp_subscription_required else stats_snapshot(runtime.telemetry)
        return setup_get(
            request, settings, stats, entitled=entitled, lapsed=bool(scid) and not entitled
        )

    @server.custom_route("/subscribe", methods=["GET"])
    async def subscribe_page(request):
        from google_drive_mcp.infra.billing.gateway import InactiveBilling as _Inactive

        configured = not isinstance(runtime.billing, _Inactive)
        return await run_in_threadpool(
            subscribe_get,
            request,
            settings,
            runtime.billing,
            runtime.email_link,
            configured=configured,
        )

    @server.custom_route("/subscribe/email", methods=["POST"])
    async def subscribe_email(request):
        return await subscribe_email_post(request, settings, runtime.billing, runtime.email_link)

    @server.custom_route("/subscribe/email/verify", methods=["GET", "POST"])
    async def subscribe_email_verify(request):
        if request.method == "POST":
            return await subscribe_email_verify_post(
                request, settings, runtime.billing, runtime.email_link
            )
        return subscribe_email_verify_get(request, settings)

    @server.custom_route("/subscribe/checkout", methods=["POST"])
    async def subscribe_checkout(request):
        return await subscribe_checkout_post(request, settings, runtime.billing)

    @server.custom_route("/subscribe/complete", methods=["GET"])
    async def subscribe_complete(request):
        return await subscribe_complete_get(request, settings, runtime.billing)

    @server.custom_route("/subscribe/manage", methods=["POST"])
    async def subscribe_manage(request):
        return await subscribe_manage_post(request, settings, runtime.billing)

    @server.custom_route("/subscribe/signout", methods=["POST"])
    async def subscribe_signout(request):
        return await subscribe_signout_post(request, settings)

    @server.custom_route("/webhooks/stripe", methods=["POST"])
    async def stripe_hook(request):
        return await stripe_webhook_post(request, settings)

    @server.custom_route("/stats", methods=["GET"])
    async def connect_stats(request):
        # Public page: with the paywall on, leave out console links (they name the
        # GCP project).
        return stats_get(
            request, runtime.telemetry, links=not settings.mcp_subscription_required
        )

    tool_meta = {"securitySchemes": oauth_security_schemes()}

    def _dispatch(name: str, arguments: dict[str, Any], ctx: Context | None) -> Any:
        return mcp_tool_result(
            handle_tool(runtime, name, arguments, _authorization_from_ctx(ctx)),
            settings,
        )

    @server.tool(
        title=DRIVE_LS_TITLE,
        description=DRIVE_LS_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        meta=tool_meta,
        structured_output=False,
    )
    def drive_ls(
        folder_id: Annotated[
            str | None,
            Field(
                default=None,
                pattern=FILE_ID_PATTERN,
                description=(
                    "Drive folder id whose immediate children to list. Omit to list the kb folder. "
                    "A folder outside kb is AUTHORIZATION_ERROR. Not a filename."
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
    ) -> Any:
        return _dispatch(
            "drive_ls",
            {
                "folder_id": folder_id,
                "max_results": max_results,
                "page_token": page_token,
            },
            ctx,
        )

    @server.tool(
        title=DRIVE_FIND_TITLE,
        description=DRIVE_FIND_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        meta=tool_meta,
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
                description=(
                    "Restrict to this folder and its descendants inside kb. Omit to search kb. "
                    "A folder outside kb is AUTHORIZATION_ERROR."
                ),
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
                description=(
                    f"Max matching files {MAX_RESULTS_MIN}–{MAX_RESULTS_MAX}. Matching folders are "
                    "listed under their own cap of the same size, unless mime_type is the folder "
                    "type. "
                    "More matches remaining → PARTIAL."
                ),
            ),
        ] = None,
        ctx: Context | None = None,
    ) -> Any:
        return _dispatch(
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
            ctx,
        )

    @server.tool(
        title=DRIVE_READ_TITLE,
        description=DRIVE_READ_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        meta=tool_meta,
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
    ) -> Any:
        return _dispatch(
            "drive_read",
            {
                "file_id": file_id,
                "content_format": content_format,
                "max_bytes": max_bytes,
            },
            ctx,
        )

    @server.tool(
        title=DRIVE_GREP_TITLE,
        description=DRIVE_GREP_DESCRIPTION,
        annotations=READ_ONLY_ANNOTATIONS,
        meta=tool_meta,
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
            list[Annotated[str, Field(pattern=FILE_ID_PATTERN, min_length=1, max_length=128)]]
            | None,
            Field(
                default=None,
                description="Specific Drive file ids to search. Prefer one id when the file is many megabytes; a call stops at 20 MB.",
            ),
        ] = None,
        folder_id: Annotated[
            str | None,
            Field(
                default=None,
                pattern=FILE_ID_PATTERN,
                description=(
                    "Search this folder and descendants inside kb. Omit with no file_ids to search kb. "
                    "A folder or file outside kb is AUTHORIZATION_ERROR. "
                    "If set together with file_ids, each id must lie in that folder."
                ),
            ),
        ] = None,
        next_cursor: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Continue a previous drive_grep. Paste that result's next_cursor value here exactly "
                    "(a file id, or file_id:N to continue inside that file). Use the same pattern, "
                    "case_sensitive, regex and scope: the same folder_id (omit it again to stay in "
                    "kb) or the same file_ids. Empty string starts at the first file."
                ),
            ),
        ] = "",
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
                description=(
                    f"Stop after this many matches ({MAX_MATCHES_MIN}–{MAX_MATCHES_MAX}). "
                    "In text files a match is one line (location.occurrences counts hits on it); "
                    "in Sheets, Slides, CSV and JSON each hit is a match. "
                    "Stopping at the cap with more left → PARTIAL with next_cursor."
                ),
            ),
        ] = None,
        cursor: Annotated[
            str,
            Field(
                default="",
                description=(
                    "Alias of next_cursor. Paste the previous drive_grep result's next_cursor value. "
                    "If both names are set they must be the same value. Empty string starts at the first file."
                ),
            ),
        ] = "",
        ctx: Context | None = None,
    ) -> Any:
        return _dispatch(
            "drive_grep",
            {
                "pattern": pattern,
                "file_ids": file_ids,
                "folder_id": folder_id,
                "case_sensitive": case_sensitive,
                "regex": regex,
                "context_lines": context_lines,
                "max_matches": max_matches,
                "next_cursor": next_cursor,
                "cursor": cursor,
            },
            ctx,
        )

    server._runtime = runtime  # type: ignore[attr-defined]
    return server


class _AuthorizationHeaderMiddleware:
    """Capture Bearer from Streamable HTTP and isolate request-scoped Drive clients.

    Registered on the Starlette app (not a raw ASGI wrap) so lifespan still
    starts the MCP session manager.
    """

    def __init__(self, app, settings: Settings | None = None):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        set_authorization(headers.get("authorization"))
        reset_request_drive()
        scid = None
        resume_cookie: bytes | None = None
        if self.settings is not None:
            from urllib.parse import quote

            # The entitlement is only ever the HttpOnly cookie, never a URL value.
            cookies = headers.get("cookie") or ""
            raw = None
            for part in cookies.split(";"):
                if "=" not in part:
                    continue
                name, value = part.strip().split("=", 1)
                if name == COOKIE_NAME:
                    raw = value
                    break
            scid = verify_entitlement(raw, self.settings)
            path = scope.get("path") or ""
            method = scope.get("method") or "GET"
            if (
                method == "GET"
                and path == "/authorize"
                and self.settings.mcp_subscription_required
            ):
                # Remember the in-progress Connect so it resumes after payment or
                # the email link, whether the browser has no subscription or a lapsed one.
                query = (scope.get("query_string") or b"").decode("latin-1")
                resume = "/authorize" + (f"?{query}" if query else "")
                if safe_resume(resume):
                    secure = issuer_url(self.settings).startswith("https://")
                    resume_cookie = (
                        f"{RESUME_COOKIE}={quote(resume, safe='')}; HttpOnly; Path=/; "
                        f"Max-Age=3600; SameSite=Lax"
                        + ("; Secure" if secure else "")
                    ).encode()
                    if not scid:
                        await send(
                            {
                                "type": "http.response.start",
                                "status": 302,
                                "headers": [
                                    (b"location", b"/subscribe"),
                                    (b"set-cookie", resume_cookie),
                                ],
                            }
                        )
                        await send({"type": "http.response.body", "body": b""})
                        return
        set_current_scid(scid)
        subscribe_url = (
            f"{issuer_url(self.settings).rstrip('/')}/subscribe".encode()
            if self.settings is not None
            else b""
        )

        async def send_renewed(message):
            if (
                message["type"] == "http.response.start"
                and scid
                and self.settings is not None
                and self.settings.mcp_subscription_required
            ):
                headers = list(message.get("headers") or [])
                prefix = f"{COOKIE_NAME}=".encode()
                # A route that just set a new entitlement (Checkout return, email link)
                # wins; renewing the old cookie after it would put the old one back.
                if not any(
                    k.lower() == b"set-cookie" and v.startswith(prefix) for k, v in headers
                ):
                    token = mint_entitlement(self.settings, customer_id=scid)
                    secure = issuer_url(self.settings).startswith("https://")
                    cookie = (
                        f"{COOKIE_NAME}={token}; HttpOnly; Path=/; Max-Age={ENTITLEMENT_TTL}; "
                        "SameSite=Lax" + ("; Secure" if secure else "")
                    )
                    headers.append((b"set-cookie", cookie.encode()))
                # A lapsed subscriber sent to /subscribe resumes this Connect after paying.
                if resume_cookie and any(
                    k.lower() == b"location" and v.split(b"?")[0] in {b"/subscribe", subscribe_url}
                    for k, v in headers
                ):
                    headers.append((b"set-cookie", resume_cookie))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_renewed)


def streamable_app(runtime: Runtime | None = None, *, json_response: bool = True):
    server = create_server(runtime)
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=json_response,
        host="0.0.0.0",
    )
    runtime = runtime or getattr(server, "_runtime", None) or build_runtime()
    app.router.routes = [*chatgpt_compat_routes(runtime.settings), *app.router.routes]
    install_chatgpt_mcp_http(app, runtime.settings)
    app.add_exception_handler(BillingUnavailable, _billing_unavailable)
    app.add_middleware(_AuthorizationHeaderMiddleware, settings=runtime.settings)
    return app


async def _billing_unavailable(_request, _exc):
    """Stripe could not be asked. Not invalid_grant (hosts drop tokens on that):
    a 503 with Retry-After tells the AI chat app to try the same token again."""
    _LOG.warning("billing_unavailable")
    return JSONResponse(
        {
            "error": "temporarily_unavailable",
            "error_description": "The subscription check is unavailable. Retry shortly.",
        },
        status_code=503,
        headers={"Retry-After": "30", "Cache-Control": "no-store"},
    )


def check_allowed_folder_in_drive(settings: Settings) -> None:
    """Refuse to serve unless the allow-list is one folder that Drive can read."""
    from google_drive_mcp.infra.google_auth.refresh_token import (
        clear_request_credentials,
        mint_readonly_credentials,
    )
    from google_drive_mcp.infra.google_drive.client import GoogleDriveClient

    folder = settings.require_allowed_folder()
    try:
        check_allowed_folder(GoogleDriveClient(mint_readonly_credentials(settings)), folder)
    finally:
        clear_request_credentials()


def main() -> None:
    import uvicorn

    try:
        runtime = build_runtime()
        check_allowed_folder_in_drive(runtime.settings)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    app = streamable_app(runtime)
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
