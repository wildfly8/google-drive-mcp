"""Public Claude connector setup page. Remaining clicks are Claude UI, not this server."""

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
  <title>Add onto-kb in Claude</title>
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
  <h1>Add this connector in Claude</h1>
  <p>Read-only Google Drive tools. This server cannot write, delete, or share.
     Claude still has two prompts this origin cannot skip: <strong>Always allow</strong>
     and enabling the connector in a chat.</p>
  <p>Connector URL</p>
  <div class="url-row">
    <input id="mcp-url" readonly value="{mcp_url}">
    <button type="button" id="copy">Copy</button>
  </div>
  <ol>
    <li>Claude Web → Customize → Connectors → <strong>+</strong> → Add custom connector.</li>
    <li>Name: <strong>onto-kb</strong>. Paste the URL above.</li>
    <li>Authentication: <strong>Sign in when needed</strong> (override Detected “No sign-in” if shown).
        OAuth client: <strong>Use Claude’s published identity</strong>. Leave request headers empty.</li>
    <li>Connect. {auth_step}</li>
    <li>When Claude asks <strong>Read-only tools, always allow?</strong>, choose <strong>Always allow</strong>.</li>
    <li>In a chat, <strong>+</strong> → Connectors → enable onto-kb.</li>
  </ol>
  <p class="note">{auth_note}</p>
  <p class="stats">{stats_line} <a href="/stats">JSON</a>{gcp_links}</p>
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


def setup_get(
    _request: Request, settings: Settings, stats: dict | None = None
) -> HTMLResponse:
    mcp_url = resource_url(settings)
    stats = stats or {}
    connects = int(stats.get("oauth_connects") or 0)
    first = int(stats.get("drive_first_uses") or 0)
    stats_line = (
        f"Non-PII usage: {connects} successful Connects, {first} first Drive tool uses "
        "(not unique people)."
    )
    gcp = stats.get("gcp") if isinstance(stats.get("gcp"), dict) else {}
    gcp_links = ""
    dash = gcp.get("dashboards")
    metrics = gcp.get("metrics_explorer")
    logs = gcp.get("logs_oauth_connects")
    extras = []
    if dash:
        extras.append(f'<a href="{html.escape(str(dash), quote=True)}">Monitoring dashboards</a>')
    if metrics:
        extras.append(f'<a href="{html.escape(str(metrics), quote=True)}">Metrics Explorer</a>')
    if logs:
        extras.append(f'<a href="{html.escape(str(logs), quote=True)}">Connect logs</a>')
    if extras:
        gcp_links = " · " + " · ".join(extras)
    if settings.mcp_oauth_auto_approve:
        auth_step = "Your browser returns to Claude. There is no deployment password."
        auth_note = (
            "Knowing this URL is enough to finish OAuth. Drive calls still require the "
            "short-lived token Claude stores after Connect. Do not put MCP_AUTH_TOKEN "
            "in Claude request headers."
        )
    else:
        auth_step = (
            "On this origin’s consent page, enter the deployment password "
            "(Secret Manager <code>MCP_AUTH_TOKEN</code>)."
        )
        auth_note = (
            "Do not put MCP_AUTH_TOKEN in Claude request headers. It is only the consent password."
        )
    return HTMLResponse(
        _PAGE.format(
            mcp_url=html.escape(mcp_url, quote=True),
            auth_step=auth_step,
            auth_note=auth_note,
            stats_line=html.escape(stats_line),
            gcp_links=gcp_links,
        )
    )
