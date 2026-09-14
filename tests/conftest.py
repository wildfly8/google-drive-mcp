"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.mcp.middleware import Runtime


@pytest.fixture
def settings() -> Settings:
    return Settings.for_tests()


@pytest.fixture
def authz(settings: Settings) -> str:
    from google_drive_mcp.infra.mcp_auth.tokens import authorization_header

    return authorization_header(settings)


@pytest.fixture
def fake_drive() -> FakeDrive:
    return FakeDrive.sample()


@pytest.fixture
def runtime(settings: Settings, fake_drive: FakeDrive) -> Runtime:
    return Runtime(settings=settings, drive=fake_drive)
