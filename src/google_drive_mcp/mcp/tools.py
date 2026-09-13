"""MCP tool registration. Mounted from server.py through access-control middleware.

Structural read-only guarantee: only drive_ls, drive_find, drive_read, drive_grep
are registered. No mutating tools exist.
"""

from __future__ import annotations

import time
from typing import Any

from google_drive_mcp.domain.errors import DomainError, ErrorCategory, envelope
from google_drive_mcp.domain.retrieval_scope import apply_allowed_folder
from google_drive_mcp.infra.logging import log_chain_event, log_retrieval
from google_drive_mcp.infra.mcp_auth.tokens import verify_authorization_header
from google_drive_mcp.mcp.middleware import Runtime, new_request_id, run_with_chain
from google_drive_mcp.retrieval.find import drive_find, validate_find_args
from google_drive_mcp.retrieval.grep import drive_grep, validate_grep_args
from google_drive_mcp.retrieval.ls import drive_ls, validate_ls_args
from google_drive_mcp.retrieval.read import drive_read, validate_read_args

READ_ONLY_TOOLS = ("drive_ls", "drive_find", "drive_read", "drive_grep")
SCOPE_PROBE = "scope_probe"


def handle_tool(
    runtime: Runtime,
    name: str,
    arguments: dict[str, Any] | None,
    authorization: str | None,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    args = dict(arguments or {})
    started = time.monotonic()
    rid = request_id or new_request_id()
    request_id = rid
    apply_allowed_folder(args, runtime.settings.drive_allowed_folder_id)
    if not verify_authorization_header(authorization, runtime.settings):
        log_chain_event(
            request_id=rid,
            principal_id=runtime.settings.mcp_principal_id,
            step_failed="mcp_authentication",
            category="AUTHENTICATION_ERROR",
        )
        return envelope(ErrorCategory.AUTHENTICATION_ERROR, request_id=rid).to_dict()
    try:
        if name == "drive_ls":
            validate_ls_args(args)
        elif name == "drive_find":
            validate_find_args(args)
        elif name == "drive_read":
            validate_read_args(args)
        elif name == "drive_grep":
            validate_grep_args(args)
    except DomainError as exc:
        err = exc.error
        if err.request_id is None:
            err = envelope(err.category, message=err.message, request_id=rid)
        return err.to_dict()

    def body() -> dict[str, Any]:
        if name == SCOPE_PROBE:
            return {"status": "COMPLETE", "ok": True}
        drive = runtime.active_drive()
        if name == "drive_ls":
            validate_ls_args(args)
            return drive_ls(
                drive,
                folder_id=args.get("folder_id"),
                max_results=args.get("max_results"),
                page_token=args.get("page_token"),
                request_id=request_id,
            )
        if name == "drive_find":
            validate_find_args(args)
            return drive_find(
                drive,
                name_pattern=args.get("name_pattern"),
                mime_type=args.get("mime_type"),
                folder_id=args.get("folder_id"),
                modified_after=args.get("modified_after"),
                modified_before=args.get("modified_before"),
                trashed=bool(args.get("trashed", False)),
                max_results=args.get("max_results"),
                request_id=request_id,
            )
        if name == "drive_read":
            validate_read_args(args)
            return drive_read(
                drive,
                file_id=args["file_id"],
                content_format=args.get("content_format"),
                max_bytes=args.get("max_bytes"),
                request_id=request_id,
            )
        if name == "drive_grep":
            validate_grep_args(args)
            return drive_grep(
                drive,
                pattern=args["pattern"],
                file_ids=args.get("file_ids"),
                folder_id=args.get("folder_id"),
                case_sensitive=args.get("case_sensitive", True),
                regex=args.get("regex", False),
                context_lines=args.get("context_lines", 2),
                max_matches=args.get("max_matches"),
                request_id=request_id,
            )
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)

    result = run_with_chain(
        runtime, args, body, authorization=authorization, request_id=request_id
    )
    duration_ms = (time.monotonic() - started) * 1000
    status = result.get("status", "ERROR")
    result_count = (
        len(result.get("children") or [])
        + len(result.get("candidates") or [])
        + len(result.get("matches") or [])
        + (1 if result.get("content") is not None else 0)
    )
    log_retrieval(
        request_id=request_id or "",
        tool=name,
        file_count=result_count if name != "drive_read" else 1,
        bytes_processed=len(result["content"].encode()) if isinstance(result.get("content"), str) else 0,
        duration_ms=duration_ms,
        result_count=result_count,
        status=status,
        error_category=result.get("category") if status == "ERROR" else None,
    )
    return result
