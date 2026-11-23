"""A grep that cannot afford any bytes says so, and names what it did not read (Article X).

With no bytes left in the operation, every searchable file is set aside in deferred_file_ids
and the call is PARTIAL (max_bytes). It must not look like a finished search that found
nothing.
"""

from __future__ import annotations

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.retrieval.grep import drive_grep


def test_a_call_with_no_bytes_left_defers_every_searchable_file(fake_drive):
    result = drive_grep(
        fake_drive,
        pattern="idempotency",
        folder_id="folder-a",
        budget=Budget(max_files=200, max_bytes_per_operation=0),
    )
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_bytes"
    assert result["matches"] == []
    assert set(result["deferred_file_ids"]) == {
        "nested-doc",
        "nested-sheet",
        "nested-slide",
        "text-file",
    }
    assert fake_drive.content_count == 0, "a deferred file is never downloaded"
