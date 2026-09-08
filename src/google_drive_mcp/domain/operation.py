"""Operation status for retrieval tools."""

from __future__ import annotations

from enum import StrEnum


class OperationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    ERROR = "ERROR"


class PartialReason(StrEnum):
    max_files = "max_files"
    max_bytes = "max_bytes"
    max_matches = "max_matches"
    max_execution_time = "max_execution_time"
    RATE_LIMITED = "RATE_LIMITED"
    unsupported_skipped = "unsupported_skipped"
    pagination = "pagination"
