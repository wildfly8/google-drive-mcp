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
from google_drive_mcp.domain.retrieval_scope import (
    RetrievalScope,
    apply_allowed_folder,
    is_within_scope,
)

MetadataGet = Callable[[str], Any]
ParentLookup = Callable[[str], list[str] | None]
GoogleMint = Callable[[], object]


def evaluate_chain(
    *,
    authorization: str | None,
    verify_caller: Callable[[str | None], bool],
    principal_id: str,
    folder_id: str | None = None,
    file_ids: list[str] | None = None,
    file_id: str | None = None,
    allowed_folder_id: str | None = None,
    get_metadata: MetadataGet | None = None,
    parent_lookup: ParentLookup | None = None,
    mint_credentials: GoogleMint | None = None,
) -> AuthorizationDecision:
    """Run MCP auth → MCP authz → Google auth. Document body is not a parameter."""

    # Step 2 — MCP authentication (OAuth 2.1 access token; not a shared secret)
    if not verify_caller(authorization):
        return AuthorizationDecision(
            outcome=DecisionOutcome.AUTHENTICATION_ERROR,
            step_failed=StepFailed.mcp_authentication,
            reason_code="mcp_access_token_rejected",
            principal_id=principal_id,
        )

    # Step 3 — MCP authorization (argument-level only; no Drive I/O).
    # Fail closed: with no allow-list folder nothing is readable, and a call
    # that names no folder or file after the rewrite is refused rather than
    # widened to the whole Google grant.
    allowed = (allowed_folder_id or "").strip() or None
    if not allowed:
        return _refuse(principal_id, StepFailed.mcp_authorization, "no_allowed_folder")
    rewritten = {
        "folder_id": folder_id,
        "file_ids": file_ids,
        "file_id": file_id,
    }
    apply_allowed_folder(rewritten, allowed)
    folder_id = rewritten.get("folder_id")
    file_ids = rewritten.get("file_ids")
    file_id = rewritten.get("file_id")

    scope = RetrievalScope.from_tool_args(
        folder_id=folder_id, file_ids=file_ids, file_id=file_id
    )
    if scope.default_whole_grant:
        return _refuse(principal_id, StepFailed.mcp_authorization, "whole_grant_refused")

    # Step 4 — Google authorization
    if mint_credentials is not None:
        mint_credentials()

    raw_lookup = parent_lookup or (lambda _fid: None)

    def lookup(fid: str) -> list[str] | None:
        try:
            return raw_lookup(fid)
        except GoogleApiError as exc:
            raise DomainError(map_google_error(exc)) from exc

    def _get(fid: str) -> Any:
        if get_metadata is None:
            raise DomainError.of(ErrorCategory.DRIVE_API_ERROR)
        try:
            return get_metadata(fid)
        except GoogleApiError as exc:
            raise DomainError(map_google_error(exc)) from exc

    named_files = list(scope.file_ids or [])
    try:
        # Allow-list first. An id that is not proven to be the allow-list
        # folder or a descendant is refused the same way whether or not
        # Google grants it, so the reply does not reveal that it exists.
        allow_scope = RetrievalScope(folder_id=allowed)
        check_ids = list(named_files)
        if scope.folder_id:
            check_ids.append(scope.folder_id)
        for fid in check_ids:
            if not is_within_scope(fid, allow_scope, lookup):
                return _refuse(
                    principal_id, StepFailed.google_authorization, "outside_allowed_folder"
                )

        if named_files:
            for fid in named_files:
                _get(fid)
            if scope.folder_id:
                _get(scope.folder_id)
                for fid in named_files:
                    if not is_within_scope(fid, scope, lookup):
                        return _refuse(
                            principal_id, StepFailed.google_authorization, "file_outside_folder"
                        )
        else:
            _get(scope.folder_id)
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


def _refuse(principal_id: str, step: StepFailed, reason_code: str) -> AuthorizationDecision:
    return AuthorizationDecision(
        outcome=DecisionOutcome.AUTHORIZATION_ERROR,
        step_failed=step,
        reason_code=reason_code,
        principal_id=principal_id,
    )
