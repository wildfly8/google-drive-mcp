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


def test_google_miss_is_authorization_error_without_metadata(runtime, fake_drive: FakeDrive, authz):
    fake_drive.reset_counters()
    result = _call(
        runtime,
        {"file_id": "missing-id"},
        authz,
    )
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert "name" not in result
    assert "content" not in result
    assert "Notes" not in result.get("message", "")
    assert fake_drive.content_count == 0


def test_folder_and_granted_file_outside_folder_is_authorization_error(
    runtime, fake_drive: FakeDrive, authz
):
    fake_drive.reset_counters()
    result = _call(
        runtime,
        {"folder_id": "folder-a", "file_ids": ["outside-doc"]},
        authz,
    )
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.content_count == 0
    assert fake_drive.metadata_get_count >= 1


def test_google_miss_and_outside_allow_list_reply_the_same(fake_drive: FakeDrive, authz):
    from google_drive_mcp.infra.config import Settings

    settings = Settings.for_tests().model_copy(update={"drive_allowed_folder_id": "folder-a"})
    runtime = Runtime(settings=settings, drive=fake_drive)
    missing = _call(runtime, {"file_id": "does-not-exist"}, authz)
    outside = _call(runtime, {"file_id": "outside-doc"}, authz)
    missing.pop("request_id")
    outside.pop("request_id")
    assert missing == outside
    assert outside["category"] == "AUTHORIZATION_ERROR"
