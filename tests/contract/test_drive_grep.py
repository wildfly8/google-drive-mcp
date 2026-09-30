"""drive_grep contract tests including mixed-folder FR-037."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_grep_idempotency_returns_match_with_provenance(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        authz,
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    assert result["matches"]
    match = result["matches"][0]
    assert match["file_id"]
    assert match["matched_text"]
    assert "location" in match
    assert match["source_url"] == f"drive:{match['file_id']}"
    assert not match["source_url"].lower().startswith("http")
    assert match["retrieved_at"]
    assert match["pattern"] == "idempotency"


def test_grep_missing_phrase_is_empty(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "no-such-phrase-xyz", "file_ids": ["nested-doc"]},
        authz,
    )
    assert result["status"] == "EMPTY"
    assert result["matches"] == []


def test_grep_twice_identical(runtime, authz):
    args = {"pattern": "idempotency", "file_ids": ["nested-doc"]}
    first = handle_tool(runtime, "drive_grep", args, authz)
    second = handle_tool(runtime, "drive_grep", args, authz)
    assert first["matches"] == second["matches"]


def test_literal_vs_regex_and_case_flag(runtime, authz):
    literal = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "Idempotency", "file_ids": ["nested-doc"], "regex": False},
        authz,
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
        authz,
    )
    assert insensitive["matches"]
    regex = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency|widgets", "file_ids": ["nested-doc"], "regex": True},
        authz,
    )
    assert regex["matches"]
    escaped = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency|widgets", "file_ids": ["nested-doc"], "regex": False},
        authz,
    )
    assert escaped["status"] == "EMPTY"


def test_slides_grep_uses_character_window_not_lines(runtime, fake_drive, authz):
    fake_drive.update_content(
        "nested-slide",
        "intro line\n\nQuarterly update idempotency extra context",
    )
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["nested-slide"]},
        authz,
    )
    assert result["matches"]
    location = result["matches"][0]["location"]
    assert "offset" in location
    assert "line" not in location


def test_mixed_folder_skips_unsupported_partial(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        authz,
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "unsupported_skipped"
    assert result["matches"]


def test_grep_binary_by_id_is_classified_error(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["binary-file"]},
        authz,
    )
    assert result["status"] == "ERROR"
    assert result["category"] in {"UNSUPPORTED_MIME_TYPE", "FILE_NOT_EXPORTABLE"}


def test_rate_limited_walk_with_only_unsupported_is_partial(authz):
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
        authz,
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


def test_folders_are_not_unsupported_skips(authz):
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
        authz,
    )
    assert result["status"] == "COMPLETE"
    assert result.get("partial_reason") != "unsupported_skipped"
    assert result["matches"]


def test_folder_only_tree_is_empty_not_unsupported(authz):
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
        authz,
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


def test_folder_export_429_is_partial_not_envelope(runtime, fake_drive, authz):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        authz,
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"
    assert result["matches"] == []


def test_whole_grant_export_429_is_partial(runtime, fake_drive, authz):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency"},
        authz,
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"


def test_multi_file_ids_export_429_is_partial(runtime, fake_drive, authz):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {
            "pattern": "idempotency",
            "file_ids": ["nested-doc", "nested-slide"],
        },
        authz,
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"


def test_multi_file_ids_skip_then_export_429_is_partial(runtime, fake_drive, authz):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {
            "pattern": "idempotency",
            "file_ids": ["binary-file", "nested-doc"],
        },
        authz,
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "UNSUPPORTED_MIME_TYPE"


def test_single_file_id_export_429_is_error_envelope(runtime, fake_drive, authz):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["nested-doc"]},
        authz,
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "RATE_LIMITED"


def test_folder_export_429_preserves_matches_already_found(runtime, fake_drive, authz):
    from google_drive_mcp.domain.google_errors import GoogleApiError

    original = fake_drive.export
    seen = {"n": 0}

    def fail_after_first(file_id: str, mime: str) -> str:
        seen["n"] += 1
        if seen["n"] > 1:
            raise GoogleApiError(429)
        return original(file_id, mime)

    fake_drive.export = fail_after_first  # type: ignore[method-assign]
    fake_drive.update_content("text-file", "idempotency")
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        authz,
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result["matches"]
    assert {m["file_id"] for m in result["matches"]} == {"text-file"}


def test_text_blob_get_media_429_on_folder_grep_is_partial(authz):
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
        authz,
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"


def test_grep_mdx_octet_stream_is_searchable(runtime, fake_drive, authz):
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
        authz,
    )
    assert result["status"] == "COMPLETE"
    assert result["matches"]
    assert result["matches"][0]["file_id"] == "essay-mdx"
    assert "follows from axioms" in (result["matches"][0].get("context") or "")


def test_folder_grep_defers_file_that_does_not_fit_and_scans_small_first():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(
        FakeFile(
            id="essay",
            name="essay.md",
            mime_type=DOC_MIME,
            parents=["top"],
            content="short hit",
        )
    )
    drive.add(
        FakeFile(
            id="year-log",
            name="chatgpt-2025.mdx",
            mime_type="application/octet-stream",
            parents=["top"],
            content=b"alpha " + (b"x" * 5000),
        )
    )
    result = drive_grep(
        drive,
        pattern="short hit",
        folder_id="top",
        budget=Budget(max_bytes_per_operation=1000),
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_bytes"
    assert result["deferred_file_ids"] == ["year-log"]
    assert result["files_scanned"] == 1
    assert result["bytes_scanned"] == len("short hit")
    assert {m["file_id"] for m in result["matches"]} == {"essay"}
    assert drive.content_media_count == 0


def test_single_file_id_is_not_deferred_when_larger_than_remaining_budget():
    from fakes.fake_drive import FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    payload = b"alpha token " + (b"x" * 500)
    drive = FakeDrive()
    drive.add(
        FakeFile(
            id="year-a",
            name="chatgpt-2025.mdx",
            mime_type="application/octet-stream",
            parents=["root"],
            content=payload,
        )
    )
    result = drive_grep(
        drive,
        pattern="alpha token",
        file_ids=["year-a"],
        budget=Budget(max_bytes_per_operation=100),
    )
    assert "deferred_file_ids" not in result
    assert drive.content_media_count == 1
    assert result["matches"]
    assert result["files_scanned"] == 1
    assert result["bytes_scanned"] == len(payload)


def test_grep_cursor_resumes_after_last_scanned_file():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for name, size in (("c-doc", 30), ("a-doc", 10), ("b-doc", 20)):
        drive.add(
            FakeFile(
                id=name,
                name=f"{name}.txt",
                mime_type=DOC_MIME,
                parents=["top"],
                content="hit " + ("." * size),
            )
        )
    first = drive_grep(
        drive, pattern="hit", folder_id="top", budget=Budget(max_files=1)
    )
    assert first["status"] == "PARTIAL"
    assert first["partial_reason"] == "max_files"
    assert first["files_scanned"] == 1
    assert first["next_cursor"] == "a-doc"
    assert {m["file_id"] for m in first["matches"]} == {"a-doc"}

    second = drive_grep(
        drive,
        pattern="hit",
        folder_id="top",
        cursor="a-doc",
        budget=Budget(max_files=1),
    )
    assert second["next_cursor"] == "b-doc"
    assert {m["file_id"] for m in second["matches"]} == {"b-doc"}

    third = drive_grep(
        drive,
        pattern="hit",
        folder_id="top",
        cursor="b-doc",
        budget=Budget(max_files=5),
    )
    assert third["status"] == "COMPLETE"
    assert "next_cursor" not in third
    assert {m["file_id"] for m in third["matches"]} == {"c-doc"}
    assert third["files_scanned"] == 1
    assert "bytes_scanned" in third


def test_grep_empty_slice_includes_coverage_counts():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(
        FakeFile(
            id="essay",
            name="essay.md",
            mime_type=DOC_MIME,
            parents=["top"],
            content="nothing relevant",
        )
    )
    result = drive_grep(drive, pattern="missing-phrase", folder_id="top")
    assert result["status"] == "EMPTY"
    assert result["matches"] == []
    assert result["files_scanned"] == 1
    assert result["bytes_scanned"] == len("nothing relevant")
    assert "deferred_file_ids" not in result


def test_deferred_tail_is_not_reported_empty():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(
        FakeFile(
            id="essay",
            name="essay.md",
            mime_type=DOC_MIME,
            parents=["top"],
            content="no phrase here",
        )
    )
    drive.add(
        FakeFile(
            id="year-log",
            name="chatgpt-2025.mdx",
            mime_type="application/octet-stream",
            parents=["top"],
            content=b"x" * 4000,
        )
    )
    result = drive_grep(
        drive,
        pattern="missing-phrase",
        folder_id="top",
        budget=Budget(max_bytes_per_operation=1000),
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_bytes"
    assert result["matches"] == []
    assert result["deferred_file_ids"] == ["year-log"]


def test_next_cursor_argument_resumes_the_same_grep(authz):
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.infra.config import Settings
    from google_drive_mcp.mcp.middleware import Runtime

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for name, size in (("c-doc", 30), ("a-doc", 10), ("b-doc", 20)):
        drive.add(
            FakeFile(
                id=name,
                name=f"{name}.txt",
                mime_type=DOC_MIME,
                parents=["top"],
                content="hit " + ("." * size),
            )
        )
    runtime = Runtime(Settings.for_tests(), drive=drive)
    first = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "hit", "folder_id": "top"},
        authz,
    )
    # The contract helper above uses a tiny max_files via drive_grep(). Here the
    # default cap is GREP_MAX_FILES, so force the cap through the same resume
    # argument the host sends.
    from google_drive_mcp.retrieval.grep import drive_grep

    limited = drive_grep(drive, pattern="hit", folder_id="top", budget=Budget(max_files=1))
    assert limited["next_cursor"] == "a-doc"
    resumed = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "hit", "folder_id": "top", "next_cursor": limited["next_cursor"]},
        authz,
    )
    assert "a-doc" not in {m["file_id"] for m in resumed["matches"]}
    assert {m["file_id"] for m in resumed["matches"]} == {"b-doc", "c-doc"}
    assert first["status"] == "COMPLETE"


def test_unknown_cursor_and_cursor_outside_file_ids_are_invalid(runtime, authz):
    missing = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a", "cursor": "not-a-real-file"},
        authz,
    )
    assert missing["status"] == "ERROR"
    assert missing["category"] == "INVALID_ARGUMENT"
    # With file_ids, a cursor must name one of those files.
    both = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["nested-doc"], "cursor": "other-doc"},
        authz,
    )
    assert both["status"] == "ERROR"
    assert both["category"] == "INVALID_ARGUMENT"
    aliased = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["nested-doc"], "next_cursor": "other-doc:3"},
        authz,
    )
    assert aliased["status"] == "ERROR"
    assert aliased["category"] == "INVALID_ARGUMENT"
    for bad in ("nested-doc:0", "nested-doc:x", "nested-doc:-1", "nested-doc:", ":2"):
        refused = handle_tool(
            runtime,
            "drive_grep",
            {"pattern": "idempotency", "file_ids": ["nested-doc"], "cursor": bad},
            authz,
        )
        assert refused["category"] == "INVALID_ARGUMENT", bad
    blank = handle_tool(
        runtime,
        "drive_grep",
        {
            "pattern": "idempotency",
            "file_ids": ["nested-doc"],
            "next_cursor": "",
            "cursor": "",
        },
        authz,
    )
    assert blank["status"] == "COMPLETE"
    assert blank["matches"]


def _text_folder(count: int, content: str):
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for n in range(count):
        drive.add(
            FakeFile(
                id=f"note-{n:03d}",
                name=f"note-{n:03d}.md",
                mime_type="text/markdown",
                parents=["top"],
                content=content,
            )
        )
    return drive


def test_one_match_per_line_counts_occurrences():
    from fakes.fake_drive import FakeDrive, FakeFile
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(
        FakeFile(
            id="se-entry",
            name="entry.md",
            mime_type="text/markdown",
            content="Causation, correlation and causation\nunrelated\nmore causation",
        )
    )
    result = drive_grep(
        drive, pattern="causation", file_ids=["se-entry"], case_sensitive=False, max_matches=3
    )
    assert result["status"] == "COMPLETE"
    assert [m["location"] for m in result["matches"]] == [
        {"line": 1, "offset": 0, "occurrences": 2},
        {"line": 3, "offset": 5, "occurrences": 1},
    ]
    assert result["matches"][0]["matched_text"] == "Causation"
    assert result["matches"][0]["context"].startswith("Causation, correlation and causation")


def test_repeat_hits_on_one_line_do_not_spend_max_matches():
    from fakes.fake_drive import FakeDrive, FakeFile
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(
        FakeFile(
            id="one-line",
            name="one.md",
            mime_type="text/markdown",
            content="hit hit hit",
        )
    )
    # Three hits on one line take one slot, so max_matches=2 is not reached.
    result = drive_grep(drive, pattern="hit", file_ids=["one-line"], max_matches=2)
    assert result["status"] == "COMPLETE"
    assert len(result["matches"]) == 1
    assert result["matches"][0]["location"]["occurrences"] == 3


def test_folder_grep_scans_more_than_40_files_by_default():
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = _text_folder(45, "nothing here")
    result = drive_grep(drive, pattern="absent-term", folder_id="top")
    assert result["status"] == "EMPTY"
    assert result["files_scanned"] == 45
    assert "next_cursor" not in result


def test_folder_grep_stops_at_grep_file_cap_with_cursor():
    from google_drive_mcp.domain.budgets import GREP_MAX_FILES
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = _text_folder(GREP_MAX_FILES + 1, "nothing here")
    first = drive_grep(drive, pattern="absent-term", folder_id="top")
    assert first["status"] == "PARTIAL"
    assert first["partial_reason"] == "max_files"
    assert first["files_scanned"] == GREP_MAX_FILES
    assert first["next_cursor"] == f"note-{GREP_MAX_FILES - 1:03d}"
    rest = drive_grep(drive, pattern="absent-term", folder_id="top", cursor=first["next_cursor"])
    assert rest["status"] == "EMPTY"
    assert rest["files_scanned"] == 1


def test_grep_description_states_the_file_cap_and_per_line_matches():
    from google_drive_mcp.domain.budgets import GREP_MAX_FILES
    from google_drive_mcp.mcp.tool_schema import DRIVE_GREP_DESCRIPTION

    assert f"up to {GREP_MAX_FILES} files" in DRIVE_GREP_DESCRIPTION
    assert "location.occurrences" in DRIVE_GREP_DESCRIPTION


def _lines_file(file_id: str, lines: int, *, hit: str = "hit"):
    from fakes.fake_drive import FakeFile

    body = "\n".join(f"{hit} {n}" for n in range(1, lines + 1))
    return FakeFile(id=file_id, name=f"{file_id}.md", mime_type="text/markdown", content=body)


def test_max_matches_inside_a_file_returns_an_in_file_cursor():
    from fakes.fake_drive import FakeDrive
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(_lines_file("five", 5))
    first = drive_grep(drive, pattern="hit", file_ids=["five"], max_matches=2)
    assert first["status"] == "PARTIAL"
    assert first["partial_reason"] == "max_matches"
    assert [m["location"]["line"] for m in first["matches"]] == [1, 2]
    assert first["next_cursor"] == "five:2"
    second = drive_grep(
        drive, pattern="hit", file_ids=["five"], max_matches=2, cursor=first["next_cursor"]
    )
    assert [m["location"]["line"] for m in second["matches"]] == [3, 4]
    assert second["next_cursor"] == "five:4"
    last = drive_grep(
        drive, pattern="hit", file_ids=["five"], max_matches=2, cursor=second["next_cursor"]
    )
    assert [m["location"]["line"] for m in last["matches"]] == [5]
    assert last["status"] == "COMPLETE"
    assert "next_cursor" not in last


def test_exactly_max_matches_with_nothing_left_is_complete():
    from fakes.fake_drive import FakeDrive
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(_lines_file("three", 3))
    result = drive_grep(drive, pattern="hit", file_ids=["three"], max_matches=3)
    assert result["status"] == "COMPLETE"
    assert len(result["matches"]) == 3
    assert "next_cursor" not in result


def test_folder_grep_resumes_after_a_max_matches_stop():
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for file_id, lines in (("a-two", 2), ("b-three", 3), ("c-four", 4)):
        item = _lines_file(file_id, lines)
        item.parents = ["top"]
        drive.add(item)
    seen: list[tuple[str, int]] = []
    cursor = None
    calls = 0
    while True:
        calls += 1
        result = drive_grep(drive, pattern="hit", folder_id="top", max_matches=2, cursor=cursor)
        seen.extend((m["file_id"], m["location"]["line"]) for m in result["matches"])
        cursor = result.get("next_cursor")
        if not cursor:
            break
        assert result["partial_reason"] == "max_matches"
    assert result["status"] == "COMPLETE"
    expected = [(f, n) for f, lines in (("a-two", 2), ("b-three", 3), ("c-four", 4))
                for n in range(1, lines + 1)]
    assert seen == expected
    assert calls == 5
    # The first stop fills the cap exactly at the end of a-two, so the cursor
    # continues after that file rather than inside it.
    first = drive_grep(drive, pattern="hit", folder_id="top", max_matches=2)
    assert first["next_cursor"] == "a-two"


class _SlowDrive:
    """FakeDrive wrapper: delays downloads so later files finish first."""

    def __init__(self, drive, delay_for):
        import threading

        self._drive = drive
        self._delay_for = delay_for
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.fetched: list[str] = []
        self.threads: dict[str, str] = {}

    def __getattr__(self, name):
        return getattr(self._drive, name)

    def get_media(self, file_id: str) -> bytes:
        import threading
        import time

        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.fetched.append(file_id)
            self.threads[file_id] = threading.current_thread().name
        try:
            time.sleep(self._delay_for(file_id))
            return self._drive.get_media(file_id)
        finally:
            with self._lock:
                self.in_flight -= 1


def test_prefetched_grep_matches_a_sequential_scan_exactly():
    from google_drive_mcp.domain.budgets import GREP_PREFETCH_WORKERS
    from google_drive_mcp.retrieval.grep import drive_grep

    base = _text_folder(30, "alpha hit\nbeta\nhit again hit")
    reference = drive_grep(base, pattern="hit", folder_id="top", max_matches=50)
    # Earlier files sleep longer, so downloads finish in reverse order.
    slow = _SlowDrive(base, lambda fid: 0.002 * (30 - int(fid.split("-")[1])))
    result = drive_grep(slow, pattern="hit", folder_id="top", max_matches=50)
    strip = lambda r: [(m["file_id"], m["location"]) for m in r["matches"]]  # noqa: E731
    assert strip(result) == strip(reference)
    assert result["status"] == reference["status"] == "PARTIAL"
    assert result["next_cursor"] == reference["next_cursor"]
    assert 1 < slow.max_in_flight <= GREP_PREFETCH_WORKERS


def test_prefetch_skips_large_files_and_never_downloads_deferred_ones():
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.domain.budgets import GREP_PREFETCH_MAX_FILE_BYTES, Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for n in range(5):
        drive.add(FakeFile(id=f"small-{n}", name=f"s{n}.md", mime_type="text/markdown",
                           parents=["top"], content="x" * 100))
    big = "y" * (GREP_PREFETCH_MAX_FILE_BYTES + 10)
    drive.add(FakeFile(id="big-1", name="b1.md", mime_type="text/markdown",
                       parents=["top"], content=big))
    drive.add(FakeFile(id="big-2", name="b2.md", mime_type="text/markdown",
                       parents=["top"], content=big + "z"))
    slow = _SlowDrive(drive, lambda fid: 0.0)
    budget = Budget(max_files=200, max_bytes_per_operation=len(big) + 1000)
    result = drive_grep(slow, pattern="nothing", folder_id="top", budget=budget)
    assert result["deferred_file_ids"] == ["big-2"]
    assert "big-2" not in slow.fetched
    assert slow.threads["big-1"] == "MainThread"
    assert all(slow.threads[f"small-{n}"].startswith("grep-fetch") for n in range(5))


def test_a_download_past_the_time_cap_stops_with_a_cursor():
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    base = _text_folder(4, "nothing here")
    slow = _SlowDrive(base, lambda fid: 1.0 if fid == "note-002" else 0.0)
    result = drive_grep(
        slow,
        pattern="absent",
        folder_id="top",
        budget=Budget(max_files=200, max_execution_time=0.4),
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_execution_time"
    assert result["next_cursor"] == "note-001"
    assert result["files_scanned"] == 2


def test_download_rate_limit_after_listing_keeps_a_cursor():
    from google_drive_mcp.retrieval.grep import drive_grep

    base = _text_folder(3, "nothing here")

    class _Limited(_SlowDrive):
        def get_media(self, file_id: str) -> bytes:
            from google_drive_mcp.domain.google_errors import GoogleApiError

            if file_id == "note-002":
                raise GoogleApiError(429)
            return self._drive.get_media(file_id)

    result = drive_grep(_Limited(base, lambda fid: 0.0), pattern="absent", folder_id="top")
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result["next_cursor"] == "note-001"
    resumed = drive_grep(base, pattern="absent", folder_id="top", cursor=result["next_cursor"])
    assert resumed["status"] == "EMPTY"
    assert resumed["files_scanned"] == 1


def _folder(*files):
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for item in files:
        item.parents = ["top"]
        drive.add(item)
    return drive


def _md(file_id: str, content: str):
    from fakes.fake_drive import FakeFile

    return FakeFile(id=file_id, name=f"{file_id}.md", mime_type="text/markdown", content=content)


def test_repeated_file_ids_are_scanned_once_and_cursors_finish():
    from fakes.fake_drive import FakeDrive
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(_lines_file("aaa", 3))
    drive.add(_lines_file("bbb", 1))
    ids = ["aaa", "aaa", "bbb"]
    seen = []
    cursor = None
    for _ in range(10):
        result = drive_grep(drive, pattern="hit", file_ids=ids, max_matches=2, cursor=cursor)
        seen.extend((m["file_id"], m["location"]["line"]) for m in result["matches"])
        cursor = result.get("next_cursor")
        if not cursor:
            break
    assert cursor is None
    assert sorted(seen) == [("aaa", 1), ("aaa", 2), ("aaa", 3), ("bbb", 1)]


def test_no_cursor_when_only_unsupported_files_remain():
    from fakes.fake_drive import FakeFile
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = _folder(
        _md("a", "hit 1\nhit 2"),
        # Larger than a.md, so it sorts after it.
        FakeFile(id="z", name="z.png", mime_type="image/png", content=b"\x89PNG" + b"." * 60),
    )
    result = drive_grep(drive, pattern="hit", folder_id="top", max_matches=2)
    assert "next_cursor" not in result
    assert result["partial_reason"] == "unsupported_skipped"
    assert len(result["matches"]) == 2
    # A continuation slice left with only unsupported files is PARTIAL, not an error.
    tail = drive_grep(drive, pattern="hit", folder_id="top", cursor="a")
    assert tail["status"] == "PARTIAL"
    assert tail["partial_reason"] == "unsupported_skipped"


def test_cursor_after_a_download_429_does_not_also_defer_revisited_files():
    from fakes.fake_drive import DOC_MIME, FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.domain.google_errors import GoogleApiError
    from google_drive_mcp.retrieval.grep import drive_grep

    class _UnsizedDoc(FakeFile):
        def metadata_dict(self) -> dict:
            data = super().metadata_dict()
            data["size"] = None
            return data

    drive = _folder(
        _md("small", "x" * 10),
        _md("big", "x" * 500),
        _UnsizedDoc(id="doc", name="Doc", mime_type=DOC_MIME, content="text"),
    )

    class _Limited(_SlowDrive):
        def export(self, file_id: str, mime: str) -> str:
            raise GoogleApiError(429)

    result = drive_grep(
        _Limited(drive, lambda fid: 0.0),
        pattern="absent",
        folder_id="top",
        budget=Budget(max_files=200, max_bytes_per_operation=100),
    )
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result["next_cursor"] == "small"
    # "big" comes after the cursor, so the next call handles it; it is not
    # also returned for its own call.
    assert "deferred_file_ids" not in result


def test_oversized_or_deep_cursor_counts():
    from fakes.fake_drive import FakeDrive
    from google_drive_mcp.retrieval.grep import drive_grep, grep_resume_cursor
    from google_drive_mcp.domain.errors import DomainError

    for bad in ("five:" + "9" * 11, "five:" + "1" * 5000, "five:١٢"):
        try:
            grep_resume_cursor({"cursor": bad})
        except DomainError as exc:
            assert exc.error.category.value == "INVALID_ARGUMENT"
        else:
            raise AssertionError(bad)
    drive = FakeDrive()
    drive.add(_lines_file("five", 5))
    deep = drive_grep(drive, pattern="hit", file_ids=["five"], cursor="five:9999999999")
    assert deep["status"] == "EMPTY"
    assert deep["matches"] == []


def test_invalid_utf8_does_not_make_a_prefetched_file_deferred():
    from fakes.fake_drive import FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = _folder(
        FakeFile(id="a", name="a.txt", mime_type="text/plain", content=b"\xff" * 300),
        FakeFile(id="b", name="b.txt", mime_type="text/plain", content="b" * 301),
        FakeFile(id="c", name="c.txt", mime_type="text/plain", content="c" * 302),
        FakeFile(id="d", name="d.txt", mime_type="text/plain", content="d" * 303),
    )
    slow = _SlowDrive(drive, lambda fid: 0.0)
    result = drive_grep(
        slow,
        pattern="absent",
        folder_id="top",
        budget=Budget(max_files=200, max_bytes_per_operation=1000),
    )
    assert result["deferred_file_ids"] == ["d"]
    assert "d" not in slow.fetched
    assert result["bytes_scanned"] == 903


def test_prefetch_counts_unsupported_files_against_max_files():
    from fakes.fake_drive import FakeFile
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = _folder(
        FakeFile(id="bin-1", name="1.bin", mime_type="application/octet-stream", content=b"\x00"),
        FakeFile(id="bin-2", name="2.bin", mime_type="application/octet-stream", content=b"\x01"),
        *[_md(f"md-{n}", "x" * (10 + n)) for n in range(5)],
    )
    slow = _SlowDrive(drive, lambda fid: 0.0)
    result = drive_grep(slow, pattern="absent", folder_id="top", budget=Budget(max_files=3))
    assert result["partial_reason"] == "max_files"
    assert slow.fetched == ["md-0"]


def test_resuming_inside_a_file_does_not_download_later_files():
    from fakes.fake_drive import FakeDrive
    from google_drive_mcp.retrieval.grep import drive_grep

    drive = FakeDrive()
    drive.add(_lines_file("aa", 6))
    drive.add(_lines_file("bb", 7))
    drive.add(_lines_file("cc", 8))
    slow = _SlowDrive(drive, lambda fid: 0.0)
    result = drive_grep(
        slow, pattern="hit", file_ids=["aa", "bb", "cc"], max_matches=2, cursor="aa:2"
    )
    assert result["next_cursor"] == "aa:4"
    assert slow.fetched == ["aa"]
