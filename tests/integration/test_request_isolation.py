"""Concurrent requests mint distinct Google credential objects."""

from __future__ import annotations

import asyncio

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.google_auth.refresh_token import mint_readonly_credentials


async def test_overlapping_mints_are_distinct_objects():
    settings = Settings.for_tests()

    async def mint():
        return mint_readonly_credentials(settings)

    first, second = await asyncio.gather(mint(), mint())
    assert first is not second
    assert getattr(first, "_mcp_request_key") != getattr(second, "_mcp_request_key")
    assert first.scopes == ["https://www.googleapis.com/auth/drive.readonly"]
    assert second.scopes == ["https://www.googleapis.com/auth/drive.readonly"]
