"""No tool result carries a source link or locator.

A host lists any such field as a source and offers an HTTP link as a download, so
results identify files by file_id and file_name, for the agent's own tracking, and
carry nothing a host could present as a source (owner decision, 2026-10-05).
"""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool

LINK_KEYS = {"source_url", "web_view_link", "webViewLink", "url", "href"}


def _assert_no_link_fields(obj: object) -> None:
    if isinstance(obj, dict):
        assert not LINK_KEYS & obj.keys(), sorted(LINK_KEYS & obj.keys())
        for value in obj.values():
            _assert_no_link_fields(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_link_fields(item)


def test_ls_find_read_grep_results_carry_no_link_or_locator(runtime, authz):
    ls = handle_tool(runtime, "drive_ls", {"folder_id": "folder-a"}, authz)
    find = handle_tool(runtime, "drive_find", {"folder_id": "folder-a"}, authz)
    read = handle_tool(runtime, "drive_read", {"file_id": "nested-doc"}, authz)
    grep = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "folder_id": "folder-a"},
        authz,
    )
    for result in (ls, find, read, grep):
        assert result["status"] in {"COMPLETE", "PARTIAL"}
        _assert_no_link_fields(result)
        blob = str(result)
        assert "https://drive.google.com" not in blob
        assert "https://docs.google.com" not in blob
        assert "drive:" not in blob
    # What the agent needs to chain calls is still there.
    assert read["file_id"] == "nested-doc" and read["file_name"]
    assert grep["matches"][0]["file_id"] and grep["matches"][0]["file_name"]
    assert all(c["id"] and c["name"] for c in ls["children"])
    assert all(c["file"]["id"] and c["file"]["name"] for c in find["candidates"])
