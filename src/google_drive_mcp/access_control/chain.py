"""Ordered authorization chain. No Google client types. No document content."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google_drive_mcp.access_control.decisions import (
    AuthorizationDecision,
    DecisionOutcome,
    StepFailed,
)
from google_drive_mcp.domain.errors import ErrorCategory, DomainError
from google_drive_mcp.domain.google_errors import GoogleApiError, map_google_error
from google_drive_mcp.domain.retrieval_scope import RetrievalScope, is_within_scope
from google_drive_mcp.infra.mcp_auth.bearer import extract_bearer, verify_bearer

MetadataGet = Callable[[str], Any]
ParentLookup = Callable[[str], list[str] | None]
GoogleMint = Callable[[], object]


def evaluate_chain(
    *,
    authorization: str | None,
    expected_token: str,
    principal_id: str,
    folder_id: str | None = None,
    file_ids: list[str] | None = None,
    file_id: str | None = None,
    get_metadata: MetadataGet | None = None,
    parent_lookup: ParentLookup | None = None,
    mint_credentials: GoogleMint | None = None,
) -> AuthorizationDecision:
    """Run MCP auth → MCP authz → Google auth. Document body is not a parameter."""

    # Step 2 — MCP authentication
    token = extract_bearer(authorization)
    if not verify_bearer(token, expected_token):
        return AuthorizationDecision(
            outcome=DecisionOutcome.AUTHENTICATION_ERROR,
            step_failed=StepFailed.mcp_authentication,
            reason_code="mcp_bearer_rejected",
            principal_id=principal_id,
        )

    # Step 3 — MCP authorization (argument-level only; no Drive I/O)
    scope = RetrievalScope.from_tool_args(
        folder_id=folder_id, file_ids=file_ids, file_id=file_id
    )
    # v1: no ambient allow-list; constructed scopes pass.

    # Step 4 — Google authorization
    if mint_credentials is not None:
        mint_credentials()

    lookup = parent_lookup or (lambda _fid: None)

    def _get(fid: str) -> Any:
        if get_metadata is None:
            raise DomainError.of(ErrorCategory.DRIVE_API_ERROR)
        try:
            return get_metadata(fid)
        except GoogleApiError as exc:
            raise DomainError(map_google_error(exc)) from exc

    named_files = list(scope.file_ids or [])
    try:
        if named_files:
            granted: list[str] = []
            for fid in named_files:
                _get(fid)
                granted.append(fid)
            if scope.folder_id:
                try:
                    _get(scope.folder_id)
                except DomainError as exc:
                    if exc.error.category == ErrorCategory.FILE_NOT_FOUND:
                        raise
                    raise
                for fid in granted:
                    if not is_within_scope(fid, scope, lookup):
                        return AuthorizationDecision(
                            outcome=DecisionOutcome.AUTHORIZATION_ERROR,
                            step_failed=StepFailed.google_authorization,
                            reason_code="file_outside_folder",
                            principal_id=principal_id,
                        )
        elif scope.folder_id:
            _get(scope.folder_id)
        # default_whole_grant: no resource-specific get
    except DomainError as exc:
        if exc.error.category == ErrorCategory.FILE_NOT_FOUND:
            return AuthorizationDecision(
                outcome=DecisionOutcome.FILE_NOT_FOUND,
                step_failed=StepFailed.google_authorization,
                reason_code="google_grant_miss",
                principal_id=principal_id,
            )
        raise

    return AuthorizationDecision(
        outcome=DecisionOutcome.ALLOW,
        step_failed=None,
        reason_code="allow",
        principal_id=principal_id,
    )
