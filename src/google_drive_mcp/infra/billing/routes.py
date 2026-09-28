"""Subscribe pages and Stripe webhook. No PAN/bank in HTML or logs."""

from __future__ import annotations

import html
import json
import logging
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    RESUME_COOKIE,
    mint_entitlement,
    safe_resume,
    set_entitlement_cookie,
    verify_entitlement,
)
from google_drive_mcp.infra.billing.gateway import BillingGateway
from google_drive_mcp.infra.billing.passkey import (
    CHALLENGE_COOKIE,
    authentication_options,
    merge_passkey,
    mint_challenge,
    passkey_script,
    read_challenge,
    registration_options,
    remember_controls,
    signature_matches,
    verify_authentication,
    verify_registration,
)
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
  <p>Mandatory subscription to Connect this MCP from any AI chat app.
     You pay on Stripe’s checkout. This page never asks for a card. The operator’s
     bank details are not shown here.</p>
  <p>{status}</p>
  {form}
  {setup}
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
  <p>Return to your AI chat app. While this subscription stays active,
     that app keeps calling onto-kb with no email and no further payment.</p>
  {controls}
  <p>Fallback entitlement (do not share):</p>
  <p><code>{code}</code></p>
  <p><a href="/setup">Setup</a></p>
</body>
</html>
"""


def _resume_or_none(request: Request) -> str | None:
    raw = request.cookies.get(RESUME_COOKIE)
    if raw:
        raw = unquote(raw)
    return safe_resume(raw)


def _resume_target(request: Request) -> str:
    return _resume_or_none(request) or "/setup"


def subscribe_get(
    request: Request, settings: Settings, billing: BillingGateway, *, configured: bool
) -> Response:
    scid = entitlement_from_request(request, settings)
    if (
        settings.mcp_subscription_required
        and configured
        and scid
        and billing.is_subscription_active(scid)
    ):
        nxt = _resume_target(request)
        if billing.get_passkey(scid):
            page = RedirectResponse(nxt, status_code=303)
        else:
            page = HTMLResponse(
                _SUBSCRIBE.format(
                    status=html.escape(
                        "This subscription is already active. Remember it in this browser "
                        "so a different browser can continue Connect."
                    ),
                    form=remember_controls(nxt),
                    setup=f'<p><a href="{html.escape(nxt, quote=True)}">Continue</a></p>',
                )
            )
        set_entitlement_cookie(page, settings, scid)
        page.delete_cookie(RESUME_COOKIE, path="/")
        return page
    if not settings.mcp_subscription_required:
        status = (
            "USD 20 per month for onto-kb. Checkout is not open yet because "
            "the Stripe price is not connected to this server. "
            "The connector setup page is available."
        )
        form = ""
        setup = '<p class="note"><a href="/setup">Setup</a></p>'
    elif not configured:
        status = "Payments are not configured (missing processor keys)."
        form = ""
        setup = ""
    else:
        status = (
            "USD 20 each month until you cancel in the Stripe customer portal. "
            "An AI chat app that already finished Connect keeps working "
            "while the subscription is active. No email, and no second charge. "
            "Switching browsers continues the same subscription automatically. "
            "You do not type a receipt email."
        )
        form = (
            '<form method="post" action="/subscribe/checkout">'
            '<button type="submit">Pay $20 / month</button></form>'
            '<p class="note" id="passkey-status">If you already pay, this browser continues '
            "that subscription when it has been remembered. You do not type a receipt email.</p>"
            '<button type="button" id="continue-sub" hidden onclick="ontoKbContinue()">'
            "Continue subscription</button>"
            '<div id="passkey-auto" hidden></div>'
            + passkey_script()
        )
        setup = ""
    return HTMLResponse(
        _SUBSCRIBE.format(status=html.escape(status), form=form, setup=setup)
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
                setup="",
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
                setup="",
            ),
            status_code=402,
        )
    token = mint_entitlement(settings, customer_id=customer)
    nxt = _resume_target(request)
    page = HTMLResponse(
        _COMPLETE.format(code=html.escape(token), controls=remember_controls(nxt))
    )
    set_entitlement_cookie(page, settings, customer)
    page.delete_cookie(RESUME_COOKIE, path="/")
    return page


async def subscribe_restore_post(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    form = await request.form()
    email = str(form.get("email") or "")
    customer = billing.active_customer_id_for_email(email)
    if not customer:
        return HTMLResponse(
            _SUBSCRIBE.format(
                status=html.escape(
                    "No active subscription was found. Pay to start one. "
                    "The email address is not shown again."
                ),
                form=(
                    '<form method="post" action="/subscribe/checkout">'
                    '<button type="submit">Pay $20 / month</button></form>'
                ),
                setup="",
            ),
            status_code=404,
        )
    page = RedirectResponse(_resume_target(request), status_code=303)
    set_entitlement_cookie(page, settings, customer)
    page.delete_cookie(RESUME_COOKIE, path="/")
    return page


async def stripe_webhook_post(request: Request, settings: Settings) -> Response:
    secret = settings.stripe_webhook_secret.get_secret_value().strip()
    payload = await request.body()
    header = request.headers.get("stripe-signature") or ""
    if not verify_stripe_signature(payload, header, secret):
        return JSONResponse({"ok": False}, status_code=400)
    _LOG.info("stripe_webhook")
    return JSONResponse({"ok": True})


def _challenge_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        CHALLENGE_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=300,
        secure=issuer_url(settings).startswith("https://"),
        path="/",
    )


async def passkey_options_post(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    scid = entitlement_from_request(request, settings)
    challenge, token = mint_challenge(settings)
    if scid and billing.is_subscription_active(scid):
        public_key = registration_options(settings, scid, challenge, billing.get_passkey(scid))
    else:
        public_key = authentication_options(settings, challenge)
    page = JSONResponse({"publicKey": public_key})
    _challenge_cookie(page, settings, token)
    return page


async def passkey_register_post(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    scid = entitlement_from_request(request, settings)
    if not scid or not billing.is_subscription_active(scid):
        return JSONResponse({"ok": False}, status_code=401)
    challenge = read_challenge(request.cookies.get(CHALLENGE_COOKIE), settings)
    if not challenge:
        return JSONResponse({"ok": False}, status_code=400)
    try:
        body = await request.json()
        record = verify_registration(settings, challenge, scid, body)
        billing.save_passkey(scid, merge_passkey(billing.get_passkey(scid), record))
    except (ValueError, json.JSONDecodeError, RuntimeError):
        return JSONResponse({"ok": False}, status_code=400)
    page = JSONResponse({"ok": True})
    page.delete_cookie(CHALLENGE_COOKIE, path="/")
    return page


async def passkey_finish_post(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    challenge = read_challenge(request.cookies.get(CHALLENGE_COOKIE), settings)
    if not challenge:
        return JSONResponse({"ok": False}, status_code=400)
    try:
        body = await request.json()
        customer_id, material = verify_authentication(settings, challenge, body)
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False}, status_code=400)
    if not billing.is_subscription_active(customer_id):
        return JSONResponse({"ok": False}, status_code=403)
    updated = None
    keys = billing.get_passkey(customer_id)
    for record in keys:
        updated = signature_matches(record, material)
        if updated:
            break
    if updated is None:
        return JSONResponse({"ok": False}, status_code=400)
    try:
        billing.save_passkey(customer_id, merge_passkey(keys, updated))
    except RuntimeError:
        pass
    page = JSONResponse({"redirect": _resume_target(request)})
    set_entitlement_cookie(page, settings, customer_id)
    page.delete_cookie(CHALLENGE_COOKIE, path="/")
    page.delete_cookie(RESUME_COOKIE, path="/")
    return page


def entitlement_from_request(request: Request, settings: Settings) -> str | None:
    raw = request.cookies.get(COOKIE_NAME)
    scid = verify_entitlement(raw, settings)
    if scid:
        return scid
    return verify_entitlement(request.query_params.get("entitlement"), settings)
