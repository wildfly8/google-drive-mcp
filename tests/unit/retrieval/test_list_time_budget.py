"""Production list adapter honors max_execution_time during pagination."""

from __future__ import annotations

from unittest.mock import MagicMock

from google_drive_mcp.domain.budgets import Budget
from google_drive_mcp.infra.google_drive.client import GoogleDriveClient


def test_list_stops_before_paging_when_time_budget_is_zero():
    client = GoogleDriveClient.__new__(GoogleDriveClient)
    client._service = MagicMock()
    client.metadata_get_count = 0
    client.content_export_count = 0
    client.content_media_count = 0
    client.list_time_exceeded = False
    client._service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "a", "name": "n", "mimeType": "text/plain"}],
        "nextPageToken": "more",
    }
    items = client._list("q", budget=Budget(max_execution_time=0))
    assert items == []
    assert client.list_time_exceeded is True
    client._service.files.return_value.list.assert_not_called()
