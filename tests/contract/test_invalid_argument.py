"""INVALID_ARGUMENT contract tests."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_bad_regex(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "[", "regex": True, "file_ids": ["nested-doc"]},
        authz,
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_bad_file_id_shape(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_read",
        {"file_id": "not a/valid id"},
        authz,
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_max_results_out_of_range(runtime, authz):
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "folder-a", "max_results": 0}, authz
    )
    assert result["category"] == "INVALID_ARGUMENT"
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "folder-a", "max_results": 41}, authz
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_max_bytes_out_of_range(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_read",
        {"file_id": "nested-doc", "max_bytes": 0},
        authz,
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_unknown_content_format(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_read",
        {"file_id": "nested-doc", "content_format": "nope/nope"},
        authz,
    )
    assert result["category"] == "INVALID_ARGUMENT"


def test_bad_page_token_is_invalid_argument(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_ls",
        {"folder_id": "folder-a", "page_token": "not-an-int"},
        authz,
    )
    assert result["category"] == "INVALID_ARGUMENT"
