"""INVALID_ARGUMENT contract tests."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_bad_regex(runtime):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "[", "regex": True, "file_ids": ["nested-doc"]},
        "Bearer test-token",
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_bad_file_id_shape(runtime):
    result = handle_tool(
        runtime,
        "drive_read",
        {"file_id": "not a/valid id"},
        "Bearer test-token",
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_max_results_out_of_range(runtime):
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "folder-a", "max_results": 0}, "Bearer test-token"
    )
    assert result["category"] == "INVALID_ARGUMENT"
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "folder-a", "max_results": 41}, "Bearer test-token"
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_max_bytes_out_of_range(runtime):
    result = handle_tool(
        runtime,
        "drive_read",
        {"file_id": "nested-doc", "max_bytes": 0},
        "Bearer test-token",
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_unknown_content_format(runtime):
    result = handle_tool(
        runtime,
        "drive_read",
        {"file_id": "nested-doc", "content_format": "nope/nope"},
        "Bearer test-token",
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_bad_page_token_is_invalid_argument(runtime):
    result = handle_tool(
        runtime,
        "drive_ls",
        {"folder_id": "folder-a", "page_token": "not-an-int"},
        "Bearer test-token",
    )
    assert result["category"] == "INVALID_ARGUMENT"
