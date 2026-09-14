"""Default resource budgets (plan-level FR-104)."""

from __future__ import annotations

from dataclasses import dataclass
import time

MAX_FILES = 40
MAX_BYTES_PER_FILE = 5_000_000
MAX_BYTES_PER_OPERATION = 20_000_000
MAX_MATCHES = 50
MAX_EXECUTION_TIME = 25.0
MAX_CONTEXT_LINES = 2
MAX_EXPORT_SIZE = 5_000_000
MAX_CONTEXT_WINDOW_CHARS = 200


@dataclass
class Budget:
    max_files: int = MAX_FILES
    max_bytes_per_file: int = MAX_BYTES_PER_FILE
    max_bytes_per_operation: int = MAX_BYTES_PER_OPERATION
    max_matches: int = MAX_MATCHES
    max_execution_time: float = MAX_EXECUTION_TIME
    max_context_lines: int = MAX_CONTEXT_LINES
    max_export_size: int = MAX_EXPORT_SIZE
    clock: object = time.monotonic
    _start: float = 0.0
    files_seen: int = 0
    bytes_seen: int = 0
    matches_seen: int = 0

    def __post_init__(self) -> None:
        self._start = float(self.clock())  # type: ignore[operator]

    def time_exceeded(self) -> bool:
        return (float(self.clock()) - self._start) >= self.max_execution_time  # type: ignore[operator]

    def note_file(self) -> None:
        self.files_seen += 1

    def note_bytes(self, n: int) -> None:
        self.bytes_seen += n

    def note_matches(self, n: int) -> None:
        self.matches_seen += n

    def files_exhausted(self) -> bool:
        return self.files_seen >= self.max_files

    def bytes_exhausted(self) -> bool:
        return self.bytes_seen >= self.max_bytes_per_operation

    def matches_exhausted(self) -> bool:
        return self.matches_seen >= self.max_matches
