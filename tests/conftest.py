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
def fake_drive() -> FakeDrive:
    return FakeDrive.sample()


@pytest.fixture
def runtime(settings: Settings, fake_drive: FakeDrive) -> Runtime:
    return Runtime(settings=settings, drive=fake_drive)
