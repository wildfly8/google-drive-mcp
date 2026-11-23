"""The scan downloads at most 8 MB ahead of itself, so memory stays near a one-file scan.

Files are fetched ahead on worker threads. The byte window is what keeps that bounded when
every file is large enough to matter, so its size is pinned in bytes, not by the constant.
"""

from __future__ import annotations

from google_drive_mcp.domain.drive_file import DriveFile
from google_drive_mcp.retrieval.grep import _Prefetch

MB = 1_000_000


def _files(count: int, size: int) -> list[DriveFile]:
    return [
        DriveFile(
            id=f"f{n}",
            name=f"f{n}.md",
            mime_type="text/markdown",
            modified_time="2024-01-01T00:00:00Z",
            size=size,
        )
        for n in range(count)
    ]


def _queued(prefetch: _Prefetch, count: int) -> int:
    return sum(1 for index in range(count) if prefetch.has(index))


def test_the_bytes_fetched_ahead_stay_inside_an_eight_megabyte_window():
    files = _files(20, 3 * MB // 2)  # 1.5 MB each
    prefetch = _Prefetch(files, lambda _file: None, max_file_bytes=20 * MB)
    try:
        prefetch.top_up(0, bytes_left=20 * MB, files_left=200)
        queued = _queued(prefetch, len(files))
    finally:
        prefetch.close()
    assert queued >= 4, "the scan should fetch ahead at all"
    assert queued * 3 * MB // 2 <= 8 * MB


def test_nothing_is_fetched_ahead_that_the_operation_could_not_afford():
    files = _files(20, 3 * MB // 2)
    prefetch = _Prefetch(files, lambda _file: None, max_file_bytes=20 * MB)
    try:
        prefetch.top_up(0, bytes_left=3 * MB, files_left=200)
        queued = _queued(prefetch, len(files))
    finally:
        prefetch.close()
    assert queued * 3 * MB // 2 <= 3 * MB
