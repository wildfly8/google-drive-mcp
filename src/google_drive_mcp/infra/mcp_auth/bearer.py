"""Constant-time MCP bearer comparison. Never forwards the token to Google."""

from __future__ import annotations

import hmac


def extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "bearer "
    if authorization[:7].lower() == prefix:
        token = authorization[7:].strip()
        return token or None
    stripped = authorization.strip()
    return stripped or None


def verify_bearer(provided: str | None, expected: str) -> bool:
    if provided is None or expected == "":
        return False
    provided_b = provided.encode("utf-8")
    expected_b = expected.encode("utf-8")
    return hmac.compare_digest(provided_b, expected_b)
