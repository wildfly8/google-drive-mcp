"""Every grep match says where it came from and when (Article VIII).

A host quotes from matches, so each one carries the file's id and name, its type, when Drive
last modified it, when this server read it, the pattern, the text, and the place in the file.
There is no link or locator: the citation is one line, not a source list.
"""

from __future__ import annotations

import re

from google_drive_mcp.mcp.tools import handle_tool

PROVENANCE = {
    "file_id",
    "file_name",
    "mime_type",
    "modified_time",
    "retrieved_at",
    "pattern",
    "matched_text",
    "location",
}


def test_a_match_carries_its_full_provenance(runtime, fake_drive, authz):
    result = handle_tool(
        runtime, "drive_grep", {"pattern": "idempotency", "file_ids": ["nested-doc"]}, authz
    )
    assert result["matches"]
    source = fake_drive.files["nested-doc"]
    for match in result["matches"]:
        assert PROVENANCE <= set(match)
        assert match["file_id"] == "nested-doc"
        assert match["file_name"] == source.name
        assert match["mime_type"] == source.mime_type
        assert match["modified_time"] == source.modified_time
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", match["retrieved_at"])
        assert match["pattern"] == "idempotency"
        assert match["matched_text"] == "idempotency"
        assert match["location"]
        assert not {k for k in match if "url" in k or "link" in k}


def test_the_modified_time_follows_an_edit(runtime, fake_drive, authz):
    fake_drive.update_content("nested-doc", "idempotency again", modified_time="2031-02-03T04:05:06Z")
    match = handle_tool(
        runtime, "drive_grep", {"pattern": "idempotency", "file_ids": ["nested-doc"]}, authz
    )["matches"][0]
    assert match["modified_time"] == "2031-02-03T04:05:06Z"
