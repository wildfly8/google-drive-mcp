"""Advertised MCP tools/list schemas: descriptions, bounds, read-only hints."""

from __future__ import annotations

from google_drive_mcp.mcp.server import create_server
from google_drive_mcp.mcp.tool_schema import CITING_RULE, SERVER_INSTRUCTIONS
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


def _string_description(schema: dict, name: str) -> str:
    prop = schema["properties"][name]
    parts = [prop.get("description") or ""]
    for arm in prop.get("anyOf", []):
        parts.append(arm.get("description") or "")
    return " ".join(parts)


def _schema_bounds(schema: dict, name: str) -> tuple[int | None, int | None]:
    prop = schema["properties"][name]
    arm = next((a for a in prop.get("anyOf", [prop]) if a.get("type") == "integer"), prop)
    return arm.get("minimum"), arm.get("maximum")


def _array_item_schema(schema: dict, name: str) -> dict:
    prop = schema["properties"][name]
    arm = next((a for a in prop.get("anyOf", [prop]) if a.get("type") == "array"), prop)
    return arm["items"]


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
        # Closed world: one private folder (kb), not the open web.
        assert tool.annotations.open_world_hint is False


async def test_initialize_instructions_say_host_extracts_terms(runtime):
    server = create_server(runtime)
    text = server.instructions or ""
    assert text == SERVER_INSTRUCTIONS
    assert "never extracts keywords" in text
    assert "MCP OAuth 2.1" in text
    assert "initialize" in text and "tools/list" in text
    assert "does not implement MCP OAuth 2.1" not in text
    assert "natural-language" in SERVER_INSTRUCTIONS or "user question" in text
    assert "No folder is disallowed" not in text
    assert "only folder this server may read is kb" in text
    assert "AUTHORIZATION_ERROR" in text
    assert "Never pass tokens" in text
    # The consent password is an operator secret; hosts never need its name.
    assert "MCP_AUTH_TOKEN" not in text


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
    for tool_name in ("drive_ls", "drive_find"):
        folder_text = _string_description(by_name[tool_name].input_schema, "folder_id")
        assert "disallowed" not in folder_text.lower()
        assert "kb" in folder_text


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
    assert _array_item_schema(grep, "file_ids")["pattern"] == FILE_ID_PATTERN
    assert grep["properties"]["next_cursor"]["type"] == "string"
    assert "next_cursor" in grep["properties"]["next_cursor"]["description"]
    assert grep["properties"]["cursor"]["type"] == "string"
    assert "next_cursor" in grep["properties"]["cursor"]["description"]
    assert "deferred_file_ids" in by_name["drive_grep"].description
    assert "next_cursor" in by_name["drive_grep"].description
    grep_folder = _string_description(grep, "folder_id")
    assert "disallowed" not in grep_folder.lower()
    assert "kb" in grep_folder


async def test_answers_cite_onto_kb_in_one_line_only(runtime):
    # Owner decision (constitution v2.1.0, Article VIII): the final answer names
    # the connector once and lists no separate file references; text quoted word
    # for word from Stack Exchange keeps its CC BY-SA link.
    text = create_server(runtime).instructions or ""
    assert "exactly one line at the end of the answer: Source: onto-kb connector" in text
    assert "Do not list, number or link separate references" in text
    assert "quotes Stack Exchange text word for word" in text
    assert "CC BY-SA 4.0 and must be attributed" in text
    assert "for your own tracking only" in text
    assert "That line is the only source you name" in text
    assert "Do not add a Sources or References section" in text
    for tool in await create_server(runtime).list_tools():
        assert CITING_RULE in tool.description, tool.name
        assert "Source: onto-kb connector" in tool.description, tool.name
        assert "no Sources or References section" in tool.description, tool.name
        assert "never list, number or link file names or ids" in tool.description, tool.name
        assert "One exception: a Stack Exchange link beside text quoted word for word" in (
            tool.description
        ), tool.name


async def test_tool_texts_do_not_advertise_a_source_link(runtime):
    # Results carry no source_url or drive: locator (owner decision, 2026-10-05).
    server = create_server(runtime)
    texts = [server.instructions or ""] + [t.description for t in await server.list_tools()]
    for text in texts:
        assert "source_url" not in text
        assert "drive:" not in text
        assert "locator" not in text


# Claude Code clips a tool description at 4,096 characters; it cut the rule off the end of
# drive_grep's, and the answer then listed file names and drive: locators as sources.
HOST_DESCRIPTION_CLIP = 4096


async def test_citing_rule_leads_the_instructions_and_every_description(runtime):
    server = create_server(runtime)
    instructions = server.instructions or ""
    assert instructions.index("Source: onto-kb connector") < 400
    # The whole rule, exception included, sits before the authentication text.
    assert instructions.index("Paraphrase needs no link.") < instructions.index("Authentication")
    assert instructions.count("Source: onto-kb connector") == 1
    for tool in await server.list_tools():
        text = tool.description
        purpose, rule, _details = text.split("\n\n", 2)
        assert "\n" not in purpose and len(purpose) < 150, tool.name
        assert rule == CITING_RULE, tool.name
        # A host that keeps only the first kilobyte still keeps the rule.
        assert CITING_RULE in text[:1024], tool.name
        # Nothing long enough to be clipped, so the result format arrives too.
        assert len(text) <= HOST_DESCRIPTION_CLIP - 100, f"{tool.name}: {len(text)} characters"
