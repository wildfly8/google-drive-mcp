"""Argument shape checks shared by tools and advertised MCP JSON Schema."""

from __future__ import annotations

import re

from google_drive_mcp.domain.errors import DomainError, ErrorCategory

FILE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
FILE_ID_RE = re.compile(FILE_ID_PATTERN)

MAX_RESULTS_MIN = 1
MAX_RESULTS_MAX = 40
MAX_MATCHES_MIN = 1
MAX_MATCHES_MAX = 50
CONTEXT_LINES_MIN = 0
CONTEXT_LINES_MAX = 10
MAX_BYTES_MIN = 1
MAX_BYTES_MAX = 5_000_000


def require_file_id(value: str) -> None:
    if not isinstance(value, str) or not FILE_ID_RE.fullmatch(value):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
