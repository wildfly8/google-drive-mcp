"""Temporary kb write tools: off by default, kb-only, trash instead of delete."""

from __future__ import annotations

import pytest

from fakes.fake_drive import FOLDER_MIME, SHEET_MIME, FakeDrive, FakeFile
from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.kb_write import NO_WRITE_GRANT
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import create_server
from google_drive_mcp.mcp.tool_schema import SERVER_INSTRUCTIONS, WRITE_INSTRUCTIONS
from google_drive_mcp.mcp.tools import handle_tool


def _runtime(fake_drive: FakeDrive, *, enabled: bool = True) -> Runtime:
    settings = Settings.for_tests().model_copy(
        update={"drive_allowed_folder_id": "folder-a", "drive_write_enabled": enabled}
    )
    return Runtime(settings=settings, drive=fake_drive, writer=fake_drive)


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("drive_write", {"file_id": "nested-doc", "content": "x"}),
        ("drive_trash", {"file_id": "nested-doc"}),
    ],
)
def test_write_tools_are_off_by_default(fake_drive: FakeDrive, authz, name, arguments):
    assert Settings.for_tests().drive_write_enabled is False
    result = handle_tool(_runtime(fake_drive, enabled=False), name, arguments, authz)
    assert result["category"] == "INVALID_ARGUMENT"
    assert fake_drive.write_count == 0


def test_write_replaces_text_of_a_kb_file(fake_drive: FakeDrive, authz):
    fake_drive.add(
        FakeFile(
            id="notes-md",
            name="notes.mdx",
            mime_type="application/octet-stream",
            parents=["folder-a"],
            content="old",
        )
    )
    runtime = _runtime(fake_drive)
    result = handle_tool(
        runtime, "drive_write", {"file_id": "notes-md", "content": "new body\n"}, authz
    )
    assert result["status"] == "COMPLETE"
    assert result["bytes_written"] == len("new body\n")
    assert fake_drive.files["notes-md"].content == "new body\n"
    assert fake_drive.last_upload_mime == "application/octet-stream"
    read = handle_tool(runtime, "drive_read", {"file_id": "notes-md"}, authz)
    assert read["content"] == "new body\n"


def test_write_uploads_plain_text_into_a_google_doc(fake_drive: FakeDrive, authz):
    result = handle_tool(
        _runtime(fake_drive), "drive_write", {"file_id": "nested-doc", "content": "doc"}, authz
    )
    assert result["status"] == "COMPLETE"
    assert fake_drive.last_upload_mime == "text/plain"


def test_trash_moves_a_kb_file_to_the_trash(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    result = handle_tool(runtime, "drive_trash", {"file_id": "text-file"}, authz)
    assert result == {
        "status": "COMPLETE",
        "file_id": "text-file",
        "file_name": "readme.txt",
        "trashed": True,
        "source_url": "drive:text-file",
    }
    assert fake_drive.files["text-file"].trashed is True
    assert "text-file" in fake_drive.files  # trashed, not deleted
    again = handle_tool(runtime, "drive_trash", {"file_id": "text-file"}, authz)
    assert again["status"] == "COMPLETE"
    assert fake_drive.write_count == 1


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("drive_write", {"file_id": "outside-doc", "content": "x"}),
        ("drive_trash", {"file_id": "outside-doc"}),
        ("drive_write", {"file_id": "no-such-id", "content": "x"}),
        ("drive_trash", {"file_id": "root"}),
    ],
)
def test_nothing_outside_kb_is_written_or_trashed(fake_drive: FakeDrive, authz, name, arguments):
    result = handle_tool(_runtime(fake_drive), name, arguments, authz)
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.write_count == 0
    assert fake_drive.files["outside-doc"].content == "secret other folder text"
    assert fake_drive.files["outside-doc"].trashed is False


def test_write_tools_refuse_without_an_allow_list(fake_drive: FakeDrive, authz):
    settings = Settings.for_tests().model_copy(
        update={"drive_allowed_folder_id": "", "drive_write_enabled": True}
    )
    runtime = Runtime(settings=settings, drive=fake_drive, writer=fake_drive)
    result = handle_tool(runtime, "drive_trash", {"file_id": "nested-doc"}, authz)
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.write_count == 0


@pytest.mark.parametrize(
    ("name", "arguments", "category"),
    [
        ("drive_trash", {"file_id": "folder-a"}, "INVALID_ARGUMENT"),
        ("drive_trash", {"file_id": "sub-folder"}, "INVALID_ARGUMENT"),
        ("drive_write", {"file_id": "sub-folder", "content": "x"}, "UNSUPPORTED_MIME_TYPE"),
        ("drive_write", {"file_id": "nested-sheet", "content": "x"}, "UNSUPPORTED_MIME_TYPE"),
        ("drive_write", {"file_id": "binary-file", "content": "x"}, "UNSUPPORTED_MIME_TYPE"),
        ("drive_write", {"file_id": "nested-doc"}, "INVALID_ARGUMENT"),
        ("drive_write", {"file_id": "nested-doc", "content": 5}, "INVALID_ARGUMENT"),
        (
            "drive_write",
            {"file_id": "nested-doc", "content": "x", "folder_id": "folder-a"},
            "INVALID_ARGUMENT",
        ),
        ("drive_trash", {"file_id": "nested-doc", "content": "x"}, "INVALID_ARGUMENT"),
    ],
)
def test_write_tools_refuse_folders_other_types_and_bad_arguments(
    fake_drive: FakeDrive, authz, name, arguments, category
):
    fake_drive.add(
        FakeFile(id="sub-folder", name="sub", mime_type=FOLDER_MIME, parents=["folder-a"])
    )
    result = handle_tool(_runtime(fake_drive), name, arguments, authz)
    assert result["category"] == category
    assert fake_drive.write_count == 0
    assert fake_drive.files["nested-sheet"].mime_type == SHEET_MIME


def test_write_too_large_is_invalid(fake_drive: FakeDrive, authz):
    big = "x" * 20_000_001
    result = handle_tool(
        _runtime(fake_drive), "drive_write", {"file_id": "nested-doc", "content": big}, authz
    )
    assert result["category"] == "INVALID_ARGUMENT"
    assert fake_drive.write_count == 0


@pytest.mark.parametrize("status", [401, 403])
def test_google_refusing_the_write_says_the_login_needs_the_drive_scope(
    fake_drive: FakeDrive, authz, status
):
    def refuse(*_args, **_kwargs):
        raise GoogleApiError(status)

    fake_drive.replace_text = refuse  # type: ignore[method-assign]
    fake_drive.trash = refuse  # type: ignore[method-assign]
    runtime = _runtime(fake_drive)
    for name, arguments in [
        ("drive_write", {"file_id": "nested-doc", "content": "x"}),
        ("drive_trash", {"file_id": "nested-doc"}),
    ]:
        result = handle_tool(runtime, name, arguments, authz)
        assert result["category"] == "AUTHORIZATION_ERROR"
        assert result["message"] == NO_WRITE_GRANT


def test_missing_bearer_cannot_write(fake_drive: FakeDrive):
    result = handle_tool(
        _runtime(fake_drive), "drive_trash", {"file_id": "nested-doc"}, "Bearer wrong"
    )
    assert result["category"] == "AUTHENTICATION_ERROR"
    assert fake_drive.write_count == 0


async def test_server_registers_write_tools_only_when_enabled(fake_drive: FakeDrive):
    off = create_server(_runtime(fake_drive, enabled=False))
    on = create_server(_runtime(fake_drive))
    off_names = {tool.name for tool in await off.list_tools()}
    on_tools = {tool.name: tool for tool in await on.list_tools()}
    assert not off_names & {"drive_write", "drive_trash"}
    assert {"drive_write", "drive_trash"} <= set(on_tools)
    for name in ("drive_write", "drive_trash"):
        annotations = on_tools[name].annotations
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is True
        assert "explicitly asks" in on_tools[name].description
    assert "drive_trash" in WRITE_INSTRUCTIONS
    assert "No write/delete/share tools exist" in SERVER_INSTRUCTIONS
    assert "No write/delete/share tools exist" not in WRITE_INSTRUCTIONS
