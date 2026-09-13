"""Mint and verify MCP OAuth 2.1 JWTs. Never forwards tokens to Google."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from pydantic import AnyHttpUrl

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.bearer import extract_bearer
from google_drive_mcp.infra.mcp_auth.jwt import decode_jwt, encode_jwt

MCP_OAUTH_SCOPE = "drive.read"
TYP_ACCESS = "access"
TYP_REFRESH = "refresh"
TYP_CODE = "code"
TYP_TICKET = "ticket"


def issuer_url(settings: Settings) -> str:
    raw = settings.mcp_public_url.strip().rstrip("/")
    if not raw:
        return ""
    return str(AnyHttpUrl(raw))


def resource_url(settings: Settings) -> str:
    return f"{issuer_url(settings).rstrip('/')}/mcp"


def consent_url(settings: Settings) -> str:
    return f"{issuer_url(settings).rstrip('/')}/consent"


def signing_key(settings: Settings) -> bytes:
    explicit = settings.mcp_oauth_signing_key.get_secret_value()
    if explicit:
        return hashlib.sha256(explicit.encode("utf-8")).digest()
    password = settings.mcp_auth_token.get_secret_value()
    return hashlib.sha256(b"mcp-oauth-jwt-v1:" + password.encode("utf-8")).digest()


def _now() -> int:
    return int(time.time())


def _base_claims(
    settings: Settings,
    *,
    typ: str,
    aud: str,
    client_id: str,
    ttl: int,
    extra: dict[str, Any],
) -> dict[str, Any]:
    iat = _now()
    claims: dict[str, Any] = {
        "typ": typ,
        "iss": issuer_url(settings),
        "aud": aud,
        "sub": settings.mcp_principal_id,
        "client_id": client_id,
        "scope": MCP_OAUTH_SCOPE,
        "iat": iat,
        "exp": iat + ttl,
        "jti": str(uuid.uuid4()),
    }
    claims.update(extra)
    return claims


def mint_access_token(
    settings: Settings,
    *,
    client_id: str = "test-client",
    ttl: int | None = None,
) -> str:
    claims = _base_claims(
        settings,
        typ=TYP_ACCESS,
        aud=resource_url(settings),
        client_id=client_id,
        ttl=ttl if ttl is not None else settings.mcp_access_token_ttl_seconds,
        extra={"resource": resource_url(settings)},
    )
    return encode_jwt(claims, signing_key(settings))


def mint_refresh_token(settings: Settings, *, client_id: str) -> str:
    claims = _base_claims(
        settings,
        typ=TYP_REFRESH,
        aud=resource_url(settings),
        client_id=client_id,
        ttl=settings.mcp_refresh_token_ttl_seconds,
        extra={"resource": resource_url(settings)},
    )
    return encode_jwt(claims, signing_key(settings))


def mint_authorization_code(
    settings: Settings,
    *,
    client_id: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    code_challenge: str,
    resource: str,
) -> str:
    claims = _base_claims(
        settings,
        typ=TYP_CODE,
        aud=resource_url(settings),
        client_id=client_id,
        ttl=settings.mcp_authorization_code_ttl_seconds,
        extra={
            "resource": resource,
            "redirect_uri": redirect_uri,
            "redirect_uri_provided_explicitly": redirect_uri_provided_explicitly,
            "code_challenge": code_challenge,
        },
    )
    return encode_jwt(claims, signing_key(settings))


def mint_consent_ticket(
    settings: Settings,
    *,
    client_id: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    code_challenge: str,
    state: str | None,
    resource: str,
) -> str:
    extra: dict[str, Any] = {
        "resource": resource,
        "redirect_uri": redirect_uri,
        "redirect_uri_provided_explicitly": redirect_uri_provided_explicitly,
        "code_challenge": code_challenge,
    }
    if state is not None:
        extra["state"] = state
    claims = _base_claims(
        settings,
        typ=TYP_TICKET,
        aud=consent_url(settings),
        client_id=client_id,
        ttl=600,
        extra=extra,
    )
    return encode_jwt(claims, signing_key(settings))


def _verify(
    token: str | None,
    settings: Settings,
    *,
    typ: str,
    audience: str,
) -> dict[str, Any] | None:
    if not token:
        return None
    payload = decode_jwt(token, signing_key(settings))
    if payload is None:
        return None
    if payload.get("typ") != typ:
        return None
    if payload.get("iss") != issuer_url(settings):
        return None
    if payload.get("aud") != audience:
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < _now():
        return None
    if payload.get("scope") != MCP_OAUTH_SCOPE:
        return None
    if not payload.get("client_id") or not payload.get("jti"):
        return None
    return payload


def verify_access_claims(token: str | None, settings: Settings) -> dict[str, Any] | None:
    return _verify(token, settings, typ=TYP_ACCESS, audience=resource_url(settings))


def verify_refresh_claims(token: str | None, settings: Settings) -> dict[str, Any] | None:
    return _verify(token, settings, typ=TYP_REFRESH, audience=resource_url(settings))


def verify_code_claims(token: str | None, settings: Settings) -> dict[str, Any] | None:
    return _verify(token, settings, typ=TYP_CODE, audience=resource_url(settings))


def verify_ticket_claims(token: str | None, settings: Settings) -> dict[str, Any] | None:
    return _verify(token, settings, typ=TYP_TICKET, audience=consent_url(settings))


def verify_authorization_header(authorization: str | None, settings: Settings) -> bool:
    return verify_access_claims(extract_bearer(authorization), settings) is not None


def authorization_header(settings: Settings) -> str:
    return f"Bearer {mint_access_token(settings)}"
