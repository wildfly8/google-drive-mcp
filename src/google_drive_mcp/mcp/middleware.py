"""MCP middleware: run the authorization chain before any tool body."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from google_drive_mcp.access_control.chain import evaluate_chain
from google_drive_mcp.access_control.decisions import AuthorizationDecision
from google_drive_mcp.domain.errors import DomainError, ErrorEnvelope
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.google_auth.refresh_token import mint_readonly_credentials
from google_drive_mcp.infra.logging import log_chain_event

_authorization: ContextVar[str | None] = ContextVar("mcp_authorization", default=None)
_request_id: ContextVar[str] = ContextVar("mcp_request_id", default="")


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


class Runtime:
    """Composition-time dependencies for one server instance (Drive port is injected)."""

    def __init__(self, settings: Settings, drive: Any) -> None:
        self.settings = settings
        self.drive = drive


def authorize(
    runtime: Runtime,
    arguments: dict[str, Any],
    authorization: str | None = None,
    request_id: str | None = None,
) -> AuthorizationDecision:
    rid = request_id or new_request_id()
    auth = authorization if authorization is not None else get_authorization()
    drive = runtime.drive

    def get_metadata(file_id: str) -> Any:
        return drive.get_metadata(file_id)

    def parent_lookup(file_id: str) -> list[str] | None:
        return drive.parent_lookup(file_id)

    def mint() -> object:
        return mint_readonly_credentials(runtime.settings)

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
    decision = authorize(runtime, arguments, authorization=authorization, request_id=rid)
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
