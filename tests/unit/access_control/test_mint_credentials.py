"""Per-request credential minting, including authorized-user JSON."""

from __future__ import annotations

import json

from pydantic import SecretStr

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.google_auth.refresh_token import mint_readonly_credentials


def test_mint_prefers_authorized_user_json_over_three_field_refresh():
    info = {
        "type": "authorized_user",
        "client_id": "json-client-id",
        "client_secret": "json-client-secret",
        "refresh_token": "json-refresh-token",
    }
    settings = Settings(
        mcp_auth_token=SecretStr("test-token"),
        mcp_principal_id="deployment-1",
        google_client_id="other-client-id",
        google_client_secret=SecretStr("other-client-secret"),
        google_refresh_token=SecretStr("other-refresh-token"),
        google_authorized_user_json=SecretStr(json.dumps(info)),
    )
    creds = mint_readonly_credentials(settings)
    assert creds.client_id == "json-client-id"
    assert creds.refresh_token == "json-refresh-token"
    assert creds.scopes is None
    dumped = repr(settings) + str(settings)
    assert "json-refresh-token" not in dumped
    assert "json-client-secret" not in dumped


def test_mint_keeps_scopes_declared_on_authorized_user_json():
    info = {
        "type": "authorized_user",
        "client_id": "json-client-id",
        "client_secret": "json-client-secret",
        "refresh_token": "json-refresh-token",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    }
    settings = Settings(
        mcp_auth_token=SecretStr("test-token"),
        mcp_principal_id="deployment-1",
        google_authorized_user_json=SecretStr(json.dumps(info)),
    )
    creds = mint_readonly_credentials(settings)
    assert creds.scopes == ["https://www.googleapis.com/auth/drive.readonly"]


def test_mint_falls_back_to_refresh_token_fields():
    creds = mint_readonly_credentials(Settings.for_tests())
    assert creds.client_id == "test-client-id"
    assert creds.refresh_token == "test-refresh-token"
    assert creds.scopes == ["https://www.googleapis.com/auth/drive.readonly"]
