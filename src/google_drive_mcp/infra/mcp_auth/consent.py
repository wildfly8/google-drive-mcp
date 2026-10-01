"""Consent pages.

Paid deployments show an Allow page to the subscriber whose browser started
Connect. Unpaid deployments use the resource-owner password page, where
MCP_AUTH_TOKEN is the password, not an API bearer.
"""

from __future__ import annotations

import html
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from mcp.server.auth.provider import construct_redirect_uri

from google_drive_mcp.infra.billing.entitlement import current_scid
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.bearer import verify_bearer
from google_drive_mcp.infra.mcp_auth.provider import DriveMcpOAuthProvider
from google_drive_mcp.infra.mcp_auth.tokens import issuer_url, verify_ticket_claims

# Pages here must never load inside another site's frame (clickjacking).
_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}

# Hosts of AI chat apps whose Connect flow returns to them. Anything else is
# shown as unrecognized so a subscriber thinks twice before allowing it.
KNOWN_RETURN_HOSTS = frozenset(
    {"claude.ai", "claude.com", "chatgpt.com", "chat.openai.com", "localhost", "127.0.0.1"}
)

_STYLE = """
    body {{ font-family: system-ui, sans-serif; max-width: 32rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
    label {{ display: block; margin: 1rem 0 0.4rem; }}
    input[type=password] {{ width: 100%; padding: 0.5rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.5rem 1rem; }}
    .err {{ color: #b00020; }}
    .warn {{ color: #b00020; font-weight: 600; }}
    .ok {{ color: #1b5e20; }}
"""

_PASSWORD_PAGE = (
    """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Authorize onto-kb</title>
  <style>"""
    + _STYLE
    + """</style>
</head>
<body>
  <h1>Authorize onto-kb</h1>
  <p>This client wants a short-lived token for read-only retrieval on this deployment.
     Enter the deployment password stored as <code>MCP_AUTH_TOKEN</code>.</p>
  <p>After you allow access, your AI chat app may ask you to <strong>Always allow</strong>
     read-only tools. These tools can only list, find, read, and search;
     they cannot write, delete, or share.</p>
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
)

_ALLOW_PAGE = (
    """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Allow onto-kb access</title>
  <style>"""
    + _STYLE
    + """</style>
</head>
<body>
  <h1>Allow this app to use your onto-kb subscription?</h1>
  <p>An app that calls itself <strong>{client_name}</strong> wants read-only access to onto-kb
     on your subscription. After you allow, you return to:</p>
  <p><strong>{return_host}</strong> — {verdict}</p>
  <p>Only allow if you just clicked Connect in your own AI chat app. The tools can only list,
     find, read and search; they cannot write, delete or share.</p>
  {error}
  <form method="post" action="/consent">
    <input type="hidden" name="ticket" value="{ticket}">
    <button type="submit">Allow</button>
  </form>
</body>
</html>
"""
)

_EXPIRED = "<p>This consent link is missing or expired. Restart the OAuth flow.</p>"


def _return_host(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme in {"http", "https"}:
        return parsed.hostname or redirect_uri
    return f"{parsed.scheme}:" if parsed.scheme else redirect_uri


def _recognized(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == known or host.endswith("." + known) for known in KNOWN_RETURN_HOSTS)


def _password_page(ticket: str, error: str | None = None) -> HTMLResponse:
    err_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(
        _PASSWORD_PAGE.format(ticket=html.escape(ticket, quote=True), error=err_html),
        status_code=400 if error else 200,
        headers=_HEADERS,
    )


async def _allow_page(
    ticket: str, claims: dict, provider: DriveMcpOAuthProvider, error: str | None = None
) -> HTMLResponse:
    client = await provider.get_client(str(claims.get("client_id") or ""))
    name = (getattr(client, "client_name", None) or "an unnamed app")[:80]
    host = _return_host(str(claims.get("redirect_uri") or ""))
    verdict = (
        '<span class="ok">a known AI chat app address</span>'
        if _recognized(host)
        else '<span class="warn">not a known AI chat app address; allow only if you trust it</span>'
    )
    err_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(
        _ALLOW_PAGE.format(
            client_name=html.escape(name),
            return_host=html.escape(host),
            verdict=verdict,
            ticket=html.escape(ticket, quote=True),
            error=err_html,
        ),
        status_code=400 if error else 200,
        headers=_HEADERS,
    )


async def consent_get(
    request: Request, settings: Settings, provider: DriveMcpOAuthProvider
) -> Response:
    ticket = request.query_params.get("ticket") or ""
    claims = verify_ticket_claims(ticket, settings)
    if claims is None:
        return HTMLResponse(_EXPIRED, status_code=400, headers=_HEADERS)
    if claims.get("scid"):
        return await _allow_page(ticket, claims, provider)
    return _password_page(ticket)


async def consent_post(
    request: Request,
    provider: DriveMcpOAuthProvider,
    settings: Settings,
) -> Response:
    form = await request.form()
    ticket = form.get("ticket")
    if not isinstance(ticket, str):
        return HTMLResponse("<p>Invalid consent form.</p>", status_code=400, headers=_HEADERS)
    claims = verify_ticket_claims(ticket, settings)
    if claims is None:
        return HTMLResponse(_EXPIRED, status_code=400, headers=_HEADERS)
    scid = claims.get("scid")
    if scid:
        # The click must come from the browser that holds this subscription.
        if current_scid() != scid or not provider.billing.is_subscription_active(str(scid)):
            return HTMLResponse(_EXPIRED, status_code=400, headers=_HEADERS)
    else:
        password = form.get("password")
        if not isinstance(password, str):
            return HTMLResponse("<p>Invalid consent form.</p>", status_code=400, headers=_HEADERS)
        expected = settings.mcp_auth_token.get_secret_value()
        if not verify_bearer(password, expected):
            return _password_page(ticket, error="Incorrect password.")
    code, state = provider.issue_code_from_ticket(claims)
    return RedirectResponse(
        url=construct_redirect_uri(
            str(claims["redirect_uri"]),
            code=code,
            state=state,
            iss=issuer_url(settings),
        ),
        status_code=303,
        headers=_HEADERS,
    )
