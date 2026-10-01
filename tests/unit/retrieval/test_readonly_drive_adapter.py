"""Drive adapter must not expose mutating files() methods."""

from __future__ import annotations

from pathlib import Path

FORBIDDEN_SNIPPETS = (
    "files().create(",
    "files().update(",
    "files().delete(",
    ".permissions(",
)


def test_google_drive_adapter_has_no_write_methods():
    # All of src/, not only the adapter package: a writer elsewhere is still a writer.
    root = Path("src/google_drive_mcp")
    blob = "\n".join(p.read_text() for p in root.rglob("*.py"))
    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet not in blob
