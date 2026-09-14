"""drive_find contract tests."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_find_includes_nested_doc_as_candidate_not_evidence(runtime, authz):
    result = handle_tool(
        runtime, "drive_find", {"folder_id": "folder-a"}, authz
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    ids = {c["file"]["id"] for c in result["candidates"]}
    assert "nested-doc" in ids
    for cand in result["candidates"]:
        assert cand["discovery_method"] == "find"
        assert "reason" in cand
        assert "content" not in cand
        assert "content" not in cand["file"]
        assert cand["file"]["source_url"] == f"drive:{cand['file']['id']}"
        assert not cand["file"]["source_url"].lower().startswith("http")
        assert "verified" not in cand
        assert "evidence" not in cand
    assert "trashed-doc" not in ids


def test_find_folder_includes_trashed_when_requested(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_find",
        {"folder_id": "folder-a", "trashed": True},
        authz,
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    ids = {c["file"]["id"] for c in result["candidates"]}
    assert "nested-doc" in ids
    assert "trashed-doc" in ids
