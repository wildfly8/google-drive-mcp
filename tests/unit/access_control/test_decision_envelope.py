"""A refusal does not say which rule refused (Article XI, AC-FR-025).

The reason code is for the server's own log. If it reached the reply, an outside folder, a
missing id and an unset allow-list would answer differently and tell a caller what exists.
"""

from __future__ import annotations

from google_drive_mcp.access_control.decisions import (
    AuthorizationDecision,
    DecisionOutcome,
    StepFailed,
)

REASONS = (
    "outside_allowed_folder",
    "no_allowed_folder",
    "whole_grant_refused",
    "file_outside_folder",
    "google_grant_miss",
)


def _reply(reason: str) -> dict:
    decision = AuthorizationDecision(
        outcome=DecisionOutcome.AUTHORIZATION_ERROR,
        step_failed=StepFailed.google_authorization,
        reason_code=reason,
        principal_id="deployment-1",
    )
    return decision.to_envelope(request_id="req-1").to_dict()


def test_every_refusal_gets_the_same_reply():
    replies = [_reply(reason) for reason in REASONS]
    assert all(reply == replies[0] for reply in replies)
    assert replies[0]["category"] == "AUTHORIZATION_ERROR"
    assert not any(reason in str(replies[0]) for reason in REASONS)
