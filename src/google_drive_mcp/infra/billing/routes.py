"""Subscribe pages and Stripe webhook. No PAN/bank in HTML or logs."""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from urllib.parse import unquote, urlparse

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from google_drive_mcp.infra.billing.email_link import EmailLinkPort
from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    RESUME_COOKIE,
    safe_resume,
    set_entitlement_cookie,
    verify_entitlement,
)
from google_drive_mcp.infra.billing.gateway import BillingGateway
from google_drive_mcp.infra.billing.stripe_api import verify_stripe_signature
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt, encode_jwt
from google_drive_mcp.infra.mcp_auth.tokens import _now, issuer_url, signing_key

_LOG = logging.getLogger("google_drive_mcp")
_SESSION_ID = re.compile(r"cs_(live|test)_[A-Za-z0-9]{10,200}")

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
  <h1>{heading}</h1>
  <p>{message}</p>
  <p><a id="return-app" href="{next_href}">Return to your AI chat app</a></p>
  {script}
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


# Holds the reference of the Checkout this browser started (client_reference_id).
CHECKOUT_COOKIE = "onto_kb_checkout"
_CHECKOUT_COOKIE_TTL = 24 * 3600  # Stripe Checkout Sessions expire after 24 hours


def _cross_site(request: Request, settings: Settings) -> bool:
    """True when a form POST did not come from this origin's own pages.

    Browsers send Sec-Fetch-Site; older ones send Origin. A request with
    neither (scripts, tests) is not a browser forging a form, so it passes.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in {"same-origin", "none"}
    origin = request.headers.get("origin")
    if not origin:
        return False
    if origin == "null":
        return True
    mine = urlparse(issuer_url(settings))
    theirs = urlparse(origin)
    return (theirs.scheme, theirs.netloc) != (mine.scheme, mine.netloc)


MANAGE_FORM = (
    '<form method="post" action="/subscribe/manage">'
    '<button type="submit">Manage or cancel subscription</button></form>'
)
SIGNOUT_FORM = (
    '<form method="post" action="/subscribe/signout">'
    '<button type="submit">Sign out of this browser</button></form>'
)


_PAY_FORM = (
    '<form method="post" action="/subscribe/checkout">'
    '<button type="submit">Pay $20 / month</button></form>'
)

_RESTORE_FORM = (
    "<h2>Already subscribed?</h2>"
    '<p class="note">To use your subscription in this browser, get a one-time sign-in '
    "link at the email on your Stripe receipt. Open the link in this browser.</p>"
    '<form method="post" action="/subscribe/email">'
    '<input type="email" name="email" autocomplete="email" required maxlength="254" '
    'aria-label="Receipt email"> '
    '<button type="submit">Email me a sign-in link</button></form>'
)


def subscribe_get(
    request: Request,
    settings: Settings,
    billing: BillingGateway,
    email_link: EmailLinkPort,
    *,
    configured: bool,
) -> Response:
    scid = entitlement_from_request(request, settings)
    active = bool(
        settings.mcp_subscription_required
        and configured
        and scid
        and billing.is_subscription_active(scid)
    )
    if active and scid:
        page = RedirectResponse(_resume_target(request), status_code=303)
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
            "USD 20 each month until you cancel. Cancel any time with Manage or cancel "
            "subscription on the setup page, or from the link in your Stripe receipt email. "
            "An AI chat app that already finished Connect keeps working "
            "while the subscription is active."
        )
        form = _PAY_FORM + (_RESTORE_FORM if email_link.configured() else "")
        setup = ""
        if scid:
            # A subscription this browser held is no longer active (cancelled,
            # or a renewal failed). Updating the card there beats paying twice.
            form = (
                '<p class="note">This browser holds an onto-kb subscription that is not '
                "active now. If a renewal failed, update your card in the Stripe portal "
                "instead of paying again.</p>" + MANAGE_FORM + SIGNOUT_FORM + form
            )
    return HTMLResponse(
        _SUBSCRIBE.format(status=html.escape(status), form=form, setup=setup)
    )


async def subscribe_checkout_post(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    if _cross_site(request, settings):
        return _page("Start checkout from this site's subscribe page.", _PAY_FORM, code=403)
    if not _LIMITS.allow(f"checkout:{_client_ip(request)}", 10, 3600):
        return _page("Too many requests. Try again later.", code=429)
    origin = issuer_url(settings).rstrip("/")
    success = f"{origin}/subscribe/complete?session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{origin}/subscribe"
    reference = secrets.token_urlsafe(24)
    # A lapsed subscriber pays again as the same Stripe customer, not a second one.
    customer = entitlement_from_request(request, settings)
    try:
        url = await run_in_threadpool(
            lambda: billing.create_checkout_url(
                success_url=success, cancel_url=cancel, reference=reference, customer=customer
            )
        )
    except Exception as exc:  # noqa: BLE001 - the subscriber sees a retry page
        _LOG.warning("checkout_start_failed error=%s", type(exc).__name__)
        return HTMLResponse(
            _SUBSCRIBE.format(
                status=html.escape("Checkout could not start. Try again later."),
                form="",
                setup="",
            ),
            status_code=503,
        )
    page = RedirectResponse(url, status_code=303)
    page.set_cookie(
        CHECKOUT_COOKIE,
        reference,
        max_age=_CHECKOUT_COOKIE_TTL,
        httponly=True,
        samesite="lax",
        secure=issuer_url(settings).startswith("https://"),
        path="/subscribe",
    )
    return page


async def subscribe_complete_get(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    session_id = request.query_params.get("session_id") or ""
    if not _SESSION_ID.fullmatch(session_id) or not _LIMITS.allow(
        f"complete:{_client_ip(request)}", 30, 3600
    ):
        return HTMLResponse(
            _SUBSCRIBE.format(
                status=html.escape("Payment not confirmed. Start again from the Pay button."),
                form=_PAY_FORM,
                setup="",
            ),
            status_code=400,
        )
    reference = request.cookies.get(CHECKOUT_COOKIE) or ""
    if not reference and entitlement_from_request(request, settings):
        # Reloading this page after it already worked: the browser has its cookie.
        return RedirectResponse(_resume_target(request), status_code=303)
    if not reference:
        return HTMLResponse(
            _SUBSCRIBE.format(
                status=html.escape(
                    "Open this page in the browser where you started checkout. "
                    "Already paid? Use the email sign-in link on the subscribe page."
                ),
                form=_PAY_FORM,
                setup="",
            ),
            status_code=400,
        )
    found = await run_in_threadpool(
        lambda: billing.customer_id_from_checkout_session(session_id, reference=reference)
    )
    if not found:
        return HTMLResponse(
            _SUBSCRIBE.format(
                status=html.escape("Payment not confirmed yet. Refresh after checkout completes."),
                form="",
                setup="",
            ),
            status_code=402,
        )
    customer = found
    heading = "Payment received"
    message = (
        "Return to your AI chat app. While this subscription stays active, "
        "that app keeps calling onto-kb with no further payment."
    )
    page = HTMLResponse(
        _COMPLETE.format(
            heading=html.escape(heading),
            message=html.escape(message),
            next_href=html.escape(_resume_target(request), quote=True),
            script="",
        )
    )
    set_entitlement_cookie(page, settings, customer)
    page.delete_cookie(RESUME_COOKIE, path="/")
    page.delete_cookie(CHECKOUT_COOKIE, path="/subscribe")
    return page


EMAIL_COOKIE = "onto_kb_email"
_TYP_EMAIL = "email_restore"
_EMAIL_COOKIE_TTL = 3600
_SENT = (
    "If that email has an active onto-kb subscription, a one-time sign-in link is on "
    "its way from Google. Open it in this browser to continue. The link works once. "
    "Nothing arrived? Check spam, or ask again in 15 minutes."
)
_PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


class _RateLimit:
    """Sliding-window counters per key, in this instance's memory (best effort).

    Keys are kept in least-recently-used order: each call drops keys idle past
    the longest window and evicts the oldest beyond max_keys, so memory and
    time stay bounded however many addresses an attacker uses.
    """

    def __init__(self, max_keys: int = 20000, max_window: float = 3600.0) -> None:
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_keys = max_keys
        self._max_window = max_window

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._hits:
                oldest_key, oldest = next(iter(self._hits.items()))
                if oldest and now - oldest[-1] <= self._max_window:
                    break
                self._hits.popitem(last=False)
            hits = self._hits.pop(key, None) or deque()
            while hits and now - hits[0] > window:
                hits.popleft()
            allowed = len(hits) < limit
            if allowed:
                hits.append(now)
            self._hits[key] = hits
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
            return allowed

    def __len__(self) -> int:
        return len(self._hits)


_LIMITS = _RateLimit()


def _client_ip(request: Request) -> str:
    # Cloud Run's front end appends the caller's address; earlier entries can be forged.
    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    parts = [part.strip() for part in forwarded.split(",") if part.strip()]
    if parts:
        return parts[-1]
    return request.client.host if request.client else "unknown"


def _clean_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip()
    if (
        not email
        or len(email) > 254
        or not email.isascii()
        or email.count("@") != 1
        or any(c.isspace() for c in email)
    ):
        return None
    local, domain = email.split("@")
    if not local or "." not in domain:
        return None
    return email


def _email_key(email: str) -> str:
    return hashlib.sha256(email.lower().encode("utf-8")).hexdigest()


def _email_audience(settings: Settings) -> str:
    return f"{issuer_url(settings).rstrip('/')}/subscribe/email"


def _set_email_cookie(response: Response, settings: Settings, email: str) -> None:
    iat = _now()
    token = encode_jwt(
        {
            "typ": _TYP_EMAIL,
            "iss": issuer_url(settings),
            "aud": _email_audience(settings),
            "email": email,
            "iat": iat,
            "exp": iat + _EMAIL_COOKIE_TTL,
        },
        signing_key(settings),
    )
    response.set_cookie(
        EMAIL_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=_EMAIL_COOKIE_TTL,
        secure=issuer_url(settings).startswith("https://"),
        path="/subscribe/email",
    )


def _email_from_cookie(request: Request, settings: Settings) -> str | None:
    payload = decode_jwt(request.cookies.get(EMAIL_COOKIE) or "", signing_key(settings))
    if not payload or payload.get("typ") != _TYP_EMAIL:
        return None
    if payload.get("iss") != issuer_url(settings):
        return None
    if payload.get("aud") != _email_audience(settings):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < _now():
        return None
    return _clean_email(payload.get("email"))


def _page(status: str, form: str = "", *, code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        _SUBSCRIBE.format(status=html.escape(status), form=form, setup=""),
        status_code=code,
        headers=_PRIVATE_HEADERS,
    )


def _send_if_subscriber(
    billing: BillingGateway, email_link: EmailLinkPort, email: str, continue_url: str
) -> None:
    try:
        if billing.active_customer_id_for_email(email):
            email_link.send_link(email, continue_url)
    except Exception:  # noqa: BLE001 - never surface processor errors to the caller
        _LOG.warning("email_restore_send_failed")


# Every reply to an address takes at least this long, so timing does not reveal
# subscribers. The send runs before the reply: Cloud Run throttles CPU after it.
_EMAIL_REPLY_FLOOR = 3.0


async def subscribe_email_post(
    request: Request,
    settings: Settings,
    billing: BillingGateway,
    email_link: EmailLinkPort,
) -> Response:
    started = time.monotonic()
    if not settings.mcp_subscription_required or not email_link.configured():
        return _page("Email sign-in is not available on this server.", _PAY_FORM, code=404)
    if _cross_site(request, settings):
        return _page("Ask for a sign-in link from this site's subscribe page.", code=403)
    form = await request.form()
    email = _clean_email(form.get("email"))
    if email is None:
        return _page("Enter the email address from your Stripe receipt.", _RESTORE_FORM, code=400)
    page = _page(_SENT)
    _set_email_cookie(page, settings, email)
    allowed = _LIMITS.allow(f"ip:{_client_ip(request)}", 10, 3600) and _LIMITS.allow(
        f"email:{_email_key(email)}", 3, 900
    )
    if allowed:
        continue_url = f"{issuer_url(settings).rstrip('/')}/subscribe/email/verify"
        await run_in_threadpool(_send_if_subscriber, billing, email_link, email, continue_url)
    await asyncio.sleep(max(0.0, _EMAIL_REPLY_FLOOR - (time.monotonic() - started)))
    return page


def _verify_form(oob_code: str, ask_email: bool) -> str:
    email_field = (
        '<p><input type="email" name="email" autocomplete="email" required maxlength="254" '
        'aria-label="Receipt email"> (the address this link was sent to)</p>'
        if ask_email
        else ""
    )
    return (
        '<form method="post" action="/subscribe/email/verify">'
        f'<input type="hidden" name="oobCode" value="{html.escape(oob_code, quote=True)}">'
        f"{email_field}"
        '<button type="submit">Continue in this browser</button></form>'
    )


def subscribe_email_verify_get(request: Request, settings: Settings) -> Response:
    oob_code = request.query_params.get("oobCode") or ""
    if not oob_code or len(oob_code) > 512:
        return _page("This sign-in link is incomplete. Ask for a new one.", _RESTORE_FORM, code=400)
    # A button, not an automatic sign-in: mail scanners that open links must not
    # use up the one-time code.
    ask_email = _email_from_cookie(request, settings) is None
    return _page(
        "Continue to use your onto-kb subscription in this browser.",
        _verify_form(oob_code, ask_email),
    )


async def subscribe_email_verify_post(
    request: Request,
    settings: Settings,
    billing: BillingGateway,
    email_link: EmailLinkPort,
) -> Response:
    if not settings.mcp_subscription_required or not email_link.configured():
        return _page("Email sign-in is not available on this server.", _PAY_FORM, code=404)
    if _cross_site(request, settings):
        return _page("Finish signing in from this site's own page.", _RESTORE_FORM, code=403)
    if not _LIMITS.allow(f"verify:{_client_ip(request)}", 20, 3600):
        return _page("Too many attempts. Try again later.", code=429)
    form = await request.form()
    oob_code = form.get("oobCode")
    email = _clean_email(form.get("email")) or _email_from_cookie(request, settings)
    if not isinstance(oob_code, str) or not oob_code or len(oob_code) > 512 or email is None:
        return _page("This sign-in link is incomplete. Ask for a new one.", _RESTORE_FORM, code=400)
    verified = await run_in_threadpool(email_link.verified_email, email, oob_code)
    if verified is None:
        return _page(
            "This sign-in link is invalid, expired, already used, or for another email. "
            "Ask for a new one.",
            _RESTORE_FORM,
            code=400,
        )
    # Google returns the address lower-cased; look up the one the subscriber typed,
    # which the adapter also tries lower-cased and case-insensitively.
    customer = await run_in_threadpool(billing.active_customer_id_for_email, email)
    if not customer:
        return _page(
            "That email has no active onto-kb subscription. Pay to start one.",
            _PAY_FORM,
            code=404,
        )
    page = RedirectResponse(_resume_target(request), status_code=303, headers=_PRIVATE_HEADERS)
    set_entitlement_cookie(page, settings, customer)
    page.delete_cookie(RESUME_COOKIE, path="/")
    page.delete_cookie(EMAIL_COOKIE, path="/subscribe/email")
    return page


async def subscribe_manage_post(
    request: Request, settings: Settings, billing: BillingGateway
) -> Response:
    """Stripe customer portal (manage or cancel) for the subscriber this browser holds."""
    if not settings.mcp_subscription_required:
        return _page("Payments are not enabled on this server.", code=404)
    if _cross_site(request, settings):
        return _page("Open billing from this site's setup page.", code=403)
    if not _LIMITS.allow(f"manage:{_client_ip(request)}", 20, 3600):
        return _page("Too many requests. Try again later.", code=429)
    # Same-site POST only: the SameSite=Lax cookie is not sent from other sites.
    scid = entitlement_from_request(request, settings)
    if not scid:
        return _page(
            "This browser has no onto-kb subscription. To manage or cancel, use the link "
            "in your Stripe receipt email, or continue your subscription in this browser "
            "from the subscribe page first.",
            '<p><a href="/subscribe">Subscribe page</a></p>',
            code=403,
        )
    origin = issuer_url(settings).rstrip("/")
    url = await run_in_threadpool(
        lambda: billing.create_portal_url(scid, return_url=f"{origin}/setup")
    )
    if not url:
        return _page(
            "The Stripe billing page is not available right now. Use the link in your "
            "Stripe receipt email to manage or cancel, or try again later.",
            code=503,
        )
    return RedirectResponse(url, status_code=303, headers=_PRIVATE_HEADERS)


async def subscribe_signout_post(request: Request, settings: Settings) -> Response:
    """Forget the subscription in this browser (shared or borrowed computers)."""
    if _cross_site(request, settings):
        return _page("Sign out from this site's own page.", code=403)
    page = RedirectResponse("/subscribe", status_code=303, headers=_PRIVATE_HEADERS)
    # Deleting sets onto_kb_scid too, so the middleware does not renew the old one.
    page.delete_cookie(COOKIE_NAME, path="/")
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


def entitlement_from_request(request: Request, settings: Settings) -> str | None:
    """Subscriber from the HttpOnly cookie only. A URL value is never accepted."""
    return verify_entitlement(request.cookies.get(COOKIE_NAME), settings)
