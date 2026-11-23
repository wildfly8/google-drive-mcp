"""Stripe webhook signatures: the edges that decide whether a forged event is accepted.

The happy path and a wrong signature are tested with the HTTP routes. These cover the rest:
an unset signing secret (anyone could sign with an empty key), a stale timestamp (a captured
event replayed later), and a header with no usable signature.
"""

from __future__ import annotations

import hashlib
import hmac

from google_drive_mcp.infra.billing.stripe_api import verify_stripe_signature

PAYLOAD = b'{"type":"customer.subscription.deleted"}'
NOW = 1_700_000_000


def _header(secret: str, ts: int = NOW, payload: bytes = PAYLOAD) -> str:
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_a_signature_made_with_an_empty_key_is_never_accepted():
    # With no STRIPE_WEBHOOK_SECRET configured, anyone can compute this one.
    assert verify_stripe_signature(PAYLOAD, _header(""), "", now=NOW) is False
    assert verify_stripe_signature(PAYLOAD, _header("real-secret"), "", now=NOW) is False


def test_a_captured_event_cannot_be_replayed_later():
    secret = "whsec_test"
    assert verify_stripe_signature(PAYLOAD, _header(secret), secret, now=NOW) is True
    assert verify_stripe_signature(PAYLOAD, _header(secret), secret, now=NOW + 299) is True
    assert verify_stripe_signature(PAYLOAD, _header(secret), secret, now=NOW + 301) is False
    assert verify_stripe_signature(PAYLOAD, _header(secret), secret, now=NOW - 301) is False


def test_a_header_without_a_usable_signature_is_refused():
    secret = "whsec_test"
    assert verify_stripe_signature(PAYLOAD, "", secret, now=NOW) is False
    assert verify_stripe_signature(PAYLOAD, f"t={NOW}", secret, now=NOW) is False
    assert verify_stripe_signature(PAYLOAD, "v1=abc", secret, now=NOW) is False
    assert verify_stripe_signature(PAYLOAD, "t=soon,v1=abc", secret, now=NOW) is False
    assert verify_stripe_signature(b"", _header(secret, payload=b""), secret, now=NOW) is False
    # A body changed after signing no longer matches.
    assert verify_stripe_signature(PAYLOAD + b" ", _header(secret), secret, now=NOW) is False
