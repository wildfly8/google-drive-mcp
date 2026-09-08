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


def test_mixed_folder_skips_unsupported_partial(runtime):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"]
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
