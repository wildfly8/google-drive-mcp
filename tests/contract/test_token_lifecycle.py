"""Token lifecycle on the paid server: single-use codes, revocation, no free legacy tokens.

These drive the OAuth provider directly, with Stripe faked, so each rule is tested on its own
instead of through the whole Connect flow.
"""

from __future__ import annotations

import pytest
from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthClientInformationFull

from fakes.fake_billing import FakeBilling
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.mcp_auth.provider import DriveMcpOAuthProvider
from google_drive_mcp.infra.mcp_auth.tokens import (
    mint_authorization_code,
    mint_refresh_token,
    resource_url,
    verify_refresh_claims,
)

REDIRECT = "http://127.0.0.1/callback"
CUSTOMER = "cus_live1"


def _paid() -> tuple[Settings, FakeBilling, DriveMcpOAuthProvider]:
    settings = Settings.for_tests().model_copy(update={"mcp_subscription_required": True})
    billing = FakeBilling()
    billing.active.add(CUSTOMER)
    return settings, billing, DriveMcpOAuthProvider(settings, billing=billing)


def _client(client_id: str = "host-1") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(client_id=client_id, redirect_uris=[REDIRECT])


def _code(settings: Settings, *, scid: str | None, client_id: str = "host-1") -> str:
    return mint_authorization_code(
        settings,
        client_id=client_id,
        redirect_uri=REDIRECT,
        redirect_uri_provided_explicitly=True,
        code_challenge="abc",
        resource=resource_url(settings),
        scid=scid,
    )


async def test_an_authorization_code_works_once():
    settings, _billing, provider = _paid()
    client = _client()
    code = _code(settings, scid=CUSTOMER)
    loaded = await provider.load_authorization_code(client, code)
    assert loaded is not None
    await provider.exchange_authorization_code(client, loaded)
    # Used: it is not loaded again, and presenting it to the exchange again is refused.
    assert await provider.load_authorization_code(client, code) is None
    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(client, loaded)


async def test_a_code_from_before_the_paywall_has_no_customer_and_is_refused():
    settings, _billing, provider = _paid()
    client = _client()
    loaded = await provider.load_authorization_code(client, _code(settings, scid=None))
    assert loaded is not None
    with pytest.raises(TokenError) as caught:
        await provider.exchange_authorization_code(client, loaded)
    assert "subscription inactive" in str(caught.value.error_description)


async def test_a_refresh_token_from_before_the_paywall_is_refused():
    settings, _billing, provider = _paid()
    client = _client()
    legacy = mint_refresh_token(settings, client_id="host-1", scid=None)
    loaded = await provider.load_refresh_token(client, legacy)
    assert loaded is not None
    with pytest.raises(TokenError) as caught:
        await provider.exchange_refresh_token(client, loaded, [])
    assert "subscription inactive" in str(caught.value.error_description)


async def test_a_refreshed_token_can_be_refreshed_again():
    """The new refresh token carries the customer id, so a subscriber is not locked out
    after the first rotation."""
    settings, _billing, provider = _paid()
    client = _client()
    first = mint_refresh_token(settings, client_id="host-1", scid=CUSTOMER)
    issued = await provider.exchange_refresh_token(
        client, await provider.load_refresh_token(client, first), []
    )
    assert verify_refresh_claims(issued.refresh_token, settings)["scid"] == CUSTOMER
    second = await provider.load_refresh_token(client, issued.refresh_token)
    assert second is not None
    again = await provider.exchange_refresh_token(client, second, [])
    assert again.access_token and again.refresh_token


async def test_a_revoked_access_token_is_no_longer_accepted():
    _settings, _billing, provider = _paid()
    issued = provider._issue_tokens("host-1", scid=CUSTOMER)
    access = await provider.load_access_token(issued.access_token)
    assert access is not None
    await provider.revoke_token(access)
    assert await provider.load_access_token(issued.access_token) is None


async def test_a_revoked_refresh_token_is_no_longer_accepted():
    _settings, _billing, provider = _paid()
    client = _client()
    issued = provider._issue_tokens("host-1", scid=CUSTOMER)
    refresh = await provider.load_refresh_token(client, issued.refresh_token)
    assert refresh is not None
    await provider.revoke_token(refresh)
    assert await provider.load_refresh_token(client, issued.refresh_token) is None


async def test_a_code_and_a_refresh_token_belong_to_the_client_they_were_issued_to():
    settings, _billing, provider = _paid()
    owner, stranger = _client("host-1"), _client("host-2")
    code = _code(settings, scid=CUSTOMER, client_id="host-1")
    assert await provider.load_authorization_code(owner, code) is not None
    assert await provider.load_authorization_code(stranger, code) is None
    refresh = mint_refresh_token(settings, client_id="host-1", scid=CUSTOMER)
    assert await provider.load_refresh_token(owner, refresh) is not None
    assert await provider.load_refresh_token(stranger, refresh) is None
