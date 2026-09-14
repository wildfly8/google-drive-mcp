"""Hosts must not receive HTTP URLs in provenance source_url fields."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def _assert_source_urls_are_locators(obj: object) -> None:
    if isinstance(obj, dict):
        if "source_url" in obj:
            url = obj["source_url"]
            assert isinstance(url, str)
            assert url.startswith("drive:")
            assert "://" not in url
            assert not url.lower().startswith("http")
            file_id = obj.get("id") or obj.get("file_id")
            if isinstance(file_id, str) and file_id:
                assert url == f"drive:{file_id}"
        for value in obj.values():
            _assert_source_urls_are_locators(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_source_urls_are_locators(item)


def test_ls_find_read_grep_source_url_is_not_http(runtime, authz):
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
        _assert_source_urls_are_locators(result)
        blob = str(result)
        assert "https://drive.google.com" not in blob
        assert "https://docs.google.com" not in blob
