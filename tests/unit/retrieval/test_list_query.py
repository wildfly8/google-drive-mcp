"""files.list query text and page size."""

from __future__ import annotations

from google_drive_mcp.domain.list_filter import ListFilter
from google_drive_mcp.infra.google_drive.query import files_list_query, list_page_size


def test_page_size_is_one_thousand():
    assert list_page_size() == 1000


def test_folder_name_query_keeps_subfolders_and_escapes_quotes():
    query = files_list_query(
        "folder'1",
        ListFilter(name_contains="o'brien\\x", include_subfolders=True),
        include_trashed=False,
    )
    assert query is not None
    assert "'folder\\'1' in parents" in query
    assert "trashed = false" in query
    assert "mimeType = 'application/vnd.google-apps.folder'" in query
    assert "name contains 'o\\'brien\\\\x'" in query


def test_whole_grant_query_adds_mime_and_modified_bounds():
    query = files_list_query(
        None,
        ListFilter(
            mime_type="application/vnd.google-apps.document",
            modified_after="2024-01-01T00:00:00Z",
            modified_before="2024-12-31T00:00:00Z",
        ),
        include_trashed=False,
    )
    assert query == (
        "trashed = false and "
        "mimeType = 'application/vnd.google-apps.document' and "
        "modifiedTime >= '2024-01-01T00:00:00Z' and "
        "modifiedTime <= '2024-12-31T00:00:00Z'"
    )
