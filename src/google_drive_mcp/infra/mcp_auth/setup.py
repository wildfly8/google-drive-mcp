"""Public connector setup page. Remaining clicks are in the AI chat app."""

from __future__ import annotations

import html

from starlette.requests import Request
from starlette.responses import HTMLResponse

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.tokens import resource_url

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Set up onto-kb</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
    code, input[readonly] {{ font-family: ui-monospace, monospace; }}
    ol {{ padding-left: 1.3rem; }}
    li {{ margin: 0.6rem 0; }}
    .url-row {{ display: flex; gap: 0.5rem; margin: 0.6rem 0 1rem; }}
    input[readonly] {{ flex: 1; padding: 0.5rem; }}
    button {{ padding: 0.5rem 0.8rem; }}
    .note {{ color: #444; }}
    .stats {{ color: #444; font-size: 0.95rem; }}
  </style>
</head>
<body>
  <h1>Set up onto-kb</h1>
  {pay_block}
  <p>Read-only Google Drive tools. This server cannot write, delete, or share.
     Connector setup is available only after payment.
     Any AI chat app that already finished Connect keeps calling onto-kb while the Stripe subscription stays active.
     The app uses the URL below and then asks you to allow the tools.</p>
  <p>Connector URL</p>
  <div class="url-row">
    <input id="mcp-url" readonly value="{mcp_url}">
    <button type="button" id="copy">Copy</button>
  </div>
  <h2>Any AI chat app</h2>
  <ol>
    <li>In your AI chat app, add a remote MCP connector. Menu names differ by app.</li>
    <li>Name: <strong>onto-kb</strong>. Paste the URL above. Transport, if asked: <strong>Streamable HTTP</strong>.</li>
    <li>Authentication: <strong>Sign in</strong> or <strong>OAuth</strong>. Leave extra request headers empty. Do not paste a static token.</li>
    <li>Connect. {auth_step}</li>
    <li>If the app asks you to <strong>Always allow</strong> read-only tools, allow them, then enable onto-kb in a chat.</li>
  </ol>
  <p class="note">{auth_note}</p>
  {stats_block}
  <script>
    document.getElementById("copy").addEventListener("click", function () {{
      const el = document.getElementById("mcp-url");
      navigator.clipboard.writeText(el.value).catch(function () {{
        el.select();
        document.execCommand("copy");
      }});
    }});
  </script>
</body>
</html>
"""

_LOCKED = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Subscribe to onto-kb</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
    a {{ color: #0b57d0; }}
  </style>
</head>
<body>
  <h1>Subscribe to onto-kb</h1>
  <p><strong>$20 USD / month required.</strong> Connector setup is shown in this browser after Stripe Checkout.</p>
  <p><a href="/subscribe">Pay on Stripe Checkout</a></p>
  <p>Cards are entered on Stripe, not here. This page does not show the operator’s bank details.</p>
</body>
</html>
"""


def setup_get(
    _request: Request,
    settings: Settings,
    stats: dict | None = None,
    *,
    entitled: bool = True,
) -> HTMLResponse:
    if settings.mcp_subscription_required and not entitled:
        return HTMLResponse(_LOCKED.format())
    mcp_url = resource_url(settings)
    stats = stats or {}
    stats_block = ""
    if not settings.mcp_subscription_required:
        connects = int(stats.get("oauth_connects") or 0)
        first = int(stats.get("drive_first_uses") or 0)
        stats_line = (
            f"Non-PII usage: {connects} successful Connects, {first} first Drive tool uses "
            "(not unique people)."
        )
        gcp = stats.get("gcp") if isinstance(stats.get("gcp"), dict) else {}
        extras = []
        dash = gcp.get("dashboards")
        metrics = gcp.get("metrics_explorer")
        logs = gcp.get("logs_oauth_connects")
        if dash:
            extras.append(f'<a href="{html.escape(str(dash), quote=True)}">Monitoring dashboards</a>')
        if metrics:
            extras.append(f'<a href="{html.escape(str(metrics), quote=True)}">Metrics Explorer</a>')
        if logs:
            extras.append(f'<a href="{html.escape(str(logs), quote=True)}">Connect logs</a>')
        gcp_links = (" · " + " · ".join(extras)) if extras else ""
        stats_block = (
            f'<p class="stats">{html.escape(stats_line)} '
            f'<a href="/stats">JSON</a>{gcp_links}</p>'
        )
    pay_block = ""
    if settings.mcp_subscription_required:
        pay_block = (
            "<p><strong>Payment confirmed.</strong> "
            "Set up your AI chat app only after payment. "
            "While Stripe shows this subscription as active, that app keeps "
            "calling onto-kb with no further steps from you.</p>"
        )
    if settings.mcp_oauth_auto_approve:
        auth_step = "Your browser returns to the AI chat app. There is no deployment password."
        if settings.mcp_subscription_required:
            auth_note = (
                "There is no deployment password. After Connect, the AI chat app stores a "
                "short-lived token and sends it on each tool call."
            )
        else:
            auth_note = (
                "Knowing this URL is enough to finish OAuth. Drive calls still require the "
                "short-lived token the AI chat app stores after Connect. Do not put MCP_AUTH_TOKEN "
                "in request headers."
            )
    else:
        auth_step = (
            "On this origin’s consent page, enter the deployment password "
            "(Secret Manager <code>MCP_AUTH_TOKEN</code>)."
        )
        auth_note = (
            "Do not put MCP_AUTH_TOKEN in request headers. It is only the consent password."
        )
    return HTMLResponse(
        _PAGE.format(
            mcp_url=html.escape(mcp_url, quote=True),
            pay_block=pay_block,
            auth_step=auth_step,
            auth_note=auth_note,
            stats_block=stats_block,
        )
    )
