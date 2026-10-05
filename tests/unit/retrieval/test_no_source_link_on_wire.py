"""A DriveFile's wire output carries its id and name, never a Drive link or locator."""

from __future__ import annotations

from google_drive_mcp.domain.drive_file import DriveFile


def test_wire_has_the_id_and_name_but_no_link_or_locator():
    file = DriveFile(
        id="abc123",
        name="Notes",
        mime_type="text/plain",
        modified_time="2020-01-01T00:00:00Z",
        web_view_link="https://drive.google.com/file/d/abc123/view",
    )
    for wire in (file.child_wire(), file.candidate_file_wire()):
        assert wire["id"] == "abc123"
        assert wire["name"] == "Notes"
        assert "source_url" not in wire
        assert "web_view_link" not in wire
        assert "http" not in str(wire).lower()
        assert "drive:" not in str(wire)


def test_from_metadata_does_not_copy_a_link_onto_the_wire():
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
    for wire in (file.child_wire(), file.candidate_file_wire()):
        assert "source_url" not in wire
        assert "http" not in str(wire).lower()
    assert not hasattr(file, "source_url")
