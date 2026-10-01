"""Regex adapter determinism, regex timeouts, and stdlib re parity."""

from __future__ import annotations

import re
import time

import pytest
import regex

from google_drive_mcp.domain.errors import DomainError, ErrorCategory
from google_drive_mcp.infra.exact_search.regex import compile_pattern, search_text


def test_same_bytes_and_flags_yield_identical_matches():
    compiled = compile_pattern("ab", regex=False, case_sensitive=True)
    text = "ab ab ab"
    first = search_text(text, compiled, line_oriented=True, context_lines=0, remaining=50)
    second = search_text(text, compiled, line_oriented=True, context_lines=0, remaining=50)
    assert [(m.matched_text, m.location) for m in first] == [
        (m.matched_text, m.location) for m in second
    ]
    assert len(first) == 1
    assert first[0].location == {"line": 1, "offset": 0, "occurrences": 3}


def test_ignorecase_differs_from_sensitive():
    text = "Foo foo"
    sensitive = compile_pattern("Foo", regex=False, case_sensitive=True)
    insensitive = compile_pattern("Foo", regex=False, case_sensitive=False)
    a = search_text(text, sensitive, line_oriented=True, context_lines=0, remaining=10)
    b = search_text(text, insensitive, line_oriented=True, context_lines=0, remaining=10)
    assert [m.location["occurrences"] for m in a] == [1]
    assert [m.location["occurrences"] for m in b] == [2]


def _bait_text(bait_lines: int, *, before: str = "") -> str:
    """A few hundred KB: optional lines, then lines (a|aa)+$ is exponential on, then prose."""
    bait = ["a" * 30 + "b"] * bait_lines
    prose = ["plain prose line without the bait"] * 9000
    return "\n".join(([before] if before else []) + bait + prose)


def _search_until_timeout(text: str, compiled, *, line_oriented: bool, timeout: float) -> list:
    from google_drive_mcp.infra.exact_search.regex import SearchTimeout

    started = time.monotonic()
    with pytest.raises(SearchTimeout) as caught:
        search_text(
            text,
            compiled,
            line_oriented=line_oriented,
            context_lines=0,
            remaining=50,
            timeout=timeout,
        )
    assert time.monotonic() - started < 3
    return caught.value.found


def test_regex_mode_runs_on_the_regex_package_and_literal_mode_on_stdlib_re():
    assert isinstance(compile_pattern("a+", regex=True, case_sensitive=True), regex.Pattern)
    assert isinstance(compile_pattern("a+", regex=False, case_sensitive=True), re.Pattern)


def test_catastrophic_regex_stops_at_the_timeout_and_keeps_finished_lines():
    text = _bait_text(8, before="aaaa\nzz aa")
    assert len(text) > 300_000
    compiled = compile_pattern("(a|aa)+$", regex=True, case_sensitive=True)
    found = _search_until_timeout(text, compiled, line_oriented=True, timeout=0.3)
    assert [m.location["line"] for m in found] == [1, 2]


def test_catastrophic_regex_stops_at_the_timeout_in_text_without_lines():
    text = "x1 x2 x3\n" + _bait_text(8)
    compiled = compile_pattern(r"x\d|(a|aa)+$", regex=True, case_sensitive=True)
    found = _search_until_timeout(text, compiled, line_oriented=False, timeout=0.3)
    assert [m.matched_text for m in found] == ["x1", "x2", "x3"]


def test_reported_redos_patterns_return_within_seconds_over_a_few_hundred_kb():
    from google_drive_mcp.infra.exact_search.regex import SearchTimeout

    # On stdlib re each of these ran for hours on one such line, holding the GIL.
    text = "\n".join(["word " * 40, "a" * 40 + "!"] * 2500)
    assert len(text) > 300_000
    for pattern in (r"(\w+\s?)+:", r"(a+)+$"):
        compiled = compile_pattern(pattern, regex=True, case_sensitive=True)
        for line_oriented in (True, False):
            started = time.monotonic()
            try:
                search_text(
                    text,
                    compiled,
                    line_oriented=line_oriented,
                    context_lines=0,
                    remaining=50,
                    timeout=1.0,
                )
            except SearchTimeout:
                pass
            assert time.monotonic() - started < 3, (pattern, line_oriented)


def test_a_spent_timeout_stops_before_matching():
    compiled = compile_pattern("a", regex=True, case_sensitive=True)
    # The regex package reads a negative timeout as none; ours stops instead.
    for timeout in (0.0, -1.0):
        found = _search_until_timeout("a\na", compiled, line_oriented=True, timeout=timeout)
        assert found == []


def test_regex_package_matches_like_stdlib_re():
    text = (
        "Foo bar 123 baz\nidempotency widgets Widgets\nÉcole école\n\n"
        "key=value; other=thing\ttabbed\nend foo"
    )
    patterns = [
        r"\d+",
        "foo|baz",
        r"\bwid\w+",
        "(?:é|É)cole",
        "^$",
        r"\w*",
        "o*",
        "[a-z]+",
        r"(\w+)=(\w+)",
        r"^end\b",
        r"\s",
        "widgets$",
        "(?i)FOO",
    ]
    for pattern in patterns:
        for case_sensitive in (True, False):
            ours = compile_pattern(pattern, regex=True, case_sensitive=case_sensitive)
            stdlib = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
            for line_oriented in (True, False):
                kwargs = {"line_oriented": line_oriented, "context_lines": 1, "remaining": 50}
                got = search_text(text, ours, timeout=5.0, **kwargs)
                assert got == search_text(text, stdlib, **kwargs), (pattern, case_sensitive)


def test_regex_syntax_stdlib_re_rejects_is_invalid_argument():
    # The regex package gives some of these a meaning; the accepted syntax stays re's.
    for pattern in ("[", "(?i", "a**", r"\p{L}", "x(?i)y", "a{99999999999}"):
        with pytest.raises(DomainError) as caught:
            compile_pattern(pattern, regex=True, case_sensitive=True)
        assert caught.value.error.category == ErrorCategory.INVALID_ARGUMENT, pattern


def test_regex_whose_repeats_unroll_too_far_is_invalid_argument():
    from google_drive_mcp.infra.exact_search.regex import MAX_UNROLLED_UNITS

    # The regex package writes out minimum repeats when it compiles; the first
    # of these would need terabytes.
    too_big = ("(?:a{65535}){65535}", "(?:ab{100}){100}", f"a{{{MAX_UNROLLED_UNITS + 1}}}")
    for pattern in too_big:
        with pytest.raises(DomainError) as caught:
            compile_pattern(pattern, regex=True, case_sensitive=True)
        assert caught.value.error.category == ErrorCategory.INVALID_ARGUMENT, pattern
    fine = (r"\d{4}-\d{2}-\d{2}", r"(?:\d{1,3}\.){3}\d{1,3}", "x{0,65535}")
    for pattern in (*fine, f"a{{{MAX_UNROLLED_UNITS}}}"):
        compile_pattern(pattern, regex=True, case_sensitive=True)
