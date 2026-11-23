"""Reading and searching write nothing to disk (Article III: ephemeral computation).

Document text lives in memory for the length of one call. Cloud Run's /tmp is memory too, so
a temp file would be one more copy of the knowledge base. The temp directory is redirected to
an empty one, and any open for writing is recorded while the four tools run.
"""

from __future__ import annotations

import builtins
import tempfile
from pathlib import Path

from google_drive_mcp.mcp.tools import handle_tool

CALLS = [
    ("drive_ls", {"folder_id": "folder-a"}),
    ("drive_find", {"name_pattern": "notes"}),
    ("drive_read", {"file_id": "nested-doc"}),
    ("drive_read", {"file_id": "nested-sheet"}),
    ("drive_grep", {"pattern": "idempotency", "file_ids": ["nested-doc"]}),
    ("drive_grep", {"pattern": "idempotency", "folder_id": "folder-a"}),
    ("drive_grep", {"pattern": "idem[a-z]+", "regex": True, "folder_id": "folder-a"}),
]


def test_the_four_tools_write_no_file(runtime, authz, tmp_path: Path, monkeypatch):
    private = tmp_path / "tmp"
    private.mkdir()
    monkeypatch.setenv("TMPDIR", str(private))
    monkeypatch.setattr(tempfile, "tempdir", str(private))
    opened_for_writing: list[tuple[str, str]] = []
    real_open = builtins.open

    def watching_open(file, mode="r", *args, **kwargs):
        if set(str(mode)) & set("wax+"):
            opened_for_writing.append((str(file), str(mode)))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", watching_open)
    for tool, arguments in CALLS:
        result = handle_tool(runtime, tool, arguments, authz)
        assert result["status"] != "ERROR", (tool, result)
    assert opened_for_writing == []
    assert list(private.iterdir()) == []
