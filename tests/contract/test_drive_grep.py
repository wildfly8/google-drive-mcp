"""drive_grep contract tests including mixed-folder FR-037."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_grep_idempotency_returns_match_with_provenance(runtime):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        "Bearer test-token",
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    assert result["matches"]
    match = result["matches"][0]
    assert match["file_id"]
    assert match["matched_text"]
    assert "location" in match
    assert match["source_url"]
    assert match["retrieved_at"]
    assert match["pattern"] == "idempotency"


def test_grep_missing_phrase_is_empty(runtime):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "no-such-phrase-xyz", "file_ids": ["nested-doc"]},
        "Bearer test-token",
    )
    assert result["status"] == "EMPTY"
    assert result["matches"] == []


def test_grep_twice_identical(runtime):
    args = {"pattern": "idempotency", "file_ids": ["nested-doc"]}
    first = handle_tool(runtime, "drive_grep", args, "Bearer test-token")
    second = handle_tool(runtime, "drive_grep", args, "Bearer test-token")
    assert first["matches"] == second["matches"]


def test_literal_vs_regex_and_case_flag(runtime):
    literal = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "Idempotency", "file_ids": ["nested-doc"], "regex": False},
        "Bearer test-token",
    )
    assert literal["status"] == "EMPTY"
    insensitive = handle_tool(
        runtime,
        "drive_grep",
        {
            "pattern": "Idempotency",
            "file_ids": ["nested-doc"],
            "regex": False,
            "case_sensitive": False,
        },
        "Bearer test-token",
    )
    assert insensitive["matches"]
    regex = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency|widgets", "file_ids": ["nested-doc"], "regex": True},
        "Bearer test-token",
    )
    assert regex["matches"]
    escaped = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency|widgets", "file_ids": ["nested-doc"], "regex": False},
        "Bearer test-token",
    )
    assert escaped["status"] == "EMPTY"


def test_slides_grep_uses_character_window_not_lines(runtime, fake_drive):
    fake_drive.update_content(
        "nested-slide",
        "intro line\n\nQuarterly update idempotency extra context",
    )
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["nested-slide"]},
        "Bearer test-token",
    )
    assert result["matches"]
    location = result["matches"][0]["location"]
    assert "offset" in location
    assert "line" not in location


def test_mixed_folder_skips_unsupported_partial(runtime):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "unsupported_skipped"
    assert result["matches"]


def test_grep_binary_by_id_is_classified_error(runtime):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["binary-file"]},
        "Bearer test-token",
    )
    assert result["status"] == "ERROR"
    assert result["category"] in {"UNSUPPORTED_MIME_TYPE", "FILE_NOT_EXPORTABLE"}


def test_rate_limited_walk_with_only_unsupported_is_partial():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.infra.config import Settings
    from google_drive_mcp.mcp.middleware import Runtime
    from google_drive_mcp.mcp.tools import handle_tool

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(
        FakeFile(
            id="bin-a",
            name="photo.bin",
            mime_type="application/octet-stream",
            parents=["top"],
            content=b"\x00",
        )
    )
    drive.add(FakeFile(id="nested", name="Nested", mime_type=FOLDER_MIME, parents=["top"]))
    drive.add(
        FakeFile(
            id="hidden-doc",
            name="Notes",
            mime_type=DOC_MIME,
            parents=["nested"],
            content="idempotency",
        )
    )
    drive.rate_limit_lists_after = 1
    runtime = Runtime(Settings.for_tests(), drive=drive)
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "top"},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "UNSUPPORTED_MIME_TYPE"


def test_max_files_on_binaries_is_partial_not_unsupported():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(
        FakeFile(
            id="bin-a",
            name="a.bin",
            mime_type="application/octet-stream",
            parents=["top"],
            content=b"\x00",
        )
    )
    drive.add(
        FakeFile(
            id="bin-b",
            name="b.bin",
            mime_type="application/octet-stream",
            parents=["top"],
            content=b"\x01",
        )
    )
    drive.add(
        FakeFile(
            id="later-doc",
            name="Notes",
            mime_type=DOC_MIME,
            parents=["top"],
            content="idempotency",
        )
    )
    result = drive_grep(
        drive,
        pattern="idempotency",
        folder_id="top",
        budget=Budget(max_files=2),
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_files"
    assert result.get("category") != "UNSUPPORTED_MIME_TYPE"


def test_folders_are_not_unsupported_skips():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.infra.config import Settings
    from google_drive_mcp.mcp.middleware import Runtime
    from google_drive_mcp.mcp.tools import handle_tool

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(FakeFile(id="sub", name="Sub", mime_type=FOLDER_MIME, parents=["top"]))
    drive.add(
        FakeFile(
            id="only-doc",
            name="Notes",
            mime_type=DOC_MIME,
            parents=["sub"],
            content="idempotency",
        )
    )
    runtime = Runtime(Settings.for_tests(), drive=drive)
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "top"},
        "Bearer test-token",
    )
    assert result["status"] == "COMPLETE"
    assert result.get("partial_reason") != "unsupported_skipped"
    assert result["matches"]


def test_folder_only_tree_is_empty_not_unsupported():
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.infra.config import Settings
    from google_drive_mcp.mcp.middleware import Runtime
    from google_drive_mcp.mcp.tools import handle_tool

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(FakeFile(id="sub", name="Sub", mime_type=FOLDER_MIME, parents=["top"]))
    runtime = Runtime(Settings.for_tests(), drive=drive)
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "top"},
        "Bearer test-token",
    )
    assert result["status"] == "EMPTY"
    assert result["matches"] == []
    assert result.get("category") != "UNSUPPORTED_MIME_TYPE"


def test_grep_max_files_does_not_count_folder_nodes():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for i in range(5):
        folder_id = f"sub-{i}"
        drive.add(
            FakeFile(
                id=folder_id,
                name=f"Sub {i}",
                mime_type=FOLDER_MIME,
                parents=["top"],
            )
        )
        drive.add(
            FakeFile(
                id=f"doc-{i}",
                name=f"Notes {i}",
                mime_type=DOC_MIME,
                parents=[folder_id],
                content="idempotency",
            )
        )
    result = drive_grep(
        drive,
        pattern="idempotency",
        folder_id="top",
        budget=Budget(max_files=5),
    )
    ids = {m["file_id"] for m in result["matches"]}
    assert ids == {f"doc-{i}" for i in range(5)}
    assert result["status"] == "COMPLETE"


def test_folder_export_429_is_partial_not_envelope(runtime, fake_drive):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"
    assert result["matches"] == []


def test_whole_grant_export_429_is_partial(runtime, fake_drive):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency"},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"


def test_multi_file_ids_export_429_is_partial(runtime, fake_drive):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {
            "pattern": "idempotency",
            "file_ids": ["nested-doc", "nested-slide"],
        },
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"


def test_multi_file_ids_skip_then_export_429_is_partial(runtime, fake_drive):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {
            "pattern": "idempotency",
            "file_ids": ["binary-file", "nested-doc"],
        },
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "UNSUPPORTED_MIME_TYPE"


def test_single_file_id_export_429_is_error_envelope(runtime, fake_drive):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["nested-doc"]},
        "Bearer test-token",
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "RATE_LIMITED"


def test_folder_export_429_preserves_matches_already_found(runtime, fake_drive):
    from google_drive_mcp.domain.google_errors import GoogleApiError

    original = fake_drive.export
    seen = {"n": 0}

    def fail_after_first(file_id: str, mime: str) -> str:
        seen["n"] += 1
        if seen["n"] > 1:
            raise GoogleApiError(429)
        return original(file_id, mime)

    fake_drive.export = fail_after_first  # type: ignore[method-assign]
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result["matches"]
    assert {m["file_id"] for m in result["matches"]} == {"nested-doc"}


def test_text_blob_get_media_429_on_folder_grep_is_partial():
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.infra.config import Settings
    from google_drive_mcp.mcp.middleware import Runtime

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(
        FakeFile(
            id="readme",
            name="readme.txt",
            mime_type="text/plain",
            parents=["top"],
            content="idempotency notes",
        )
    )
    drive.rate_limit_export = True
    runtime = Runtime(Settings.for_tests(), drive=drive)
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "top"},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"


def test_grep_mdx_octet_stream_is_searchable(runtime, fake_drive):
    from fakes.fake_drive import FakeFile

    fake_drive.add(
        FakeFile(
            id="essay-mdx",
            name="soundness-reflection-lob.mdx",
            mime_type="application/octet-stream",
            parents=["folder-a"],
            content="A proof shows what follows from axioms.\n",
        )
    )
    result = handle_tool(
        runtime,
        "drive_grep",
        {
            "pattern": "follows from axioms",
            "file_ids": ["essay-mdx"],
            "context_lines": 1,
        },
        "Bearer test-token",
    )
    assert result["status"] == "COMPLETE"
    assert result["matches"]
    assert result["matches"][0]["file_id"] == "essay-mdx"
    assert "follows from axioms" in (result["matches"][0].get("context") or "")
