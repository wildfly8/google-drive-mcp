"""fetch_text refuses a file it cannot read as text before it downloads anything.

The tools check the type first, so this is the layer behind them: a binary is never decoded
as text (it would come back as replacement characters, looking like content).
"""

from __future__ import annotations

import pytest

from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.infra.google_drive.export import fetch_text


@pytest.mark.parametrize(
    ("mime", "name"),
    [("application/octet-stream", "photo.bin"), ("image/png", "scan.png"), ("application/pdf", "a.pdf")],
)
def test_a_binary_is_refused_and_never_downloaded(fake_drive, mime: str, name: str):
    with pytest.raises(DomainError) as caught:
        fetch_text(
            fake_drive,
            "binary-file",
            mime,
            "text/plain",
            max_bytes=1_000_000,
            name=name,
        )
    assert caught.value.error.category == ErrorCategory.UNSUPPORTED_MIME_TYPE
    assert fake_drive.content_count == 0
