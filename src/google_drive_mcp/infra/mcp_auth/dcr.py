"""Stateless dynamic client registration (RFC 7591).

The client_id is a signed record of the registration, so any instance resolves it
after scale-to-zero, a deploy, or on another instance, and nothing is stored. Its typ
("dcr") and aud (the issuer) match no other value this origin signs, so it never
verifies as an access or refresh token, code, consent ticket, or entitlement.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections import OrderedDict

from mcp.server.auth.provider import RegistrationError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import ValidationError

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt, encode_jwt
from google_drive_mcp.infra.mcp_auth.tokens import _now, issuer_url, signing_key

TYP_DCR = "dcr"
MAX_CLIENT_NAME = 200
KEPT_CLIENT_NAME = 100
MAX_REDIRECT_URIS = 5
MAX_REDIRECT_URI = 512
MAX_CONTACTS = 5
MAX_CONTACT = 254
MAX_METADATA_BYTES = 16 * 1024
# Codes, tickets and tokens carry the client_id and are refused over 8 KiB.
MAX_CLIENT_ID = 4096
CACHE_SIZE = 1000

# Short claim names: the client_id rides in every token and /authorize URL.
_CLAIMS = {
    "ru": "redirect_uris",
    "cn": "client_name",
    "gt": "grant_types",
    "rt": "response_types",
    "am": "token_endpoint_auth_method",
    "sc": "scope",
}


def _invalid(description: str) -> RegistrationError:
    return RegistrationError(error="invalid_client_metadata", error_description=description)


def validate_metadata(info: OAuthClientInformationFull) -> None:
    """Refuse oversized metadata before anything is signed (the SDK sets no limits)."""
    if info.client_name is not None and len(info.client_name) > MAX_CLIENT_NAME:
        raise _invalid(f"client_name is longer than {MAX_CLIENT_NAME} characters")
    uris = info.redirect_uris or []
    if len(uris) > MAX_REDIRECT_URIS:
        raise _invalid(f"at most {MAX_REDIRECT_URIS} redirect_uris")
    if any(len(str(uri)) > MAX_REDIRECT_URI for uri in uris):
        raise _invalid(f"a redirect_uri is longer than {MAX_REDIRECT_URI} characters")
    contacts = info.contacts or []
    if len(contacts) > MAX_CONTACTS or any(len(c) > MAX_CONTACT for c in contacts):
        raise _invalid(f"at most {MAX_CONTACTS} contacts of up to {MAX_CONTACT} characters")
    if len(info.model_dump_json(exclude_none=True).encode("utf-8")) > MAX_METADATA_BYTES:
        raise _invalid("client metadata is larger than 16 KB")


def client_secret(settings: Settings, client_id: str) -> str:
    message = b"dcr-secret:" + client_id.encode("utf-8")
    return hmac.new(signing_key(settings), message, hashlib.sha256).hexdigest()


def mint_client_id(settings: Settings, info: OAuthClientInformationFull, *, iat: int) -> str:
    record = {
        "ru": [str(uri) for uri in info.redirect_uris or []],
        "cn": (info.client_name or "")[:KEPT_CLIENT_NAME],
        "gt": list(info.grant_types),
        "rt": list(info.response_types),
        "am": info.token_endpoint_auth_method,
        "sc": info.scope,
    }
    claims = {
        "typ": TYP_DCR,
        "aud": issuer_url(settings),
        "iat": iat,
        # Two registrations with the same metadata in the same second still differ.
        "jti": secrets.token_urlsafe(9),
    }
    claims.update({key: value for key, value in record.items() if value})
    client_id = encode_jwt(claims, signing_key(settings))
    if len(client_id) > MAX_CLIENT_ID:
        raise _invalid("registration is too large; send fewer or shorter redirect_uris")
    return client_id


def client_from_id(settings: Settings, client_id: str) -> OAuthClientInformationFull | None:
    if len(client_id) > MAX_CLIENT_ID:
        return None
    claims = decode_jwt(client_id, signing_key(settings))
    if claims is None or claims.get("typ") != TYP_DCR:
        return None
    if claims.get("aud") != issuer_url(settings):
        return None
    record = {name: claims[key] for key, name in _CLAIMS.items() if key in claims}
    record.update(client_id=client_id, client_id_issued_at=claims.get("iat"))
    if record.get("token_endpoint_auth_method") != "none":
        record.update(client_secret=client_secret(settings, client_id), client_secret_expires_at=0)
    try:
        return OAuthClientInformationFull.model_validate(record)
    except ValidationError:
        return None


class DcrClients:
    """Registers clients by signing their metadata into the client_id; resolves them
    on any instance. Keeps the most recently used records in a small LRU."""

    def __init__(self, settings: Settings, max_size: int = CACHE_SIZE) -> None:
        self.settings = settings
        self._max_size = max_size
        self._cache: OrderedDict[str, OAuthClientInformationFull] = OrderedDict()

    def register(self, info: OAuthClientInformationFull) -> None:
        """Replace the SDK's random client_id and secret in place; the SDK returns
        this same object as the registration response."""
        validate_metadata(info)
        iat = info.client_id_issued_at or _now()
        client_id = mint_client_id(self.settings, info, iat=iat)
        info.client_id = client_id
        info.client_id_issued_at = iat
        if info.client_name:
            info.client_name = info.client_name[:KEPT_CLIENT_NAME]
        if info.token_endpoint_auth_method == "none":
            info.client_secret = None
            info.client_secret_expires_at = None
        else:
            info.client_secret = client_secret(self.settings, client_id)
            info.client_secret_expires_at = 0

    def get(self, client_id: str) -> OAuthClientInformationFull | None:
        cached = self._cache.get(client_id)
        if cached is not None:
            self._cache.move_to_end(client_id)
            return cached
        client = client_from_id(self.settings, client_id)
        if client is None:
            return None
        self._cache[client_id] = client
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return client

    def __len__(self) -> int:
        return len(self._cache)
