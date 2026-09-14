"""Exact-search adapter: stdlib re, literal vs regex, optional IGNORECASE."""

from __future__ import annotations

import re
from dataclasses import dataclass

from google_drive_mcp.domain.errors import DomainError, ErrorCategory

WINDOW_CHARS = 200


@dataclass(frozen=True)
class RawMatch:
    matched_text: str
    location: dict
    context: str | None


def compile_pattern(pattern: str, *, regex: bool, case_sensitive: bool) -> re.Pattern[str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    source = pattern if regex else re.escape(pattern)
    try:
        return re.compile(source, flags)
    except re.error as exc:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT) from exc


def search_text(
    text: str,
    compiled: re.Pattern[str],
    *,
    line_oriented: bool,
    context_lines: int,
    remaining: int,
) -> list[RawMatch]:
    try:
        if line_oriented:
            return _line_matches(text, compiled, context_lines, remaining)
        return _window_matches(text, compiled, remaining)
    except re.error as exc:
        raise DomainError.of(ErrorCategory.SEARCH_ERROR) from exc
    except RecursionError as exc:
        raise DomainError.of(ErrorCategory.SEARCH_ERROR) from exc


def _line_matches(
    text: str, compiled: re.Pattern[str], context_lines: int, remaining: int
) -> list[RawMatch]:
    lines = text.splitlines()
    found: list[RawMatch] = []
    for index, line in enumerate(lines):
        for match in compiled.finditer(line):
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            context = "\n".join(lines[start:end])
            found.append(
                RawMatch(
                    matched_text=match.group(0),
                    location={"line": index + 1, "offset": match.start()},
                    context=context,
                )
            )
            if len(found) >= remaining:
                return found
    return found


def _window_matches(text: str, compiled: re.Pattern[str], remaining: int) -> list[RawMatch]:
    found: list[RawMatch] = []
    for match in compiled.finditer(text):
        lo = max(0, match.start() - WINDOW_CHARS)
        hi = min(len(text), match.end() + WINDOW_CHARS)
        found.append(
            RawMatch(
                matched_text=match.group(0),
                location={"offset": match.start()},
                context=text[lo:hi],
            )
        )
        if len(found) >= remaining:
            return found
    return found
