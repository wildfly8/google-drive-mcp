"""Deployment folder allow-list: only that folder and descendants are in scope."""

from __future__ import annotations

from pydantic import SecretStr

from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.tools import handle_tool


def _runtime(fake_drive: FakeDrive) -> Runtime:
    settings = Settings(
        mcp_auth_token=SecretStr("test-token"),
        mcp_principal_id="deployment-1",
        drive_allowed_folder_id="folder-a",
    )
    return Runtime(settings=settings, drive=fake_drive)


def test_omitted_ls_lists_allowed_folder_not_root(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    result = handle_tool(runtime, "drive_ls", {}, authz)
    ids = {c["id"] for c in result["children"]}
    assert "nested-doc" in ids
    assert "folder-a" not in ids
    assert "outside-doc" not in ids


def test_read_outside_allowed_folder_is_authorization_error(fake_drive: FakeDrive, authz):
    fake_drive.reset_counters()
    runtime = _runtime(fake_drive)
    result = handle_tool(
        runtime, "drive_read", {"file_id": "outside-doc"}, authz
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.content_count == 0
    assert "secret other" not in str(result).lower()


def test_read_inside_allowed_folder_still_works(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    result = handle_tool(
        runtime, "drive_read", {"file_id": "nested-doc"}, authz
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    assert "idempotency" in (result.get("content") or "")


def test_ls_unrelated_folder_is_authorization_error(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "root"}, authz
    )
    assert result["category"] == "AUTHORIZATION_ERROR"


def test_find_omitted_folder_stays_inside_allow_list(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    result = handle_tool(runtime, "drive_find", {}, authz)
    names = {(c.get("file") or {}).get("name") for c in result.get("candidates") or []}
    assert "Other" not in names
    assert "Notes" in names


def test_grep_outside_file_is_authorization_error(fake_drive: FakeDrive, authz):
    fake_drive.reset_counters()
    runtime = _runtime(fake_drive)
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "secret", "file_ids": ["outside-doc"]},
        authz,
    )
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.content_count == 0
