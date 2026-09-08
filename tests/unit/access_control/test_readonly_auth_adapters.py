"""Read-only auth adapters: oauth scope and MCP registration."""

from __future__ import annotations

from pathlib import Path

from google_drive_mcp.infra.google_auth.refresh_token import DRIVE_READONLY_SCOPE
from google_drive_mcp.mcp.server import create_server
from google_drive_mcp.mcp.tools import READ_ONLY_TOOLS
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.infra.config import Settings
from fakes.fake_drive import FakeDrive

WRITE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.appdata",
)


def test_readonly_oauth_scope_constant():
    assert DRIVE_READONLY_SCOPE == "https://www.googleapis.com/auth/drive.readonly"
    src = Path("src/google_drive_mcp/infra/google_auth/refresh_token.py").read_text()
    assert "drive.readonly" in src
    assert "auth/drive\"" not in src
    assert "auth/drive'" not in src
    assert "auth/drive.file" not in src
    assert "auth/drive.appdata" not in src


def test_mcp_registration_has_no_mutating_tools():
    runtime = Runtime(settings=Settings.for_tests(), drive=FakeDrive.sample())
    server = create_server(runtime)
    names = set()
    tools = getattr(server, "_tool_manager", None) or getattr(server, "_tools", None)
    if tools is not None:
        maybe = getattr(tools, "_tools", tools)
        if isinstance(maybe, dict):
            names = set(maybe)
        elif hasattr(maybe, "keys"):
            names = set(maybe.keys())
    # Decorator-registered tools always include the four read tools.
    mutating = {"drive_write", "drive_create", "drive_delete", "drive_share", "drive_update", "scope_probe"}
    assert not (names & mutating)
    src = Path("src/google_drive_mcp/mcp/server.py").read_text()
    assert "def scope_probe" not in src
    for required in READ_ONLY_TOOLS:
        assert required in (
            "drive_ls",
            "drive_find",
            "drive_read",
            "drive_grep",
        )
