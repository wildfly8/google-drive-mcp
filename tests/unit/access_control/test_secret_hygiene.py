"""Logs and error JSON never contain token material."""

from __future__ import annotations

import logging

from fakes.fake_drive import FakeDrive
from google_drive_mcp.mcp.tools import handle_tool
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.infra.config import Settings


TOKENS = ("test-token", "test-refresh-token", "test-client-secret")


def test_error_and_success_omit_secrets(runtime: Runtime, fake_drive: FakeDrive, caplog):
    caplog.set_level(logging.DEBUG)
    settings: Settings = runtime.settings
    secrets = [
        settings.mcp_auth_token.get_secret_value(),
        settings.google_refresh_token.get_secret_value(),
        settings.google_client_secret.get_secret_value(),
    ]
    denied = handle_tool(
        runtime, "scope_probe", {"file_id": "nested-doc"}, "Bearer wrong-token"
    )
    ok = handle_tool(
        runtime, "scope_probe", {"file_id": "nested-doc"}, "Bearer test-token"
    )
    blob = str(denied) + str(ok) + caplog.text + repr(settings)
    for secret in secrets:
        assert secret not in blob
    assert "Authorization" not in str(denied)
    assert ok["status"] == "COMPLETE"
