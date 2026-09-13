"""Embedded OAuth 2.1 authorization server for this MCP origin.

DCR client records live in process memory (hosts re-register after scale-to-zero).
Access, refresh, and authorization-code values are signed JWTs so /mcp verification
does not depend on which Cloud Run instance handled /token.
"""

from __future__ import annotations

from pydantic import AnyUrl
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.tokens import (
    MCP_OAUTH_SCOPE,
    issuer_url,
    mint_access_token,
    mint_authorization_code,
    mint_consent_ticket,
    mint_refresh_token,
    resource_url,
    verify_access_claims,
    verify_code_claims,
    verify_refresh_claims,
)


def _normalize_url(value: str) -> str:
    return value.strip().rstrip("/")


class DriveMcpOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self._used_code_jti: set[str] = set()
        self._revoked_jti: set[str] = set()

    def _resource(self) -> str:
        return resource_url(self.settings)

    def _bound_resource(self, requested: str | None) -> str:
        expected = _normalize_url(self._resource())
        if not requested:
            return expected
        got = _normalize_url(requested)
        if got != expected:
            raise AuthorizeError(
                error="invalid_target",
                error_description="resource must be this server's /mcp URL",
            )
        return expected

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise ValueError("No client_id provided")
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not client.client_id:
            raise AuthorizeError(error="unauthorized_client", error_description="missing client_id")
        requested = params.scopes or [MCP_OAUTH_SCOPE]
        if set(requested) - {MCP_OAUTH_SCOPE}:
            raise AuthorizeError(error="invalid_scope", error_description="only drive.read is supported")
        resource = self._bound_resource(params.resource)
        redirect = str(params.redirect_uri)
        if self.settings.mcp_oauth_auto_approve:
            code = mint_authorization_code(
                self.settings,
                client_id=client.client_id,
                redirect_uri=redirect,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                code_challenge=params.code_challenge,
                resource=resource,
            )
            return construct_redirect_uri(redirect, code=code, state=params.state)
        ticket = mint_consent_ticket(
            self.settings,
            client_id=client.client_id,
            redirect_uri=redirect,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            state=params.state,
            resource=resource,
        )
        return construct_redirect_uri(
            f"{issuer_url(self.settings).rstrip('/')}/consent",
            ticket=ticket,
        )

    def issue_code_from_ticket(self, claims: dict) -> tuple[str, str | None]:
        code = mint_authorization_code(
            self.settings,
            client_id=str(claims["client_id"]),
            redirect_uri=str(claims["redirect_uri"]),
            redirect_uri_provided_explicitly=bool(claims["redirect_uri_provided_explicitly"]),
            code_challenge=str(claims["code_challenge"]),
            resource=str(claims["resource"]),
        )
        state = claims.get("state")
        return code, str(state) if state is not None else None

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        claims = verify_code_claims(authorization_code, self.settings)
        if claims is None:
            return None
        jti = str(claims["jti"])
        if jti in self._used_code_jti or jti in self._revoked_jti:
            return None
        if claims.get("client_id") != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=[MCP_OAUTH_SCOPE],
            expires_at=float(claims["exp"]),
            client_id=str(claims["client_id"]),
            code_challenge=str(claims["code_challenge"]),
            redirect_uri=AnyUrl(str(claims["redirect_uri"])),
            redirect_uri_provided_explicitly=bool(claims["redirect_uri_provided_explicitly"]),
            resource=str(claims.get("resource") or self._resource()),
            subject=self.settings.mcp_principal_id,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        claims = verify_code_claims(authorization_code.code, self.settings)
        if claims is None or not client.client_id:
            raise TokenError(error="invalid_grant", error_description="authorization code does not exist")
        jti = str(claims["jti"])
        if jti in self._used_code_jti:
            raise TokenError(error="invalid_grant", error_description="authorization code does not exist")
        self._used_code_jti.add(jti)
        return self._issue_tokens(client.client_id)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        claims = verify_refresh_claims(refresh_token, self.settings)
        if claims is None:
            return None
        if str(claims["jti"]) in self._revoked_jti:
            return None
        if claims.get("client_id") != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=str(claims["client_id"]),
            scopes=[MCP_OAUTH_SCOPE],
            expires_at=int(claims["exp"]),
            resource=str(claims.get("resource") or self._resource()),
            subject=self.settings.mcp_principal_id,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        claims = verify_refresh_claims(refresh_token.token, self.settings)
        if claims is None or not client.client_id:
            raise TokenError(error="invalid_grant", error_description="refresh token does not exist")
        self._revoked_jti.add(str(claims["jti"]))
        granted = scopes or [MCP_OAUTH_SCOPE]
        if set(granted) - {MCP_OAUTH_SCOPE}:
            raise TokenError(error="invalid_scope", error_description="only drive.read is supported")
        return self._issue_tokens(client.client_id)

    async def load_access_token(self, token: str) -> AccessToken | None:
        claims = verify_access_claims(token, self.settings)
        if claims is None:
            return None
        if str(claims["jti"]) in self._revoked_jti:
            return None
        return AccessToken(
            token=token,
            client_id=str(claims["client_id"]),
            scopes=[MCP_OAUTH_SCOPE],
            expires_at=int(claims["exp"]),
            resource=str(claims.get("resource") or self._resource()),
            subject=self.settings.mcp_principal_id,
            claims={"iss": claims["iss"], "sub": claims.get("sub"), "jti": claims["jti"]},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        raw = token.token
        for verifier in (verify_access_claims, verify_refresh_claims, verify_code_claims):
            claims = verifier(raw, self.settings)
            if claims is not None:
                self._revoked_jti.add(str(claims["jti"]))
                return

    def _issue_tokens(self, client_id: str) -> OAuthToken:
        access = mint_access_token(self.settings, client_id=client_id)
        refresh = mint_refresh_token(self.settings, client_id=client_id)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self.settings.mcp_access_token_ttl_seconds,
            scope=MCP_OAUTH_SCOPE,
            refresh_token=refresh,
        )
