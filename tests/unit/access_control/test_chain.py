"""Chain order, no reused ALLOW, is_within_scope with injected parent map."""

from __future__ import annotations

import inspect

import pytest

from google_drive_mcp.access_control.chain import evaluate_chain
from google_drive_mcp.access_control.decisions import DecisionOutcome, StepFailed
from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.domain.retrieval_scope import RetrievalScope, is_within_scope


def test_evaluate_chain_does_not_accept_document_content_parameter():
    params = inspect.signature(evaluate_chain).parameters
    assert "content" not in params
    assert "document" not in params
    assert "body" not in params
    assert "rationale" not in params


def test_authn_failure_never_calls_google():
    calls: list[str] = []

    def get_metadata(_fid: str):
        calls.append("google")
        raise AssertionError("google must not run")

    decision = evaluate_chain(
        authorization=None,
        expected_token="test-token",
        principal_id="deployment-1",
        file_id="nested-doc",
        get_metadata=get_metadata,
    )
    assert decision.outcome == DecisionOutcome.AUTHENTICATION_ERROR
    assert decision.step_failed == StepFailed.mcp_authentication
    assert calls == []


def test_prior_allow_is_not_reused():
    parents = {"child": ["folder"], "folder": ["root"]}
    gets = []

    def get_metadata(fid: str):
        gets.append(fid)
        return {"id": fid, "parents": parents.get(fid, [])}

    first = evaluate_chain(
        authorization="Bearer test-token",
        expected_token="test-token",
        principal_id="deployment-1",
        file_id="child",
        get_metadata=get_metadata,
        parent_lookup=lambda fid: parents.get(fid),
    )
    assert first.allowed
    second = evaluate_chain(
        authorization="Bearer other",
        expected_token="test-token",
        principal_id="deployment-1",
        file_id="child",
        get_metadata=get_metadata,
        parent_lookup=lambda fid: parents.get(fid),
    )
    assert second.outcome == DecisionOutcome.AUTHENTICATION_ERROR
    assert gets == ["child"]


def test_is_within_scope_uses_injected_parent_map_not_drive():
    parents = {
        "doc": ["folder-a"],
        "folder-a": ["root"],
        "other": ["elsewhere"],
    }

    def lookup(fid: str) -> list[str] | None:
        return parents.get(fid)

    folder_scope = RetrievalScope(folder_id="folder-a")
    assert is_within_scope("doc", folder_scope, lookup)
    assert is_within_scope("folder-a", folder_scope, lookup)
    assert not is_within_scope("other", folder_scope, lookup)

    intersection = RetrievalScope(folder_id="folder-a", file_ids=["other"])
    assert not is_within_scope("other", intersection, lookup)

    whole = RetrievalScope.default_whole_grant_scope()
    assert is_within_scope("other", whole, lookup)


def test_google_500_during_chain_is_drive_api_error():
    from google_drive_mcp.domain.errors import DomainError, ErrorCategory

    def get_metadata(_fid: str):
        raise GoogleApiError(500)

    with pytest.raises(DomainError) as caught:
        evaluate_chain(
            authorization="Bearer test-token",
            expected_token="test-token",
            principal_id="deployment-1",
            file_id="nested-doc",
            get_metadata=get_metadata,
        )
    assert caught.value.error.category == ErrorCategory.DRIVE_API_ERROR


def test_google_500_via_handle_tool_is_drive_api_error(runtime, fake_drive):
    from google_drive_mcp.mcp.tools import handle_tool

    def boom(_fid: str):
        raise GoogleApiError(500)

    fake_drive.get_metadata = boom  # type: ignore[method-assign]
    result = handle_tool(
        runtime, "drive_read", {"file_id": "nested-doc"}, "Bearer test-token"
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "DRIVE_API_ERROR"


def test_google_miss_on_named_file_is_file_not_found():
    def get_metadata(_fid: str):
        raise GoogleApiError(404)

    decision = evaluate_chain(
        authorization="Bearer test-token",
        expected_token="test-token",
        principal_id="deployment-1",
        file_id="missing",
        get_metadata=get_metadata,
    )
    assert decision.outcome == DecisionOutcome.FILE_NOT_FOUND
    assert decision.step_failed == StepFailed.google_authorization
