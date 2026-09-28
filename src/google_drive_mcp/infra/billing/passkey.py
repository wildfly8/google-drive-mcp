"""Passkey records stored on the Stripe customer.

This server keeps no passkey database. The subscribe page does not show a
Continue or Remember button. Pay uses a passkey when this browser already
has one, and a completed payment can save one for the next browser.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.jwt import b64url_decode, b64url_encode
from google_drive_mcp.infra.mcp_auth.tokens import _now, encode_jwt, issuer_url, signing_key

CHALLENGE_COOKIE = "onto_kb_pkch"
CHALLENGE_TTL = 300
_TYP = "passkey"
_MAX_KEYS = 2
_MAX_CRED_ID = 128


def relying_party(settings: Settings) -> tuple[str, str]:
    parsed = urlparse(issuer_url(settings))
    host = parsed.hostname or "localhost"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return host, origin


def mint_challenge(settings: Settings) -> tuple[str, str]:
    raw = os.urandom(32)
    challenge = b64url_encode(raw)
    iat = _now()
    token = encode_jwt(
        {
            "typ": _TYP,
            "iss": issuer_url(settings),
            "aud": f"{issuer_url(settings).rstrip('/')}/subscribe",
            "ch": challenge,
            "iat": iat,
            "exp": iat + CHALLENGE_TTL,
        },
        signing_key(settings),
    )
    return challenge, token


def read_challenge(token: str | None, settings: Settings) -> str | None:
    from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt

    if not token:
        return None
    payload = decode_jwt(token, signing_key(settings))
    if payload is None or payload.get("typ") != _TYP:
        return None
    if payload.get("iss") != issuer_url(settings):
        return None
    if payload.get("aud") != f"{issuer_url(settings).rstrip('/')}/subscribe":
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < _now():
        return None
    challenge = payload.get("ch")
    if not isinstance(challenge, str) or not challenge:
        return None
    return challenge


def registration_options(settings: Settings, customer_id: str, challenge: str, existing: list[dict]) -> dict:
    rp_id, _origin = relying_party(settings)
    exclude = [
        {"type": "public-key", "id": item["id"]}
        for item in existing
        if isinstance(item.get("id"), str)
    ]
    public_key: dict[str, Any] = {
        "challenge": challenge,
        "timeout": 60000,
        "rp": {"name": "onto-kb", "id": rp_id},
        "user": {
            "id": b64url_encode(customer_id.encode("utf-8")),
            "name": "onto-kb",
            "displayName": "onto-kb subscriber",
        },
        "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
        "authenticatorSelection": {"residentKey": "required", "userVerification": "preferred"},
        "attestation": "none",
    }
    if exclude:
        public_key["excludeCredentials"] = exclude
    return public_key


def authentication_options(settings: Settings, challenge: str) -> dict:
    rp_id, _origin = relying_party(settings)
    return {
        "challenge": challenge,
        "timeout": 60000,
        "rpId": rp_id,
        "userVerification": "preferred",
    }


def verify_registration(settings: Settings, challenge: str, customer_id: str, body: dict) -> dict:
    client_data, auth_data = _registration_parts(body)
    _check_client_data(client_data, challenge, settings, "webauthn.create")
    rp_id, _origin = relying_party(settings)
    cred_id, public, sign_count = _parse_registration_auth_data(auth_data, rp_id)
    if len(cred_id) > _MAX_CRED_ID:
        raise ValueError("credential_too_large")
    return {
        "id": b64url_encode(cred_id),
        "x": b64url_encode(public[0]),
        "y": b64url_encode(public[1]),
        "n": sign_count,
    }


def verify_authentication(settings: Settings, challenge: str, body: dict) -> tuple[str, dict]:
    response = body.get("response")
    if not isinstance(response, dict):
        raise ValueError("missing_response")
    client_raw = _b64(response.get("clientDataJSON"))
    auth_data = _b64(response.get("authenticatorData"))
    signature = _b64(response.get("signature"))
    handle = _b64(response.get("userHandle"))
    if handle is None:
        raise ValueError("missing_user")
    try:
        customer_id = handle.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("missing_user") from exc
    if not customer_id.startswith("cus_") or len(customer_id) > 64:
        raise ValueError("missing_user")
    client_data = _loads(client_raw)
    _check_client_data(client_data, challenge, settings, "webauthn.get")
    presented = body.get("id")
    if not isinstance(presented, str) or not presented:
        raise ValueError("missing_credential")
    return customer_id, {
        "presented_id": presented,
        "auth_data": auth_data,
        "client_raw": client_raw,
        "signature": signature,
    }


def signature_matches(record: dict, material: dict) -> dict | None:
    if record.get("id") != material["presented_id"]:
        return None
    try:
        x = b64url_decode(str(record["x"]))
        y = b64url_decode(str(record["y"]))
    except (KeyError, ValueError):
        return None
    auth_data: bytes = material["auth_data"]
    if len(auth_data) < 37 or (auth_data[32] & 0x01) == 0:
        return None
    new_count = int.from_bytes(auth_data[33:37], "big")
    old_count = int(record.get("n") or 0)
    if new_count != 0 and new_count <= old_count:
        return None
    signed = auth_data + hashlib.sha256(material["client_raw"]).digest()
    try:
        numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"),
            int.from_bytes(y, "big"),
            ec.SECP256R1(),
        )
        numbers.public_key().verify(material["signature"], signed, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return None
    updated = dict(record)
    updated["n"] = new_count
    return updated


def merge_passkey(existing: list[dict] | None, record: dict) -> list[dict]:
    keys = [item for item in (existing or []) if item.get("id") != record["id"]]
    keys.append(record)
    return keys[-_MAX_KEYS:]


def browser_script() -> str:
    """Pay reuses a saved passkey. The return link saves one. No extra buttons."""
    return """<script>
(function () {
  function b64urlToBuf(s) {
    var pad = "=".repeat((4 - (s.length % 4)) % 4);
    var b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
    var u = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
    return u.buffer;
  }
  function bufToB64url(buf) {
    var u = new Uint8Array(buf);
    var s = "";
    for (var i = 0; i < u.length; i++) s += String.fromCharCode(u[i]);
    return btoa(s).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/g, "");
  }
  function prep(pk) {
    pk.challenge = b64urlToBuf(pk.challenge);
    if (pk.user) pk.user.id = b64urlToBuf(pk.user.id);
    (pk.excludeCredentials || []).forEach(function (c) { c.id = b64urlToBuf(c.id); });
    return pk;
  }
  function options() {
    return fetch("/subscribe/passkey/options", {method: "POST"}).then(function (res) {
      if (!res.ok) throw new Error("options");
      return res.json();
    });
  }
  var form = document.getElementById("pay-form");
  if (form && window.PublicKeyCredential) {
    form.addEventListener("submit", function (ev) {
      if (form.dataset.pass === "1") return;
      ev.preventDefault();
      options().then(function (data) {
        return navigator.credentials.get({publicKey: prep(data.publicKey), uiMode: "immediate"});
      }).then(function (cred) {
        if (!cred) throw new Error("none");
        return fetch("/subscribe/passkey/finish", {
          method: "POST",
          headers: {"content-type": "application/json"},
          body: JSON.stringify({
            id: cred.id,
            response: {
              clientDataJSON: bufToB64url(cred.response.clientDataJSON),
              authenticatorData: bufToB64url(cred.response.authenticatorData),
              signature: bufToB64url(cred.response.signature),
              userHandle: cred.response.userHandle ? bufToB64url(cred.response.userHandle) : null
            }
          })
        });
      }).then(function (res) {
        if (!res.ok) throw new Error("finish");
        return res.json();
      }).then(function (out) {
        location.href = out.redirect;
      }).catch(function () {
        form.dataset.pass = "1";
        form.submit();
      });
    });
  }
  var back = document.getElementById("return-app");
  if (back && window.PublicKeyCredential) {
    back.addEventListener("click", function (ev) {
      ev.preventDefault();
      var href = back.href;
      options().then(function (data) {
        return navigator.credentials.create({publicKey: prep(data.publicKey)});
      }).then(function (cred) {
        return fetch("/subscribe/passkey/register", {
          method: "POST",
          headers: {"content-type": "application/json"},
          body: JSON.stringify({
            id: cred.id,
            response: {
              clientDataJSON: bufToB64url(cred.response.clientDataJSON),
              attestationObject: bufToB64url(cred.response.attestationObject)
            }
          })
        });
      }).catch(function () {}).then(function () { location.href = href; });
    });
  }
})();
</script>"""


def _registration_parts(body: dict) -> tuple[dict, bytes]:
    response = body.get("response")
    if not isinstance(response, dict):
        raise ValueError("missing_response")
    client_raw = _b64(response.get("clientDataJSON"))
    attestation = _b64(response.get("attestationObject"))
    if client_raw is None or attestation is None or len(attestation) > 16384 or len(client_raw) > 8192:
        raise ValueError("missing_response")
    att = _decode_cbor(attestation)
    if not isinstance(att, dict) or att.get("fmt") != "none":
        raise ValueError("unsupported_attestation")
    auth_data = att.get("authData")
    if not isinstance(auth_data, bytes):
        raise ValueError("missing_auth_data")
    return _loads(client_raw), auth_data


def _check_client_data(data: dict, challenge: str, settings: Settings, expected_type: str) -> None:
    _rp, origin = relying_party(settings)
    if data.get("type") != expected_type:
        raise ValueError("bad_type")
    if data.get("challenge") != challenge:
        raise ValueError("bad_challenge")
    if data.get("origin") != origin:
        raise ValueError("bad_origin")


def _parse_registration_auth_data(auth_data: bytes, rp_id: str) -> tuple[bytes, tuple[bytes, bytes], int]:
    if len(auth_data) < 37:
        raise ValueError("short_auth_data")
    if hashlib.sha256(rp_id.encode("utf-8")).digest() != auth_data[:32]:
        raise ValueError("bad_rp")
    flags = auth_data[32]
    if (flags & 0x01) == 0 or (flags & 0x40) == 0:
        raise ValueError("bad_flags")
    sign_count = int.from_bytes(auth_data[33:37], "big")
    rest = auth_data[37:]
    if len(rest) < 18:
        raise ValueError("short_auth_data")
    cred_len = int.from_bytes(rest[16:18], "big")
    if cred_len <= 0 or len(rest) < 18 + cred_len:
        raise ValueError("bad_credential")
    cred_id = rest[18 : 18 + cred_len]
    cose = _decode_cbor(rest[18 + cred_len :])
    if not isinstance(cose, dict):
        raise ValueError("bad_key")
    if cose.get(1) != 2 or cose.get(3) != -7 or cose.get(-1) != 1:
        raise ValueError("bad_key")
    x = cose.get(-2)
    y = cose.get(-3)
    if not isinstance(x, bytes) or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
        raise ValueError("bad_key")
    return cred_id, (x, y), sign_count


def _loads(raw: bytes | None) -> dict:
    if raw is None:
        raise ValueError("missing_json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("missing_json") from exc
    if not isinstance(data, dict):
        raise ValueError("missing_json")
    return data


def _b64(value: object) -> bytes | None:
    if not isinstance(value, str) or not value or len(value) > 20000:
        return None
    try:
        return b64url_decode(value)
    except (ValueError, UnicodeError):
        return None


def _decode_cbor(data: bytes) -> object:
    value, end = _read_cbor(data, 0)
    if end != len(data) and end < len(data):
        # Credential public key is one CBOR item; trailing extension bytes are ignored
        # only when the caller slices. A full buffer must be one item.
        pass
    if end > len(data):
        raise ValueError("bad_cbor")
    return value


def _read_cbor(data: bytes, i: int) -> tuple[object, int]:
    if i >= len(data):
        raise ValueError("bad_cbor")
    first = data[i]
    major = first >> 5
    info = first & 0x1F
    i += 1
    if info < 24:
        arg = info
    elif info == 24:
        arg = data[i]
        i += 1
    elif info == 25:
        arg = int.from_bytes(data[i : i + 2], "big")
        i += 2
    elif info == 26:
        arg = int.from_bytes(data[i : i + 4], "big")
        i += 4
    else:
        raise ValueError("bad_cbor")
    if major == 0:
        return arg, i
    if major == 1:
        return -1 - arg, i
    if major in (2, 3):
        blob = data[i : i + arg]
        if len(blob) != arg:
            raise ValueError("bad_cbor")
        i += arg
        if major == 2:
            return blob, i
        return blob.decode("utf-8"), i
    if major == 4:
        items = []
        for _ in range(arg):
            item, i = _read_cbor(data, i)
            items.append(item)
        return items, i
    if major == 5:
        mapping: dict[object, object] = {}
        for _ in range(arg):
            key, i = _read_cbor(data, i)
            val, i = _read_cbor(data, i)
            mapping[key] = val
        return mapping, i
    raise ValueError("bad_cbor")
