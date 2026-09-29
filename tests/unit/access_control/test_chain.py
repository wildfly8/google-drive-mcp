"""Chain order, no reused ALLOW, is_within_scope with injected parent map."""

from __future__ import annotations

import inspect

import pytest

from google_drive_mcp.access_control.chain import evaluate_chain
from google_drive_mcp.access_control.decisions import DecisionOutcome, StepFailed
from google_drive_mcp.domain.google_errors import GoogleApiError
from google_drive_mcp.domain.retrieval_scope import RetrievalScope, is_within_scope
from google_drive_mcp.infra.mcp_auth.bearer import extract_bearer


def _folders(parents: dict[str, list[str]]):
    """list_subfolders over a {folder_id: parents} map."""

    def list_subfolders(parent_ids: list[str]) -> list[dict]:
        wanted = set(parent_ids)
        return [
            {"id": fid, "parents": list(ps)}
            for fid, ps in parents.items()
            if wanted.intersection(ps)
        ]

    return list_subfolders


def _accepts(*allowed: str):
    def verify(authorization: str | None) -> bool:
        return extract_bearer(authorization) in allowed

    return verify


def test_evaluate_chain_does_not_accept_document_content_parameter():
    params = inspect.signature(evaluate_chain).parameters
    assert "content" not in params
    assert "document" not in params
    assert "body" not in params
    assert "rationale" not in params
    assert "verify_caller" in params
    assert "expected_token" not in params


def test_authn_failure_never_calls_google():
    calls: list[str] = []

    def get_metadata(_fid: str):
        calls.append("google")
        raise AssertionError("google must not run")

    decision = evaluate_chain(
        authorization=None,
        verify_caller=_accepts("test-token"),
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
        verify_caller=_accepts("test-token"),
        principal_id="deployment-1",
        file_id="child",
        allowed_folder_id="root",
        get_metadata=get_metadata,
        list_subfolders=_folders({"folder": ["root"]}),
    )
    assert first.allowed
    second = evaluate_chain(
        authorization="Bearer other",
        verify_caller=_accepts("test-token"),
        principal_id="deployment-1",
        file_id="child",
        allowed_folder_id="root",
        get_metadata=get_metadata,
        list_subfolders=_folders({"folder": ["root"]}),
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
            verify_caller=_accepts("test-token"),
            principal_id="deployment-1",
            file_id="nested-doc",
            allowed_folder_id="root",
            get_metadata=get_metadata,
            list_subfolders=_folders({}),
        )
    assert caught.value.error.category == ErrorCategory.DRIVE_API_ERROR


def test_google_500_while_listing_the_allowed_tree_is_drive_api_error():
    from google_drive_mcp.domain.errors import DomainError, ErrorCategory

    def list_subfolders(_ids: list[str]):
        raise GoogleApiError(500)

    with pytest.raises(DomainError) as caught:
        evaluate_chain(
            authorization="Bearer test-token",
            verify_caller=_accepts("test-token"),
            principal_id="deployment-1",
            file_id="nested-doc",
            allowed_folder_id="root",
            get_metadata=lambda fid: {"id": fid, "parents": ["root"]},
            list_subfolders=list_subfolders,
        )
    assert caught.value.error.category == ErrorCategory.DRIVE_API_ERROR


def test_google_500_via_handle_tool_is_drive_api_error(runtime, fake_drive, authz):
    from google_drive_mcp.mcp.tools import handle_tool

    def boom(_fid: str):
        raise GoogleApiError(500)

    fake_drive.get_metadata = boom  # type: ignore[method-assign]
    result = handle_tool(
        runtime, "drive_read", {"file_id": "nested-doc"}, authz
    )
    assert result["status"] == "ERROR"
    assert result["category"] == "DRIVE_API_ERROR"


@pytest.mark.parametrize("status", [404, 403])
def test_google_miss_on_named_file_is_authorization_error(status: int):
    def get_metadata(_fid: str):
        raise GoogleApiError(status)

    decision = evaluate_chain(
        authorization="Bearer test-token",
        verify_caller=_accepts("test-token"),
        principal_id="deployment-1",
        file_id="missing",
        allowed_folder_id="root",
        get_metadata=get_metadata,
        list_subfolders=_folders({}),
    )
    assert decision.outcome == DecisionOutcome.AUTHORIZATION_ERROR
    assert decision.reason_code == "outside_allowed_folder"


def test_outside_missing_and_ungranted_ids_cost_the_same_drive_calls():
    folders = {"kb-sub": ["kb"], "kb-deep": ["kb-sub"], "finance": ["root"]}
    files = {"inside": ["kb-deep"], "outside": ["finance"], **folders}

    def run(named: str, deny: int | None = None) -> tuple[list, str]:
        calls: list = []

        def get_metadata(fid: str):
            calls.append("get")
            if deny is not None or fid not in files:
                raise GoogleApiError(deny or 404)
            return {"id": fid, "parents": files[fid]}

        lister = _folders(folders)

        def list_subfolders(ids: list[str]):
            calls.append(("list", tuple(sorted(ids))))
            return lister(ids)

        decision = evaluate_chain(
            authorization="Bearer test-token",
            verify_caller=_accepts("test-token"),
            principal_id="deployment-1",
            file_id=named,
            allowed_folder_id="kb",
            get_metadata=get_metadata,
            list_subfolders=list_subfolders,
        )
        return calls, decision.outcome

    outside = run("outside")
    missing = run("no-such-id")
    ungranted = run("outside", deny=403)
    inside = run("inside")
    assert outside == missing == ungranted
    assert outside[1] == DecisionOutcome.AUTHORIZATION_ERROR
    assert inside == (outside[0], DecisionOutcome.ALLOW)
    listed = {pid for call in outside[0] if call != "get" for pid in call[1]}
    assert listed <= {"kb", "kb-sub", "kb-deep"}


@pytest.mark.parametrize("allowed", [None, "", "   "])
def test_no_allow_list_refuses_before_google(allowed):
    calls: list[str] = []

    def get_metadata(fid: str):
        calls.append(fid)
        return {"id": fid}

    def mint():
        calls.append("mint")

    for scope in ({}, {"folder_id": "folder-a"}, {"file_id": "nested-doc"}):
        decision = evaluate_chain(
            authorization="Bearer test-token",
            verify_caller=_accepts("test-token"),
            principal_id="deployment-1",
            allowed_folder_id=allowed,
            get_metadata=get_metadata,
            list_subfolders=_folders({"folder-a": ["root"]}),
            mint_credentials=mint,
            **scope,
        )
        assert decision.outcome == DecisionOutcome.AUTHORIZATION_ERROR
        assert decision.reason_code == "no_allowed_folder"
    assert calls == []
