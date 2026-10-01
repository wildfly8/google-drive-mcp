"""Shared pytest fixtures."""

from __future__ import annotations

import logging

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


@pytest.fixture(autouse=True)
def _restore_logging():
    """server.main() calls configure_logging(); undo it so later tests see defaults."""
    app = logging.getLogger("google_drive_mcp")
    saved = {
        "app": (app.level, app.propagate, list(app.handlers)),
        "httpx": logging.getLogger("httpx").level,
        "httpcore": logging.getLogger("httpcore").level,
    }
    yield
    app.setLevel(saved["app"][0])
    app.propagate = saved["app"][1]
    app.handlers[:] = saved["app"][2]
    logging.getLogger("httpx").setLevel(saved["httpx"])
    logging.getLogger("httpcore").setLevel(saved["httpcore"])
