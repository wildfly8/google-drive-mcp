"""Advertised MCP tools/list schemas: descriptions, bounds, read-only hints."""

from __future__ import annotations

from google_drive_mcp.mcp.server import create_server
from google_drive_mcp.mcp.tool_schema import SERVER_INSTRUCTIONS
from google_drive_mcp.mcp.tools import READ_ONLY_TOOLS
from google_drive_mcp.mcp.validation import (
    CONTEXT_LINES_MAX,
    CONTEXT_LINES_MIN,
    FILE_ID_PATTERN,
    MAX_BYTES_MAX,
    MAX_BYTES_MIN,
    MAX_MATCHES_MAX,
    MAX_MATCHES_MIN,
    MAX_RESULTS_MAX,
    MAX_RESULTS_MIN,
)

REQUIRED_DESCRIPTION_MARKERS = (
    "When to use:",
    "When not to use:",
    "Example (do):",
    "Example (don't):",
)


def _schema_bounds(schema: dict, name: str) -> tuple[int | None, int | None]:
    prop = schema["properties"][name]
    arm = next((a for a in prop.get("anyOf", [prop]) if a.get("type") == "integer"), prop)
    return arm.get("minimum"), arm.get("maximum")


async def test_tools_list_is_exactly_the_read_only_surface(runtime):
    tools = await create_server(runtime).list_tools()
    names = [t.name for t in tools]
    assert names == list(READ_ONLY_TOOLS)
    for tool in tools:
        assert tool.description and tool.description.strip()
        for marker in REQUIRED_DESCRIPTION_MARKERS:
            assert marker in tool.description, f"{tool.name} missing {marker!r}"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is True


async def test_initialize_instructions_say_host_extracts_terms(runtime):
    server = create_server(runtime)
    text = server.instructions or ""
    assert text == SERVER_INSTRUCTIONS
    assert "never extracts keywords" in text
    assert "MCP OAuth 2.1" in text
    assert "does not implement MCP OAuth 2.1" not in text
    assert "natural-language" in SERVER_INSTRUCTIONS or "user question" in text


async def test_drive_ls_and_find_schema_bounds(runtime):
    by_name = {t.name: t for t in await create_server(runtime).list_tools()}
    ls = by_name["drive_ls"].input_schema
    find = by_name["drive_find"].input_schema
    assert _schema_bounds(ls, "max_results") == (MAX_RESULTS_MIN, MAX_RESULTS_MAX)
    assert _schema_bounds(find, "max_results") == (MAX_RESULTS_MIN, MAX_RESULTS_MAX)
    folder = ls["properties"]["folder_id"]
    folder_arm = next(a for a in folder["anyOf"] if a.get("type") == "string")
    assert folder_arm["pattern"] == FILE_ID_PATTERN
    assert "folder_id" in ls["properties"]
    assert "file_id" not in ls["properties"]
    assert "pattern" not in find["properties"]
    assert find["properties"]["name_pattern"]["description"]
    assert "not glob" in find["properties"]["name_pattern"]["description"]


async def test_drive_read_and_grep_required_fields_and_bounds(runtime):
    by_name = {t.name: t for t in await create_server(runtime).list_tools()}
    read = by_name["drive_read"].input_schema
    grep = by_name["drive_grep"].input_schema
    assert read["required"] == ["file_id"]
    assert grep["required"] == ["pattern"]
    assert read["properties"]["file_id"]["pattern"] == FILE_ID_PATTERN
    assert _schema_bounds(read, "max_bytes") == (MAX_BYTES_MIN, MAX_BYTES_MAX)
    assert _schema_bounds(grep, "max_matches") == (MAX_MATCHES_MIN, MAX_MATCHES_MAX)
    ctx_min, ctx_max = _schema_bounds(grep, "context_lines")
    assert (ctx_min, ctx_max) == (CONTEXT_LINES_MIN, CONTEXT_LINES_MAX)
    assert "whole question" in grep["properties"]["pattern"]["description"]
    assert "filename" in by_name["drive_find"].input_schema["properties"]["name_pattern"]["description"]
