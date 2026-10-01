"""Signed entitlement cookie. Holds Stripe customer id only; never accepted from a URL."""

from __future__ import annotations

from contextvars import ContextVar

from starlette.responses import Response

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt, encode_jwt
from google_drive_mcp.infra.mcp_auth.tokens import _now, issuer_url, signing_key

COOKIE_NAME = "onto_kb_scid"
RESUME_COOKIE = "onto_kb_resume"
TYP_ENTITLEMENT = "entitlement"
ENTITLEMENT_TTL = 400 * 24 * 3600

_current_scid: ContextVar[str | None] = ContextVar("onto_kb_scid", default=None)


def set_current_scid(value: str | None) -> None:
    _current_scid.set(value)


def current_scid() -> str | None:
    return _current_scid.get()


def entitlement_audience(settings: Settings) -> str:
    return f"{issuer_url(settings).rstrip('/')}/subscribe"


def mint_entitlement(settings: Settings, *, customer_id: str) -> str:
    iat = _now()
    claims = {
        "typ": TYP_ENTITLEMENT,
        "iss": issuer_url(settings),
        "aud": entitlement_audience(settings),
        "scid": customer_id,
        "iat": iat,
        "exp": iat + ENTITLEMENT_TTL,
    }
    return encode_jwt(claims, signing_key(settings))


def verify_entitlement(token: str | None, settings: Settings) -> str | None:
    if not token:
        return None
    payload = decode_jwt(token, signing_key(settings))
    if payload is None:
        return None
    if payload.get("typ") != TYP_ENTITLEMENT:
        return None
    if payload.get("iss") != issuer_url(settings):
        return None
    if payload.get("aud") != entitlement_audience(settings):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < _now():
        return None
    scid = payload.get("scid")
    if not isinstance(scid, str) or not scid.startswith("cus_"):
        return None
    return scid


def set_entitlement_cookie(response: Response, settings: Settings, customer_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        mint_entitlement(settings, customer_id=customer_id),
        httponly=True,
        samesite="lax",
        max_age=ENTITLEMENT_TTL,
        secure=issuer_url(settings).startswith("https://"),
        path="/",
    )


def safe_resume(value: str | None) -> str | None:
    """In-progress OAuth path on this origin. Rejects off-site redirects."""
    if not value:
        return None
    if value != "/authorize" and not value.startswith("/authorize?"):
        return None
    if "\\" in value or "://" in value or value.startswith("//"):
        return None
    return value
