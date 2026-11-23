"""Every claim of an access token is checked, one at a time (Article VII).

A token with a good signature but one wrong claim must not be accepted. The claims overlap
(a ticket, a registered client id and an entitlement cookie all differ in several), so a check
that is removed can go unnoticed while the others hide it. Each case here changes exactly one
claim of an otherwise valid access token. Refresh and code tokens share the audience, issuer
and scope of an access token, so only `typ` tells them apart.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.bearer import verify_bearer
from google_drive_mcp.infra.mcp_auth.jwt import b64url_encode, decode_jwt, encode_jwt
from google_drive_mcp.infra.mcp_auth.tokens import (
    issuer_url,
    mint_access_token,
    mint_authorization_code,
    mint_refresh_token,
    resource_url,
    signing_key,
    verify_access_claims,
    verify_authorization_header,
    verify_code_claims,
    verify_refresh_claims,
)
from google_drive_mcp.mcp.tools import handle_tool

GONE = object()


def _forged(settings: Settings, **changes) -> str:
    """A validly signed access token with the given claims changed (GONE removes one)."""
    claims = decode_jwt(mint_access_token(settings), signing_key(settings))
    assert claims is not None
    for name, value in changes.items():
        if value is GONE:
            claims.pop(name)
        else:
            claims[name] = value
    return encode_jwt(claims, signing_key(settings))


def test_the_unchanged_token_is_accepted(settings: Settings):
    token = _forged(settings)
    assert verify_access_claims(token, settings) is not None
    assert verify_authorization_header(f"Bearer {token}", settings) is True


@pytest.mark.parametrize(
    "change",
    [
        {"typ": "refresh"},
        {"typ": "code"},
        {"typ": "ticket"},
        {"typ": GONE},
        {"iss": "https://some-other-server.example/"},
        {"iss": GONE},
        {"aud": "https://some-other-server.example/mcp"},
        {"aud": GONE},
        {"exp": 1},
        {"exp": "tomorrow"},
        {"exp": GONE},
        {"scope": "drive"},
        {"scope": "drive.read drive.write"},
        {"scope": GONE},
        {"client_id": ""},
        {"client_id": GONE},
        {"jti": ""},
        {"jti": GONE},
    ],
    ids=lambda change: "-".join(f"{k}={'GONE' if v is GONE else v}" for k, v in change.items()),
)
def test_a_token_with_one_wrong_claim_is_refused(settings: Settings, change: dict):
    token = _forged(settings, **change)
    assert verify_access_claims(token, settings) is None
    assert verify_authorization_header(f"Bearer {token}", settings) is False


def test_a_refresh_or_code_token_is_not_an_access_token(settings: Settings):
    refresh = mint_refresh_token(settings, client_id="host-1")
    code = mint_authorization_code(
        settings,
        client_id="host-1",
        redirect_uri="http://127.0.0.1/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="abc",
        resource=resource_url(settings),
    )
    for token in (refresh, code):
        assert verify_access_claims(token, settings) is None
        assert verify_authorization_header(f"Bearer {token}", settings) is False


def test_an_access_token_is_not_a_refresh_or_code_token(settings: Settings):
    access = mint_access_token(settings, client_id="host-1")
    assert verify_refresh_claims(access, settings) is None
    assert verify_code_claims(access, settings) is None


def _signed_with_header(header: dict, claims: dict, key: bytes) -> str:
    """A token whose signature is valid for the header it carries, whatever the header says."""
    signing_input = (
        b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64url_encode(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = hmac.new(key, signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url_encode(signature)}"


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "typ": "JWT"},
        {"alg": "HS512", "typ": "JWT"},
        {"alg": "RS256", "typ": "JWT"},
        {"alg": "HS256", "typ": "JWS"},
        {"alg": "HS256"},
        {"typ": "JWT"},
    ],
    ids=["none", "HS512", "RS256", "typ-JWS", "no-typ", "no-alg"],
)
def test_a_header_that_names_another_algorithm_is_refused_even_with_a_valid_signature(
    settings: Settings, header: dict
):
    """The signature check does not make the header check redundant: the header says how the
    token claims to be signed, and only HS256 is ever used."""
    key = signing_key(settings)
    claims = decode_jwt(mint_access_token(settings), key)
    assert verify_access_claims(_signed_with_header({"alg": "HS256", "typ": "JWT"}, claims, key), settings)
    assert verify_access_claims(_signed_with_header(header, claims, key), settings) is None


def test_the_issuer_is_this_server(settings: Settings):
    claims = decode_jwt(mint_access_token(settings), signing_key(settings))
    assert claims["iss"] == issuer_url(settings)
    assert claims["aud"] == resource_url(settings)


def test_authentication_comes_before_argument_validation(runtime):
    """An unauthenticated caller learns nothing from how its arguments are judged."""
    for authorization in (None, "Bearer not-a-token", ""):
        for arguments in ({"bogus": 1}, {"folder_id": "bad id!"}, {"max_results": -5}):
            result = handle_tool(runtime, "drive_ls", arguments, authorization)
            assert result["category"] == "AUTHENTICATION_ERROR", (authorization, arguments)


def test_an_empty_consent_password_never_matches():
    assert verify_bearer("", "") is False
    assert verify_bearer(None, "secret") is False
    assert verify_bearer("secret", "") is False
    assert verify_bearer("secret", "other") is False
    assert verify_bearer("secret", "secret") is True
