"""Resource-owner consent page. MCP_AUTH_TOKEN is the password, not an API bearer."""

from __future__ import annotations

import html

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from mcp.server.auth.provider import construct_redirect_uri

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.bearer import verify_bearer
from google_drive_mcp.infra.mcp_auth.provider import DriveMcpOAuthProvider
from google_drive_mcp.infra.mcp_auth.tokens import verify_ticket_claims

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Authorize Google Drive MCP</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 32rem; margin: 2rem auto; padding: 0 1rem; }}
    label {{ display: block; margin: 1rem 0 0.4rem; }}
    input[type=password] {{ width: 100%; padding: 0.5rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.5rem 1rem; }}
    .err {{ color: #b00020; }}
  </style>
</head>
<body>
  <h1>Authorize Google Drive MCP</h1>
  <p>This client wants a short-lived token for read-only Drive retrieval on this deployment.
     Enter the deployment password stored as <code>MCP_AUTH_TOKEN</code>.</p>
  {error}
  <form method="post" action="/consent">
    <input type="hidden" name="ticket" value="{ticket}">
    <label for="password">Deployment password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Allow access</button>
  </form>
</body>
</html>
"""


def _page(ticket: str, error: str | None = None) -> HTMLResponse:
    err_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(
        _PAGE.format(ticket=html.escape(ticket, quote=True), error=err_html),
        status_code=400 if error else 200,
    )


def consent_get(request: Request, settings: Settings) -> Response:
    ticket = request.query_params.get("ticket") or ""
    if verify_ticket_claims(ticket, settings) is None:
        return HTMLResponse("<p>This consent link is missing or expired. Restart the OAuth flow.</p>", status_code=400)
    return _page(ticket)


async def consent_post(
    request: Request,
    provider: DriveMcpOAuthProvider,
    settings: Settings,
) -> Response:
    form = await request.form()
    ticket = form.get("ticket")
    password = form.get("password")
    if not isinstance(ticket, str) or not isinstance(password, str):
        return HTMLResponse("<p>Invalid consent form.</p>", status_code=400)
    claims = verify_ticket_claims(ticket, settings)
    if claims is None:
        return HTMLResponse("<p>This consent link is missing or expired. Restart the OAuth flow.</p>", status_code=400)
    expected = settings.mcp_auth_token.get_secret_value()
    if not verify_bearer(password, expected):
        return _page(ticket, error="Incorrect password.")
    code, state = provider.issue_code_from_ticket(claims)
    return RedirectResponse(
        url=construct_redirect_uri(str(claims["redirect_uri"]), code=code, state=state),
        status_code=302,
    )
