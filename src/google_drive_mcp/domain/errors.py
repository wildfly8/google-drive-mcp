"""Canonical agent-visible error taxonomy and envelope."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorCategory(StrEnum):
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_NOT_EXPORTABLE = "FILE_NOT_EXPORTABLE"
    UNSUPPORTED_MIME_TYPE = "UNSUPPORTED_MIME_TYPE"
    DRIVE_API_ERROR = "DRIVE_API_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    TEMPORARY_STORAGE_ERROR = "TEMPORARY_STORAGE_ERROR"
    SEARCH_ERROR = "SEARCH_ERROR"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"


class ErrorEnvelope(BaseModel):
    """Wire error object. Never interpolates secrets or unauthorized metadata."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ERROR"] = "ERROR"
    category: ErrorCategory
    message: str = Field(min_length=1)
    request_id: str | None = None

    def to_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


SAFE_MESSAGES: dict[ErrorCategory, str] = {
    ErrorCategory.AUTHENTICATION_ERROR: "Authentication failed.",
    ErrorCategory.AUTHORIZATION_ERROR: "The named file is outside the requested folder scope.",
    ErrorCategory.FILE_NOT_FOUND: "The requested file was not found.",
    ErrorCategory.FILE_NOT_EXPORTABLE: "The file cannot be exported as usable text.",
    ErrorCategory.UNSUPPORTED_MIME_TYPE: "The file type cannot yield usable text.",
    ErrorCategory.DRIVE_API_ERROR: "The Drive API request failed.",
    ErrorCategory.RATE_LIMITED: "The Drive API rate limit was exceeded.",
    ErrorCategory.RESOURCE_LIMIT: "The export exceeded the configured size limit.",
    ErrorCategory.TEMPORARY_STORAGE_ERROR: "Temporary storage for this operation failed.",
    ErrorCategory.SEARCH_ERROR: "Exact search failed.",
    ErrorCategory.INVALID_ARGUMENT: "One or more arguments are invalid.",
}


def envelope(
    category: ErrorCategory,
    *,
    message: str | None = None,
    request_id: str | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        category=category,
        message=message or SAFE_MESSAGES[category],
        request_id=request_id,
    )


class DomainError(Exception):
    """Raised inside use cases; converted to ErrorEnvelope at the tool boundary."""

    def __init__(self, error: ErrorEnvelope) -> None:
        self.error = error
        super().__init__(error.message)

    @classmethod
    def of(
        cls,
        category: ErrorCategory,
        *,
        message: str | None = None,
        request_id: str | None = None,
    ) -> DomainError:
        return cls(envelope(category, message=message, request_id=request_id))
