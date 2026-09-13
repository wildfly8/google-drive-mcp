"""HS256 JWTs with the stdlib only. Never logs token bytes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

_MAX_TOKEN_BYTES = 8192


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    pad = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + pad)


def encode_jwt(claims: dict[str, Any], key: bytes) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signing_input = f"{b64url_encode(header_b)}.{b64url_encode(payload_b)}"
    sig = hmac.new(key, signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url_encode(sig)}"


def decode_jwt(token: str, key: bytes) -> dict[str, Any] | None:
    if not token or len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(b64url_decode(parts[0]))
        payload = json.loads(b64url_decode(parts[1]))
        sig = b64url_decode(parts[2])
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        return None
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        return None
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(key, signing_input, hashlib.sha256).digest()
    if len(sig) != len(expected) or not hmac.compare_digest(sig, expected):
        return None
    return payload
