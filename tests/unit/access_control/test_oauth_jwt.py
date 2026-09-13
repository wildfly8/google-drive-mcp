"""HS256 JWT helper: reject alg=none, expired, and tampered tokens."""

from __future__ import annotations

import base64
import json

from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt
from google_drive_mcp.infra.mcp_auth.tokens import (
    mint_access_token,
    signing_key,
    verify_access_claims,
    verify_authorization_header,
)


def test_round_trip_and_reject_tamper_and_static_secret(settings):
    token = mint_access_token(settings)
    assert verify_access_claims(token, settings)
    assert verify_authorization_header(f"Bearer {token}", settings)
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.{('A' * len(parts[2]))}"
    assert verify_access_claims(tampered, settings) is None
    assert verify_authorization_header("Bearer test-token", settings) is False
    assert verify_authorization_header(None, settings) is False


def test_rejects_expired_and_alg_none(settings):
    expired = mint_access_token(settings, ttl=-10)
    assert verify_access_claims(expired, settings) is None
    payload = mint_access_token(settings).split(".")[1]
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    forged = f"{header}.{payload}."
    assert decode_jwt(forged, signing_key(settings)) is None
