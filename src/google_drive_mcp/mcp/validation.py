"""Argument shape checks shared by tools."""

from __future__ import annotations

import re

from google_drive_mcp.domain.errors import DomainError, ErrorCategory

FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def require_file_id(value: str) -> None:
    if not isinstance(value, str) or not FILE_ID_RE.fullmatch(value):
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
