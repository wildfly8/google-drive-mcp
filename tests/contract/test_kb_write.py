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
        ("drive_replace", {"file_id": "nested-doc", "pattern": "alpha"}),
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
    assert not off_names & {"drive_write", "drive_replace", "drive_trash"}
    assert {"drive_write", "drive_replace", "drive_trash"} <= set(on_tools)
    for name in ("drive_write", "drive_replace", "drive_trash"):
        annotations = on_tools[name].annotations
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is True
        assert "explicitly asks" in on_tools[name].description
    assert "drive_trash" in WRITE_INSTRUCTIONS
    assert "No write/delete/share tools exist" in SERVER_INSTRUCTIONS
    assert "No write/delete/share tools exist" not in WRITE_INSTRUCTIONS


def _add_text(fake_drive: FakeDrive, content: str | bytes, name: str = "chat.mdx") -> str:
    fake_drive.add(
        FakeFile(
            id="chat-export",
            name=name,
            mime_type="application/octet-stream",
            parents=["folder-a"],
            content=content,
        )
    )
    return "chat-export"


def _replace(runtime: Runtime, authz: str, **arguments) -> dict:
    return handle_tool(runtime, "drive_replace", arguments, authz)


def test_replace_removes_each_match_and_keeps_every_other_byte(fake_drive: FakeDrive, authz):
    original = "Résumé\r\nGlendora | 626-555-0100 | café ✓\r\nagain 626-555-0100\r\n"
    file_id = _add_text(fake_drive, original)
    result = _replace(
        _runtime(fake_drive), authz, file_id=file_id, pattern="626-555-0100", max_replacements=2
    )
    expected = original.replace("626-555-0100", "")
    assert result["status"] == "COMPLETE"
    assert result["replacements"] == 2
    assert fake_drive.files[file_id].content == expected
    assert result["bytes_before"] == len(original.encode("utf-8"))
    assert result["bytes_after"] == len(expected.encode("utf-8"))
    assert fake_drive.last_upload_mime == "application/octet-stream"


def test_replace_accepts_the_arguments_the_server_sends(fake_drive: FakeDrive, authz):
    file_id = _add_text(fake_drive, "call 626-555-0100\n")
    result = _replace(
        _runtime(fake_drive),
        authz,
        file_id=file_id,
        pattern="626-555-0100",
        replacement="",
        regex=False,
        case_sensitive=True,
        max_replacements=1,
    )
    assert result["replacements"] == 1
    assert fake_drive.files[file_id].content == "call \n"


def test_replace_with_no_match_writes_nothing(fake_drive: FakeDrive, authz):
    file_id = _add_text(fake_drive, "nothing here\n")
    result = _replace(_runtime(fake_drive), authz, file_id=file_id, pattern="626-555-0100")
    assert result == {
        "status": "COMPLETE",
        "file_id": file_id,
        "file_name": "chat.mdx",
        "mime_type": "application/octet-stream",
        "replacements": 0,
        "source_url": f"drive:{file_id}",
    }
    assert fake_drive.write_count == 0


def test_replace_over_the_limit_writes_nothing(fake_drive: FakeDrive, authz):
    file_id = _add_text(fake_drive, "626-555-0100 and 626-555-0100\n")
    result = _replace(
        _runtime(fake_drive), authz, file_id=file_id, pattern="626-555-0100", max_replacements=1
    )
    assert result["category"] == "INVALID_ARGUMENT"
    assert "2 matches" in result["message"]
    assert fake_drive.write_count == 0
    assert fake_drive.files[file_id].content == "626-555-0100 and 626-555-0100\n"


def test_replace_regex_and_case_options_with_a_literal_replacement(fake_drive: FakeDrive, authz):
    file_id = _add_text(fake_drive, "Phone: 626.555.0100\nPHONE: 626-555-0100\n")
    runtime = _runtime(fake_drive)
    result = _replace(
        runtime,
        authz,
        file_id=file_id,
        pattern=r"phone: 626\D555\D0100",
        replacement=r"\g<0> [\1]",
        regex=True,
        case_sensitive=False,
    )
    assert result["replacements"] == 2
    assert fake_drive.files[file_id].content == "\\g<0> [\\1]\n\\g<0> [\\1]\n"


def test_replace_refuses_a_pattern_that_matches_empty_text(fake_drive: FakeDrive, authz):
    file_id = _add_text(fake_drive, "abc\n")
    result = _replace(_runtime(fake_drive), authz, file_id=file_id, pattern=r"\d*", regex=True)
    assert result["category"] == "INVALID_ARGUMENT"
    assert fake_drive.write_count == 0


def test_replace_refuses_text_that_is_not_utf8(fake_drive: FakeDrive, authz):
    file_id = _add_text(fake_drive, b"\xff\xfe 626-555-0100\n")
    result = _replace(_runtime(fake_drive), authz, file_id=file_id, pattern="626-555-0100")
    assert result["category"] == "UNSUPPORTED_MIME_TYPE"
    assert fake_drive.write_count == 0


def test_replace_refuses_files_it_cannot_read_whole(fake_drive: FakeDrive, authz, monkeypatch):
    from google_drive_mcp import kb_write

    monkeypatch.setattr(kb_write, "MAX_EXPORT_SIZE", 10)
    file_id = _add_text(fake_drive, "626-555-0100 is longer than ten bytes\n")
    result = _replace(_runtime(fake_drive), authz, file_id=file_id, pattern="626-555-0100")
    assert result["category"] == "RESOURCE_LIMIT"
    assert fake_drive.write_count == 0


def test_replace_in_a_google_doc_uploads_plain_text(fake_drive: FakeDrive, authz):
    result = _replace(_runtime(fake_drive), authz, file_id="nested-doc", pattern="alpha ")
    assert result["replacements"] == 1
    assert fake_drive.last_upload_mime == "text/plain"
    assert fake_drive.files["nested-doc"].content == "idempotency\nbeta idempotency extra"


@pytest.mark.parametrize("file_id", ["outside-doc", "no-such-id", "root"])
def test_replace_never_touches_anything_outside_kb(fake_drive: FakeDrive, authz, file_id):
    result = _replace(_runtime(fake_drive), authz, file_id=file_id, pattern="secret")
    assert result["category"] == "AUTHORIZATION_ERROR"
    assert fake_drive.write_count == 0
    assert fake_drive.files["outside-doc"].content == "secret other folder text"


@pytest.mark.parametrize(
    ("arguments", "category"),
    [
        ({"file_id": "chat-export", "pattern": ""}, "INVALID_ARGUMENT"),
        ({"file_id": "chat-export", "pattern": 5}, "INVALID_ARGUMENT"),
        ({"file_id": "chat-export", "pattern": "x", "replacement": 5}, "INVALID_ARGUMENT"),
        ({"file_id": "chat-export", "pattern": "x", "max_replacements": 0}, "INVALID_ARGUMENT"),
        ({"file_id": "chat-export", "pattern": "x", "max_replacements": True}, "INVALID_ARGUMENT"),
        ({"file_id": "chat-export", "pattern": "x", "regex": "yes"}, "INVALID_ARGUMENT"),
        ({"file_id": "chat-export", "pattern": "(", "regex": True}, "INVALID_ARGUMENT"),
        ({"file_id": "chat-export", "pattern": "x", "folder_id": "folder-a"}, "INVALID_ARGUMENT"),
        ({"file_id": "sub-folder", "pattern": "x"}, "UNSUPPORTED_MIME_TYPE"),
        ({"file_id": "nested-sheet", "pattern": "x"}, "UNSUPPORTED_MIME_TYPE"),
        ({"file_id": "binary-file", "pattern": "x"}, "UNSUPPORTED_MIME_TYPE"),
    ],
)
def test_replace_refuses_bad_arguments_and_file_types(
    fake_drive: FakeDrive, authz, arguments, category
):
    _add_text(fake_drive, "x marks the spot\n")
    fake_drive.add(
        FakeFile(id="sub-folder", name="sub", mime_type=FOLDER_MIME, parents=["folder-a"])
    )
    result = handle_tool(_runtime(fake_drive), "drive_replace", arguments, authz)
    assert result["category"] == category
    assert fake_drive.write_count == 0
