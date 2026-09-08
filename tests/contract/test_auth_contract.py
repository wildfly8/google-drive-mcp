"""Access Control US1 contract tests."""

from __future__ import annotations

from fakes.fake_drive import FakeDrive
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.tools import handle_tool


def _call(runtime: Runtime, arguments: dict, authorization: str | None) -> dict:
    return handle_tool(runtime, "scope_probe", arguments, authorization)


def test_missing_bearer_is_authentication_error_and_no_drive_io(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    result = _call(runtime, {"folder_id": "folder-a", "file_ids": ["nested-doc"]}, None)
    assert result["status"] == "ERROR"
    assert result["category"] == "AUTHENTICATION_ERROR"
    assert fake_drive.metadata_get_count == 0
    assert fake_drive.content_count == 0


def test_invalid_bearer_is_authentication_error(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    result = _call(
        runtime,
        {"folder_id": "folder-a", "file_ids": ["nested-doc"]},
        "Bearer wrong-token",
    )
    assert result["category"] == "AUTHENTICATION_ERROR"
    assert fake_drive.metadata_get_count == 0
    assert fake_drive.content_count == 0


def test_google_miss_is_file_not_found_without_metadata(runtime, fake_drive: FakeDrive):
    fake_drive.reset_counters()
    result = _call(
        runtime,
        {"file_id": "missing-id"},
        "Bearer test-token",
    )
    assert result["category"] == "FILE_NOT_FOUND"
    assert "name" not in result
    assert "content" not in result
    assert "Notes" not in result.get("message", "")
    assert fake_drive.content_count == 0


def test_folder_and_granted_file_outside_folder_is_authorization_error(
    runtime, fake_drive: FakeDrive
):
    fake_drive.reset_counters()
    result = _call(
        runtime,
        {"folder_id": "folder-a", "file_ids": ["outside-doc"]},
        "Bearer test-token",
    )
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count >= 1


def test_file_id_only_google_miss_is_never_authorization_error(runtime, fake_drive: FakeDrive):
    result = _call(runtime, {"file_id": "does-not-exist"}, "Bearer test-token")
    assert result["category"] == "FILE_NOT_FOUND"
    assert result["category"] != "AUTHORIZATION_ERROR"
