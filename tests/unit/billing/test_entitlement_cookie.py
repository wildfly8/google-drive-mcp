"""The entitlement cookie: every claim is checked, and the cookie is HttpOnly.

The cookie says "this browser holds a subscription". It is a signed token like the others,
so the signature alone is not enough: a token of another kind, for another audience, expired,
or naming something that is not a Stripe customer must not be read as an entitlement.
"""

from __future__ import annotations

import pytest
from starlette.responses import Response

from google_drive_mcp.infra.billing.entitlement import (
    COOKIE_NAME,
    mint_entitlement,
    set_entitlement_cookie,
    verify_entitlement,
)
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt, encode_jwt
from google_drive_mcp.infra.mcp_auth.tokens import mint_access_token, signing_key, verify_access_claims

GONE = object()


def _forged(settings: Settings, **changes) -> str:
    claims = decode_jwt(mint_entitlement(settings, customer_id="cus_live1"), signing_key(settings))
    assert claims is not None
    for name, value in changes.items():
        if value is GONE:
            claims.pop(name)
        else:
            claims[name] = value
    return encode_jwt(claims, signing_key(settings))


def test_an_unchanged_cookie_names_its_customer(settings: Settings):
    assert verify_entitlement(_forged(settings), settings) == "cus_live1"


@pytest.mark.parametrize(
    "change",
    [
        {"typ": "access"},
        {"typ": GONE},
        {"iss": "https://some-other-server.example/"},
        {"aud": "https://some-other-server.example/"},
        {"aud": GONE},
        {"exp": 1},
        {"exp": "tomorrow"},
        {"exp": GONE},
        {"scid": "acct_not_a_customer"},
        {"scid": 12345},
        {"scid": GONE},
    ],
    ids=lambda change: "-".join(f"{k}={'GONE' if v is GONE else v}" for k, v in change.items()),
)
def test_a_cookie_with_one_wrong_claim_is_not_an_entitlement(settings: Settings, change: dict):
    assert verify_entitlement(_forged(settings, **change), settings) is None


def test_an_access_token_is_not_an_entitlement_and_the_reverse(settings: Settings):
    assert verify_entitlement(mint_access_token(settings, client_id="host-1"), settings) is None
    assert verify_access_claims(mint_entitlement(settings, customer_id="cus_live1"), settings) is None


def test_the_cookie_cannot_be_read_by_scripts(settings: Settings):
    response = Response()
    set_entitlement_cookie(response, settings, "cus_live1")
    header = response.headers["set-cookie"]
    assert header.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
