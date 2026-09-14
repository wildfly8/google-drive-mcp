"""Wire source_url is drive:{id}, never an HTTP view link."""

from __future__ import annotations

from google_drive_mcp.domain.drive_file import DriveFile, drive_source_locator


def test_source_url_ignores_web_view_link_http():
    file = DriveFile(
        id="abc123",
        name="Notes",
        mime_type="text/plain",
        modified_time="2020-01-01T00:00:00Z",
        web_view_link="https://drive.google.com/file/d/abc123/view",
    )
    assert file.source_url == "drive:abc123"
    assert file.source_url == drive_source_locator("abc123")
    assert not file.source_url.lower().startswith("http")
    wire = file.child_wire()
    assert wire["source_url"] == "drive:abc123"
    assert "web_view_link" not in wire
    assert "https://" not in wire["source_url"]
    candidate = file.candidate_file_wire()
    assert candidate["source_url"] == "drive:abc123"


def test_from_metadata_does_not_copy_http_source_url_onto_wire():
    file = DriveFile.from_metadata(
        {
            "id": "nested-doc",
            "name": "Doc",
            "mime_type": "application/vnd.google-apps.document",
            "modified_time": "2020-01-01T00:00:00Z",
            "web_view_link": "https://docs.google.com/document/d/nested-doc/edit",
            "source_url": "https://docs.google.com/document/d/nested-doc/edit",
        }
    )
    assert file.source_url == "drive:nested-doc"
    assert "http" not in file.child_wire()["source_url"]
