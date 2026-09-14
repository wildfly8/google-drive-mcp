"""Regex adapter determinism."""

from __future__ import annotations

from google_drive_mcp.infra.exact_search.regex import compile_pattern, search_text


def test_same_bytes_and_flags_yield_identical_matches():
    compiled = compile_pattern("ab", regex=False, case_sensitive=True)
    text = "ab ab ab"
    first = search_text(text, compiled, line_oriented=True, context_lines=0, remaining=50)
    second = search_text(text, compiled, line_oriented=True, context_lines=0, remaining=50)
    assert [(m.matched_text, m.location) for m in first] == [
        (m.matched_text, m.location) for m in second
    ]
    assert len(first) == 3


def test_ignorecase_differs_from_sensitive():
    text = "Foo foo"
    sensitive = compile_pattern("Foo", regex=False, case_sensitive=True)
    insensitive = compile_pattern("Foo", regex=False, case_sensitive=False)
    a = search_text(text, sensitive, line_oriented=True, context_lines=0, remaining=10)
    b = search_text(text, insensitive, line_oriented=True, context_lines=0, remaining=10)
    assert len(a) == 1
    assert len(b) == 2
