"""Per-file and export caps admit one 20 MB blob and stop the next one."""

from __future__ import annotations

from fakes.fake_drive import FakeDrive, FakeFile
from google_drive_mcp.domain.budgets import (
    MAX_BYTES_PER_FILE,
    MAX_BYTES_PER_OPERATION,
    MAX_EXPORT_SIZE,
)
from google_drive_mcp.infra.google_drive.export import fetch_text
from google_drive_mcp.mcp.validation import MAX_BYTES_MAX
from google_drive_mcp.retrieval.grep import drive_grep


class _Blob:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def get_media(self, file_id: str) -> bytes:
        return self.payload


def test_caps_are_20mb_and_match():
    assert MAX_BYTES_PER_FILE == 20_000_000
    assert MAX_EXPORT_SIZE == 20_000_000
    assert MAX_BYTES_PER_OPERATION == 20_000_000
    assert MAX_BYTES_MAX == 20_000_000


def test_blob_at_export_cap_is_not_truncated():
    payload = b"a" * MAX_EXPORT_SIZE
    result = fetch_text(
        _Blob(payload),
        "year",
        "application/octet-stream",
        "text/markdown",
        max_bytes=MAX_BYTES_PER_FILE,
        name="chatgpt-2025.mdx",
    )
    assert result.truncated is False
    assert result.byte_length == MAX_EXPORT_SIZE


def test_one_byte_over_export_cap_is_partial_prefix():
    payload = b"a" * (MAX_EXPORT_SIZE + 1)
    result = fetch_text(
        _Blob(payload),
        "year",
        "application/octet-stream",
        "text/markdown",
        max_bytes=MAX_BYTES_PER_FILE,
        name="chatgpt-2025.mdx",
    )
    assert result.truncated is True
    assert result.byte_length == MAX_EXPORT_SIZE


def test_single_mdx_file_grep_is_complete():
    drive = FakeDrive()
    drive.add(
        FakeFile(
            id="year-a",
            name="chatgpt-2025.mdx",
            mime_type="application/octet-stream",
            parents=["root"],
            content=b"alpha token " + (b"x" * 100),
        )
    )
    result = drive_grep(drive, pattern="alpha token", file_ids=["year-a"])
    assert result["status"] == "COMPLETE"
    assert result["matches"]
