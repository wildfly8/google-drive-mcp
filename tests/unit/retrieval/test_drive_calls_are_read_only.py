"""Article V as an allowlist: the Drive adapter makes read calls and nothing else.

test_readonly_drive_adapter names four write calls and passes for any it does not name
(files().copy, emptyTrash, comments, revisions, drives, a raw HTTP DELETE). These tests
name the read calls instead, so any other call to Drive fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path("src/google_drive_mcp")
ADAPTER = SRC / "infra" / "google_drive"

# The only Drive API calls the server may make: metadata, listing, export, download.
READ_CALLS = {
    ("files", "get"),
    ("files", "list"),
    ("files", "export"),
    ("files", "get_media"),
}
# Every resource of the Drive v3 API. A call on any of them that is not in READ_CALLS fails,
# however the service object was reached (self._service, a local alias, a fresh build()).
DRIVE_RESOURCES = {
    "about",
    "accessproposals",
    "apps",
    "approvals",
    "changes",
    "channels",
    "comments",
    "drives",
    "files",
    "operations",
    "permissions",
    "replies",
    "revisions",
    "teamdrives",
}
HTTP_WRITE_METHODS = {"DELETE", "PATCH", "POST", "PUT"}
RAW_HTTP_CALLS = {"delete", "patch", "post", "put", "request", "send"}


def _trees(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def _resource_calls(tree: ast.AST):
    """(resource, verb) for every <expr>.<resource>().<verb>(...) in the tree."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Attribute)
            and node.func.value.func.attr in DRIVE_RESOURCES
        ):
            yield node.func.value.func.attr, node.func.attr


def test_the_adapter_calls_only_read_endpoints():
    seen: set[tuple[str, str]] = set()
    for _path, tree in _trees(SRC):
        seen |= set(_resource_calls(tree))
    assert seen, "the scan found no Drive calls at all, so it is not looking at the adapter"
    assert seen <= READ_CALLS, f"Drive calls outside the read allowlist: {sorted(seen - READ_CALLS)}"


def test_the_allowlist_covers_what_the_adapter_really_uses():
    """Guards the scan itself: if the adapter stopped using a call, the list is stale."""
    seen: set[tuple[str, str]] = set()
    for _path, tree in _trees(SRC):
        seen |= set(_resource_calls(tree))
    assert seen == READ_CALLS


def test_only_the_adapter_builds_a_drive_service():
    for path, tree in _trees(SRC):
        if ADAPTER in path.parents:
            continue
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            assert not any(m.split(".")[0] == "googleapiclient" for m in modules), (
                f"{path} reaches the Google API client outside the Drive adapter"
            )


def test_the_adapter_makes_no_raw_http_writes():
    """A hand-built request to the Drive API would skip the call allowlist above."""
    for path, tree in _trees(ADAPTER):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in RAW_HTTP_CALLS, (
                    f"{path}:{node.lineno} calls .{node.func.attr}() directly"
                )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value.upper() not in HTTP_WRITE_METHODS, (
                    f"{path}:{node.lineno} names the HTTP method {node.value}"
                )
            if isinstance(node, ast.keyword):
                assert node.arg != "method", f"{path}:{node.value.lineno} passes method="
