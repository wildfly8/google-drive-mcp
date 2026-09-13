"""drive_ls contract tests."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_ls_folder_returns_children_metadata_with_source_url_no_content(runtime, authz):
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "folder-a"}, authz
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    ids = {c["id"] for c in result["children"]}
    assert "nested-doc" in ids
    for child in result["children"]:
        assert "source_url" in child
        assert "content" not in child
        assert child["modified_time"]
    assert result.get("content") is None


def test_ls_empty_unknown_folder_is_file_not_found(runtime, authz):
    result = handle_tool(
        runtime, "drive_ls", {"folder_id": "missing-folder"}, authz
    )
    assert result["category"] == "FILE_NOT_FOUND"


def test_ls_omitted_folder_lists_root_children(runtime, authz):
    result = handle_tool(runtime, "drive_ls", {}, authz)
    ids = {c["id"] for c in result["children"]}
    assert "folder-a" in ids
    assert "nested-doc" not in ids
