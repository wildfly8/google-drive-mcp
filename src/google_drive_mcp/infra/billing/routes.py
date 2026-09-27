"""Subscribe pages and Stripe webhook. No PAN/bank in HTML or logs."""

from __future__ import annotations

import html
import logging

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    mint_entitlement,
    verify_entitlement,
)
from google_drive_mcp.infra.billing.gateway import BillingGateway
from google_drive_mcp.infra.billing.stripe_api import verify_stripe_signature
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.tokens import issuer_url

_LOG = logging.getLogger("google_drive_mcp")

_SUBSCRIBE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Subscribe to onto-kb</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
    button {{ padding: 0.6rem 1rem; font-size: 1rem; }}
    .note {{ color: #444; }}
  </style>
</head>
<body>
  <h1>onto-kb — $20 USD / month</h1>
  <p>Mandatory subscription to Connect this MCP (Claude, ChatGPT, or other hosts).
     You pay on Stripe’s checkout. This page never asks for a card. The operator’s
     bank details are not shown here.</p>
  <p>{status}</p>
  {form}
  <p class="note"><a href="/setup">Setup</a></p>
</body>
</html>
"""

_COMPLETE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Subscription active</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 2rem auto; padding: 0 1rem; }}
  </style>
</head>
<body>
  <h1>Payment received</h1>
  <p>Return to Claude (or your MCP host) and click <strong>Connect</strong> again
     in this same browser.</p>
  <p>Fallback entitlement (do not share):</p>
  <p><code>{code}</code></p>
  <p><a href="/setup">Setup</a></p>
</body>
</html>
"""


def subscribe_get(settings: Settings, *, configured: bool) -> HTMLResponse:
    if not settings.mcp_subscription_required:
        status = "Paywall is off on this deployment."
        form = ""
    elif not configured:
        status = "Payments are not configured (missing processor keys)."
        form = ""
    else:
        status = "USD 20 each month until you cancel in the Stripe customer portal."
        form = '<form method="post" action="/subscribe/checkout"><button type="submit">Pay $20 / month</button></form>'
    return HTMLResponse(
        _SUBSCRIBE.format(status=html.escape(status), form=form)
    )


async def subscribe_checkout_post(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    origin = issuer_url(settings).rstrip("/")
    success = f"{origin}/subscribe/complete?session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{origin}/subscribe"
    try:
        url = billing.create_checkout_url(success_url=success, cancel_url=cancel)
    except Exception:
        return HTMLResponse(
            _SUBSCRIBE.format(
                status=html.escape("Checkout could not start. Try again later."),
                form="",
            ),
            status_code=503,
        )
    return RedirectResponse(url, status_code=303)


async def subscribe_complete_get(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    session_id = request.query_params.get("session_id") or ""
    customer = billing.customer_id_from_checkout_session(session_id)
    if not customer:
        return HTMLResponse(
            _SUBSCRIBE.format(
                status=html.escape("Payment not confirmed yet. Refresh after checkout completes."),
                form="",
            ),
            status_code=402,
        )
    token = mint_entitlement(settings, customer_id=customer)
    page = HTMLResponse(_COMPLETE.format(code=html.escape(token)))
    page.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
        secure=issuer_url(settings).startswith("https://"),
        path="/",
    )
    return page


async def stripe_webhook_post(request: Request, settings: Settings) -> Response:
    secret = settings.stripe_webhook_secret.get_secret_value().strip()
    payload = await request.body()
    header = request.headers.get("stripe-signature") or ""
    if not verify_stripe_signature(payload, header, secret):
        return JSONResponse({"ok": False}, status_code=400)
    _LOG.info("stripe_webhook")
    return JSONResponse({"ok": True})


def entitlement_from_request(request: Request, settings: Settings) -> str | None:
    raw = request.cookies.get(COOKIE_NAME)
    scid = verify_entitlement(raw, settings)
    if scid:
        return scid
    return verify_entitlement(request.query_params.get("entitlement"), settings)
