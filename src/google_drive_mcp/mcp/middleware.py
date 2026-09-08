"""MCP middleware: run the authorization chain before any tool body."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from google_drive_mcp.access_control.chain import evaluate_chain
from google_drive_mcp.access_control.decisions import AuthorizationDecision
from google_drive_mcp.domain.errors import DomainError, ErrorCategory, ErrorEnvelope
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.google_auth.refresh_token import mint_readonly_credentials
from google_drive_mcp.infra.logging import log_chain_event

_authorization: ContextVar[str | None] = ContextVar("mcp_authorization", default=None)
_request_id: ContextVar[str] = ContextVar("mcp_request_id", default="")
_request_drive: ContextVar[Any] = ContextVar("mcp_request_drive", default=None)


def set_authorization(value: str | None) -> None:
    _authorization.set(value)


def get_authorization() -> str | None:
    return _authorization.get()


def current_request_id() -> str:
    rid = _request_id.get()
    if rid:
        return rid
    rid = str(uuid4())
    _request_id.set(rid)
    return rid


def new_request_id() -> str:
    rid = str(uuid4())
    _request_id.set(rid)
    return rid


def reset_request_drive() -> None:
    """Clear request-scoped Drive binding at the start of each HTTP request."""
    _request_drive.set(None)


class Runtime:
    """Composition-time dependencies. Production leaves `drive` unset so each
    request mints credentials and builds a GoogleDriveClient in this request's
    context. Tests inject a FakeDrive.
    """

    def __init__(self, settings: Settings, drive: Any | None = None) -> None:
        self.settings = settings
        self.drive = drive

    def bind_request_drive(self) -> Any:
        """Mint request-scoped credentials and bind the Drive port used for I/O."""
        creds = mint_readonly_credentials(self.settings)
        if self.drive is not None:
            _request_drive.set(self.drive)
            return self.drive
        from google_drive_mcp.infra.google_drive.client import GoogleDriveClient

        client = GoogleDriveClient(creds)
        _request_drive.set(client)
        return client

    def mint_and_bind(self) -> object:
        """Called only after MCP authentication passes."""
        from google_drive_mcp.infra.google_auth.refresh_token import current_credentials

        self.bind_request_drive()
        return current_credentials()

    def active_drive(self) -> Any:
        return _request_drive.get() or self.drive


def authorize(
    runtime: Runtime,
    arguments: dict[str, Any],
    authorization: str | None = None,
    request_id: str | None = None,
) -> AuthorizationDecision:
    rid = request_id or new_request_id()
    auth = authorization if authorization is not None else get_authorization()

    def get_metadata(file_id: str) -> Any:
        drive = runtime.active_drive()
        if drive is None:
            raise DomainError.of(ErrorCategory.DRIVE_API_ERROR)
        return drive.get_metadata(file_id)

    def parent_lookup(file_id: str) -> list[str] | None:
        drive = runtime.active_drive()
        if drive is None:
            return None
        return drive.parent_lookup(file_id)

    def mint() -> object:
        return runtime.mint_and_bind()

    decision = evaluate_chain(
        authorization=auth,
        expected_token=runtime.settings.mcp_auth_token.get_secret_value(),
        principal_id=runtime.settings.mcp_principal_id,
        folder_id=arguments.get("folder_id"),
        file_ids=arguments.get("file_ids"),
        file_id=arguments.get("file_id"),
        get_metadata=get_metadata,
        parent_lookup=parent_lookup,
        mint_credentials=mint,
    )
    if not decision.allowed:
        log_chain_event(
            request_id=rid,
            principal_id=runtime.settings.mcp_principal_id,
            step_failed=decision.step_failed.value if decision.step_failed else None,
            category=decision.outcome.value,
        )
    return decision


def run_with_chain(
    runtime: Runtime,
    arguments: dict[str, Any],
    body: Callable[[], dict[str, Any]],
    *,
    authorization: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    rid = request_id or new_request_id()
    try:
        decision = authorize(runtime, arguments, authorization=authorization, request_id=rid)
    except DomainError as exc:
        err = exc.error
        if err.request_id is None:
            err = ErrorEnvelope(
                category=err.category, message=err.message, request_id=rid
            )
        log_chain_event(
            request_id=rid,
            principal_id=runtime.settings.mcp_principal_id,
            step_failed="google_authorization",
            category=err.category.value,
        )
        return err.to_dict()
    if not decision.allowed:
        return decision.to_envelope(rid).to_dict()
    try:
        return body()
    except DomainError as exc:
        err = exc.error
        if err.request_id is None:
            err = ErrorEnvelope(
                category=err.category, message=err.message, request_id=rid
            )
        log_chain_event(
            request_id=rid,
            principal_id=runtime.settings.mcp_principal_id,
            step_failed=None,
            category=err.category.value,
        )
        return err.to_dict()
