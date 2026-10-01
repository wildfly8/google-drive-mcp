"""Embedded OAuth 2.1 authorization server for this MCP origin.

DCR client records live in process memory (hosts re-register after scale-to-zero).
Access, refresh, and authorization-code values are signed JWTs so /mcp verification
does not depend on which Cloud Run instance handled /token.
"""

from __future__ import annotations

import uuid

import anyio.to_thread

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

from google_drive_mcp.domain.connect_telemetry import host_family_from_client_id
from google_drive_mcp.infra.billing.entitlement import ENTITLEMENT_TTL, current_scid
from google_drive_mcp.infra.billing.gateway import (
    BillingGateway,
    BillingUnavailable,
    InactiveBilling,
)
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.cimd import fetch_cimd_client
from google_drive_mcp.infra.telemetry.recorder import ConnectRecorder
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
    def __init__(
        self, settings: Settings, telemetry: ConnectRecorder | None = None,
        billing: BillingGateway | None = None,
    ) -> None:
        self.settings = settings
        self.telemetry = telemetry or ConnectRecorder()
        self.billing = billing or InactiveBilling()
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
        cached = self.clients.get(client_id)
        if cached is not None:
            return cached
        fetched = await fetch_cimd_client(client_id)
        if fetched is not None:
            self.clients[client_id] = fetched
        return fetched

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise ValueError("No client_id provided")
        self.clients[client_info.client_id] = client_info

    async def _subscription_state(self, customer_id: str) -> bool | None:
        """Ask Stripe off the event loop, so a slow or retried call stalls nothing else."""
        return await anyio.to_thread.run_sync(self.billing.subscription_state, customer_id)

    async def _active(self, customer_id: str | None) -> bool:
        return bool(customer_id) and await self._subscription_state(str(customer_id)) is True

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not client.client_id:
            raise AuthorizeError(error="unauthorized_client", error_description="missing client_id")
        requested = params.scopes or [MCP_OAUTH_SCOPE]
        if set(requested) - {MCP_OAUTH_SCOPE}:
            raise AuthorizeError(error="invalid_scope", error_description="only drive.read is supported")
        resource = self._bound_resource(params.resource)
        redirect = str(params.redirect_uri)
        scid: str | None = None
        if self.settings.mcp_subscription_required:
            scid = current_scid()
            if not await self._active(scid):
                return f"{issuer_url(self.settings).rstrip('/')}/subscribe"
        # A paid Connect always asks the subscriber to Allow: any site can register
        # a client and send a subscriber's browser here, so the code must never be
        # issued without a click on this origin's page.
        if self.settings.mcp_oauth_auto_approve and not scid:
            code = mint_authorization_code(
                self.settings,
                client_id=client.client_id,
                redirect_uri=redirect,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                code_challenge=params.code_challenge,
                resource=resource,
                scid=scid,
            )
            return construct_redirect_uri(
                redirect,
                code=code,
                state=params.state,
                iss=issuer_url(self.settings),
            )
        ticket = mint_consent_ticket(
            self.settings,
            client_id=client.client_id,
            redirect_uri=redirect,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            state=params.state,
            resource=resource,
            scid=scid,
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
            scid=str(claims["scid"]) if claims.get("scid") else None,
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
        connect_id = str(uuid.uuid4())
        scid = claims.get("scid")
        sid = str(scid) if isinstance(scid, str) and scid else None
        if self.settings.mcp_subscription_required:
            state = await self._subscription_state(sid) if sid else False
            if state is None:
                raise BillingUnavailable("subscription check unavailable")
            if not state:
                raise TokenError(error="invalid_grant", error_description="subscription inactive")
        self.telemetry.record_oauth_connect(
            connect_id, host_family_from_client_id(client.client_id)
        )
        return self._issue_tokens(client.client_id, connect_id=connect_id, scid=sid)

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
        granted = scopes or [MCP_OAUTH_SCOPE]
        if set(granted) - {MCP_OAUTH_SCOPE}:
            raise TokenError(error="invalid_scope", error_description="only drive.read is supported")
        connect_id = claims.get("cid")
        cid = str(connect_id) if isinstance(connect_id, str) and connect_id else None
        scid = claims.get("scid")
        sid = str(scid) if isinstance(scid, str) and scid else None
        jti = str(claims["jti"])
        if jti in self._revoked_jti:
            raise TokenError(
                error="invalid_grant", error_description="refresh token does not exist"
            )
        # Reserve the token before asking Stripe, so two refreshes with it cannot
        # both succeed; give it back if this refresh fails, so a Stripe outage or
        # a lapse that is later fixed (card updated) does not use it up.
        self._revoked_jti.add(jti)
        try:
            if self.settings.mcp_subscription_required:
                state = await self._subscription_state(sid) if sid else False
                if state is None:
                    # Not invalid_grant: hosts discard tokens on that. A 503 is retried.
                    raise BillingUnavailable("subscription check unavailable")
                if not state:
                    raise TokenError(
                        error="invalid_grant", error_description="subscription inactive"
                    )
        except BaseException:
            self._revoked_jti.discard(jti)
            raise
        return self._issue_tokens(client.client_id, connect_id=cid, scid=sid)

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

    def _issue_tokens(
        self, client_id: str, *, connect_id: str | None = None, scid: str | None = None
    ) -> OAuthToken:
        access = mint_access_token(
            self.settings, client_id=client_id, connect_id=connect_id, scid=scid
        )
        refresh = mint_refresh_token(
            self.settings,
            client_id=client_id,
            connect_id=connect_id,
            scid=scid,
            ttl=ENTITLEMENT_TTL if scid else None,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self.settings.mcp_access_token_ttl_seconds,
            scope=MCP_OAUTH_SCOPE,
            refresh_token=refresh,
        )
