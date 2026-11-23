"""drive_find's name_pattern is a case-insensitive substring of the file name.

The tool description promises it, and Drive's own `name contains` is looser than a substring
(it matches word prefixes), so the exact, case-insensitive check is the server's own.
"""

from __future__ import annotations

import pytest

from google_drive_mcp.mcp.tools import handle_tool


@pytest.mark.parametrize("pattern", ["notes", "NOTES", "oTe", "Notes"])
def test_name_pattern_ignores_case(runtime, authz, pattern: str):
    result = handle_tool(runtime, "drive_find", {"name_pattern": pattern}, authz)
    names = [c["file"]["name"] for c in result["candidates"]]
    assert "Notes" in names
    assert "Deleted Notes" not in names  # trashed files are not candidates


def test_name_pattern_is_a_substring_not_a_word_prefix(runtime, authz):
    result = handle_tool(runtime, "drive_find", {"name_pattern": "otes"}, authz)
    assert [c["file"]["name"] for c in result["candidates"]] == ["Notes"]
