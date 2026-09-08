"""AuthorizationDecision — outcome of one chain evaluation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from google_drive_mcp.domain.errors import ErrorCategory, ErrorEnvelope, envelope


class DecisionOutcome(StrEnum):
    ALLOW = "ALLOW"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"


class StepFailed(StrEnum):
    mcp_authentication = "mcp_authentication"
    mcp_authorization = "mcp_authorization"
    google_authorization = "google_authorization"


class AuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: DecisionOutcome
    step_failed: StepFailed | None = None
    reason_code: str
    principal_id: str

    @property
    def allowed(self) -> bool:
        return self.outcome == DecisionOutcome.ALLOW

    def to_envelope(self, request_id: str | None = None) -> ErrorEnvelope:
        if self.outcome == DecisionOutcome.ALLOW:
            raise ValueError("ALLOW is not an error envelope")
        return envelope(ErrorCategory(self.outcome.value), request_id=request_id)
