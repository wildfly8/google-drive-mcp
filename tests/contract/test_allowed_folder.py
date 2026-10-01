"""Deployment folder allow-list: only that folder and descendants are in scope.

Nothing outside it is readable or listable, not even metadata, and the server
fails closed when no allow-list folder is configured.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
from google_drive_mcp.access_control.allowed_folder import check_allowed_folder
from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.domain.retrieval_scope import RetrievalScope, apply_allowed_folder
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.google_drive.list import walk_files
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.tools import handle_tool
from google_drive_mcp.retrieval.ls import drive_ls


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


@pytest.mark.parametrize("allowed", ["", "   "])
def test_unset_allow_list_refuses_every_call_without_drive_io(
    fake_drive: FakeDrive, authz, allowed: str
):
    settings = Settings(
        mcp_auth_token=SecretStr("test-token"),
        mcp_principal_id="deployment-1",
        drive_allowed_folder_id=allowed,
    )
    runtime = Runtime(settings=settings, drive=fake_drive)
    fake_drive.reset_counters()
    calls = [
        ("drive_ls", {}),
        ("drive_ls", {"folder_id": "root"}),
        ("drive_ls", {"folder_id": "folder-a"}),
        ("drive_find", {}),
        ("drive_find", {"folder_id": "root"}),
        ("drive_grep", {"pattern": "secret"}),
        ("drive_grep", {"pattern": "secret", "file_ids": ["outside-doc"]}),
        ("drive_read", {"file_id": "outside-doc"}),
        ("drive_read", {"file_id": "nested-doc"}),
    ]
    for name, arguments in calls:
        result = handle_tool(runtime, name, arguments, authz)
        assert result["category"] == "AUTHORIZATION_ERROR", (name, arguments)
    assert fake_drive.metadata_get_count == 0
    assert fake_drive.list_count == 0
    assert fake_drive.content_count == 0


def _record_drive(fake_drive: FakeDrive) -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []
    for name in ("get_metadata", "list_children", "list_subfolders", "parent_lookup"):
        original = getattr(fake_drive, name)

        def recorded(*args, _name=name, _original=original, **kwargs):
            target = args[0] if args else kwargs.get("folder_id")
            calls.append((_name, tuple(target) if isinstance(target, list) else target))
            return _original(*args, **kwargs)

        setattr(fake_drive, name, recorded)
    return calls


def test_outside_folders_cannot_even_be_listed(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    calls = _record_drive(fake_drive)
    for name, arguments in [
        ("drive_ls", {"folder_id": "root"}),
        ("drive_find", {"folder_id": "root"}),
        ("drive_find", {"folder_id": "root", "name_pattern": "Other"}),
        ("drive_grep", {"pattern": "secret", "folder_id": "root"}),
    ]:
        result = handle_tool(runtime, name, arguments, authz)
        assert result["category"] == "AUTHORIZATION_ERROR", (name, arguments)
        assert "Other" not in str(result)
        assert "outside-doc" not in str(result)
    assert fake_drive.content_count == 0
    # Only the allowed folder's own tree is listed, and only the named id is looked up.
    assert not [c for c in calls if c[0] in ("list_children", "parent_lookup")]
    assert {c[1] for c in calls if c[0] == "list_subfolders"} == {("folder-a",)}
    assert {c[1] for c in calls if c[0] == "get_metadata"} == {"root"}


def test_outside_missing_and_ungranted_ids_take_the_same_drive_calls(
    fake_drive: FakeDrive, authz
):
    runtime = _runtime(fake_drive)
    original = fake_drive.get_metadata

    def get_metadata(file_id: str):
        if file_id == "ungranted-doc":
            raise GoogleApiError(403)
        return original(file_id)

    fake_drive.get_metadata = get_metadata  # type: ignore[method-assign]
    shapes = []
    for file_id in ("outside-doc", "no-such-id", "ungranted-doc"):
        calls = _record_drive(fake_drive)
        result = handle_tool(runtime, "drive_read", {"file_id": file_id}, authz)
        result.pop("request_id")
        shape = [(name, "*" if name == "get_metadata" else target) for name, target in calls]
        shapes.append((shape, result))
    assert shapes[0] == shapes[1] == shapes[2]
    assert shapes[0][1]["category"] == "AUTHORIZATION_ERROR"


def test_deep_file_inside_allowed_folder_is_still_readable(fake_drive: FakeDrive, authz):
    fake_drive.add(FakeFile(id="sub-1", name="sub", mime_type=FOLDER_MIME, parents=["folder-a"]))
    fake_drive.add(FakeFile(id="sub-2", name="deeper", mime_type=FOLDER_MIME, parents=["sub-1"]))
    fake_drive.add(
        FakeFile(
            id="deep-doc",
            name="Deep",
            mime_type=DOC_MIME,
            parents=["sub-2"],
            content="deep kb text",
        )
    )
    runtime = _runtime(fake_drive)
    read = handle_tool(runtime, "drive_read", {"file_id": "deep-doc"}, authz)
    listed = handle_tool(runtime, "drive_ls", {"folder_id": "sub-2"}, authz)
    grepped = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "deep kb", "folder_id": "sub-1", "file_ids": ["deep-doc"]},
        authz,
    )
    assert read["content"] == "deep kb text"
    assert [c["id"] for c in listed["children"]] == ["deep-doc"]
    assert [m["file_id"] for m in grepped["matches"]] == ["deep-doc"]


def test_outside_and_missing_ids_get_the_same_reply(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    for name, key in [("drive_read", "file_id"), ("drive_ls", "folder_id")]:
        outside = handle_tool(runtime, name, {key: "outside-doc"}, authz)
        missing = handle_tool(runtime, name, {key: "no-such-id"}, authz)
        outside.pop("request_id")
        missing.pop("request_id")
        assert outside == missing
        assert outside["category"] == "AUTHORIZATION_ERROR"


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("drive_ls", {"file_id": "nested-doc"}),
        ("drive_ls", {"file_ids": ["nested-doc"]}),
        ("drive_find", {"file_id": "nested-doc"}),
        ("drive_find", {"file_ids": ["nested-doc"]}),
        ("drive_grep", {"pattern": "secret", "file_id": "nested-doc"}),
        ("drive_read", {"file_id": "nested-doc", "folder_id": "folder-a"}),
    ],
)
def test_arguments_a_tool_does_not_take_are_refused(
    fake_drive: FakeDrive, authz, name: str, arguments: dict
):
    runtime = _runtime(fake_drive)
    fake_drive.reset_counters()
    result = handle_tool(runtime, name, arguments, authz)
    assert result["category"] == "INVALID_ARGUMENT"
    assert fake_drive.list_count == 0
    assert fake_drive.content_count == 0


def test_blank_file_ids_do_not_skip_the_allow_list_rewrite():
    arguments: dict = {"file_ids": ["", "  "], "file_id": " "}
    apply_allowed_folder(arguments, "folder-a")
    assert arguments["folder_id"] == "folder-a"


def test_stale_listing_entry_outside_the_folder_is_dropped(fake_drive: FakeDrive, authz):
    listed = fake_drive.list_children

    def over_broad(folder_id, budget=None, **kwargs):
        children = listed(folder_id, budget, **kwargs)
        if folder_id == "folder-a":
            children.append(fake_drive.files["outside-doc"])
        return children

    fake_drive.list_children = over_broad  # type: ignore[method-assign]
    runtime = _runtime(fake_drive)
    listed_ids = {c["id"] for c in handle_tool(runtime, "drive_ls", {}, authz)["children"]}
    found = handle_tool(runtime, "drive_find", {}, authz)
    found_ids = {c["file"]["id"] for c in found["candidates"]}
    grepped = handle_tool(runtime, "drive_grep", {"pattern": "secret other"}, authz)
    assert "nested-doc" in listed_ids
    assert "outside-doc" not in listed_ids
    assert "outside-doc" not in found_ids
    assert grepped["matches"] == []


def test_retrieval_never_lists_without_a_folder(fake_drive: FakeDrive):
    with pytest.raises(DomainError) as listed:
        drive_ls(fake_drive)
    with pytest.raises(DomainError) as walked:
        walk_files(fake_drive, RetrievalScope.default_whole_grant_scope(), Budget())
    assert listed.value.error.category == ErrorCategory.AUTHORIZATION_ERROR
    assert walked.value.error.category == ErrorCategory.AUTHORIZATION_ERROR
    assert fake_drive.list_count == 0


@pytest.mark.parametrize("value", ["", "  ", "root", "ROOT", "appDataFolder", "kb/sub", "a b"])
def test_startup_requires_one_real_allow_list_folder(value: str):
    settings = Settings(
        mcp_auth_token=SecretStr("test-token"),
        mcp_principal_id="deployment-1",
        drive_allowed_folder_id=value,
    )
    with pytest.raises(ValueError):
        settings.require_allowed_folder()


def test_startup_accepts_the_kb_folder_id():
    settings = Settings(
        mcp_auth_token=SecretStr("test-token"),
        mcp_principal_id="deployment-1",
        drive_allowed_folder_id="1kbFolderIdUsedOnlyInTests000000",
    )
    assert settings.require_allowed_folder() == "1kbFolderIdUsedOnlyInTests000000"


@pytest.mark.parametrize(
    ("folder_id", "problem"),
    [
        ("root", "root"),
        ("nested-doc", "not a folder"),
        ("no-such-folder", "could not be read"),
        ("trashed-folder", "trash"),
    ],
)
def test_startup_drive_check_refuses_anything_but_one_folder(
    fake_drive: FakeDrive, folder_id: str, problem: str
):
    fake_drive.add(
        FakeFile(
            id="trashed-folder",
            name="old",
            mime_type=FOLDER_MIME,
            parents=["root"],
            trashed=True,
        )
    )
    with pytest.raises(ValueError, match=problem):
        check_allowed_folder(fake_drive, folder_id)


def test_startup_drive_check_refuses_the_real_root_id(fake_drive: FakeDrive):
    original = fake_drive.get_metadata

    def get_metadata(file_id: str):
        meta = original("root" if file_id in {"root", "0ARealRootId"} else file_id)
        return {**meta, "id": "0ARealRootId"} if file_id in {"root", "0ARealRootId"} else meta

    fake_drive.get_metadata = get_metadata  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="root"):
        check_allowed_folder(fake_drive, "0ARealRootId")
    check_allowed_folder(fake_drive, "folder-a")


def test_server_refuses_to_start_when_drive_check_fails(monkeypatch):
    from google_drive_mcp.mcp import server

    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token-long-enough-to-sign-jwts-0001")
    monkeypatch.setenv("DRIVE_ALLOWED_FOLDER_ID", "1kbFolderIdUsedOnlyInTests000000")

    def refuse(_settings):
        raise ValueError("DRIVE_ALLOWED_FOLDER_ID is a Drive root, not one folder under it.")

    monkeypatch.setattr(server, "check_allowed_folder_in_drive", refuse)
    with pytest.raises(SystemExit) as stopped:
        server.main()
    assert "Drive root" in str(stopped.value)


def test_server_refuses_to_start_without_allow_list(monkeypatch):
    from google_drive_mcp.mcp import server

    monkeypatch.delenv("DRIVE_ALLOWED_FOLDER_ID", raising=False)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    with pytest.raises(SystemExit) as stopped:
        server.main()
    assert "DRIVE_ALLOWED_FOLDER_ID" in str(stopped.value)


@pytest.mark.parametrize("value", [None, "", "root"])
def test_runtime_from_env_requires_allow_list(monkeypatch, value):
    from google_drive_mcp.mcp.server import build_runtime

    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    if value is None:
        monkeypatch.delenv("DRIVE_ALLOWED_FOLDER_ID", raising=False)
    else:
        monkeypatch.setenv("DRIVE_ALLOWED_FOLDER_ID", value)
    with pytest.raises(ValueError):
        build_runtime()


def test_default_folder_setting_no_longer_exists():
    with pytest.raises(ValidationError):
        Settings(
            mcp_auth_token=SecretStr("test-token"),
            mcp_principal_id="deployment-1",
            drive_default_folder_id="folder-a",
        )


def test_named_folder_outside_allow_list_is_authorization_error(fake_drive: FakeDrive, authz):
    runtime = _runtime(fake_drive)
    found = handle_tool(runtime, "drive_find", {"folder_id": "root"}, authz)
    assert found["category"] == "AUTHORIZATION_ERROR"
    grepped = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "secret", "folder_id": "root"},
        authz,
    )
    assert grepped["category"] == "AUTHORIZATION_ERROR"


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


@pytest.mark.parametrize("secret", ["", "short-password", " " * 40])
def test_server_refuses_to_start_with_a_guessable_signing_key(monkeypatch, secret: str):
    from google_drive_mcp.mcp import server

    monkeypatch.setenv("DRIVE_ALLOWED_FOLDER_ID", "1kbFolderIdUsedOnlyInTests000000")
    monkeypatch.setenv("MCP_AUTH_TOKEN", secret)
    monkeypatch.delenv("MCP_OAUTH_SIGNING_KEY", raising=False)
    monkeypatch.setattr(server, "check_allowed_folder_in_drive", lambda _settings: None)
    with pytest.raises(SystemExit) as stopped:
        server.main()
    assert "at least 32 characters" in str(stopped.value)
