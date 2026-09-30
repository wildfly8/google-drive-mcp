"""A passkey saved for one browser continues the subscription in another."""

from __future__ import annotations

import hashlib
import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.testclient import TestClient

from fakes.fake_billing import FakeBilling
from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.billing.entitlement import COOKIE_NAME, mint_entitlement
from google_drive_mcp.infra.billing.passkey import relying_party
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.jwt import b64url_encode
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import streamable_app


def _paid_settings() -> Settings:
    return Settings.for_tests().model_copy(
        update={"mcp_subscription_required": True, "stripe_price_id": "price_test"}
    )


def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([(major << 5) | n])
    if n < 256:
        return bytes([(major << 5) | 24, n])
    return bytes([(major << 5) | 25]) + n.to_bytes(2, "big")


def _cbor(value: object) -> bytes:
    if isinstance(value, int):
        if value >= 0:
            return _head(0, value)
        return _head(1, -1 - value)
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return _head(3, len(raw)) + raw
    if isinstance(value, dict):
        out = _head(5, len(value))
        for key, item in value.items():
            out += _cbor(key) + _cbor(item)
        return out
    raise TypeError(type(value))


def _client_data(kind: str, challenge: str, origin: str) -> bytes:
    return json.dumps(
        {"type": kind, "challenge": challenge, "origin": origin},
        separators=(",", ":"),
    ).encode()


def test_passkey_from_one_browser_sets_cookie_on_another(fake_drive: FakeDrive):
    settings = _paid_settings()
    billing = FakeBilling()
    billing.active.add("cus_live1")
    runtime = Runtime(settings=settings, drive=fake_drive, billing=billing)
    token = mint_entitlement(settings, customer_id="cus_live1")
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    x = numbers.x.to_bytes(32, "big")
    y = numbers.y.to_bytes(32, "big")
    cred_id = b"cred-passkey-001"
    _rp, origin = relying_party(settings)
    rp_hash = hashlib.sha256(_rp.encode()).digest()

    with TestClient(streamable_app(runtime, json_response=True)) as client:
        client.cookies.set(COOKIE_NAME, token)
        page = client.get("/subscribe", follow_redirects=False)
        assert page.status_code == 303
        assert ">Continue</button>" not in page.text
        assert "Remember this subscription" not in page.text
        options = client.post("/subscribe/passkey/options")
        challenge = options.json()["publicKey"]["challenge"]
        reg_client = _client_data("webauthn.create", challenge, origin)
        reg_auth = (
            rp_hash
            + bytes([0x45])
            + (1).to_bytes(4, "big")
            + bytes(16)
            + len(cred_id).to_bytes(2, "big")
            + cred_id
            + _cbor({1: 2, 3: -7, -1: 1, -2: x, -3: y})
        )
        registered = client.post(
            "/subscribe/passkey/register",
            json={
                "id": b64url_encode(cred_id),
                "response": {
                    "clientDataJSON": b64url_encode(reg_client),
                    "attestationObject": b64url_encode(
                        _cbor({"fmt": "none", "attStmt": {}, "authData": reg_auth})
                    ),
                },
            },
        )
        assert registered.status_code == 200
        assert billing.get_passkey("cus_live1")

        client.cookies.clear()
        fresh = client.get("/subscribe")
        assert "Pay $20 / month" in fresh.text
        assert "Continue subscription" not in fresh.text
        assert "device-email" not in fresh.text
        login_options = client.post("/subscribe/passkey/options")
        login_challenge = login_options.json()["publicKey"]["challenge"]
        login_client = _client_data("webauthn.get", login_challenge, origin)
        login_auth = rp_hash + bytes([0x05]) + (2).to_bytes(4, "big")
        signature = key.sign(
            login_auth + hashlib.sha256(login_client).digest(),
            ec.ECDSA(hashes.SHA256()),
        )
        before = billing.checkouts
        finished = client.post(
            "/subscribe/passkey/finish",
            json={
                "id": b64url_encode(cred_id),
                "response": {
                    "clientDataJSON": b64url_encode(login_client),
                    "authenticatorData": b64url_encode(login_auth),
                    "signature": b64url_encode(signature),
                    "userHandle": b64url_encode(b"cus_live1"),
                },
            },
        )
        assert finished.status_code == 200
        assert finished.json()["redirect"] == "/setup"
        assert COOKIE_NAME in finished.cookies
        assert billing.checkouts == before
