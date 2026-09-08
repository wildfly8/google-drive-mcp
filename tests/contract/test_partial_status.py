"""PARTIAL status for budgets and walk rate-limit."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_max_matches_partial(runtime):
    result = handle_tool(
        runtime,
        "drive_grep",
        {"pattern": "idempotency", "file_ids": ["nested-doc"], "max_matches": 1},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_matches"
    assert len(result["matches"]) == 1


def test_ls_pagination_not_complete_when_more_remain(runtime):
    result = handle_tool(
        runtime,
        "drive_ls",
        {"folder_id": "folder-a", "max_results": 1},
        "Bearer test-token",
    )
    assert result["status"] == "PARTIAL"
    assert result.get("next_page_token")


def test_walk_rate_limit_is_partial_not_error_envelope(runtime, fake_drive):
    fake_drive.rate_limit_lists_after = 0
    result = handle_tool(
        runtime, "drive_find", {"folder_id": "folder-a"}, "Bearer test-token"
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "RATE_LIMITED"
    assert result.get("category") != "RATE_LIMITED"


def test_single_file_429_is_error_envelope_rate_limited(runtime, fake_drive):
    fake_drive.rate_limit_export = True
    result = handle_tool(
        runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token"
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "RATE_LIMITED"


def test_max_execution_time_partial(runtime):
    from google_drive_mcp.domain.budgets import Budget
    from google_drive_mcp.retrieval.find import drive_find

    budget = Budget(max_execution_time=0)
    result = drive_find(runtime.drive, folder_id="folder-a", budget=budget)
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_execution_time"
