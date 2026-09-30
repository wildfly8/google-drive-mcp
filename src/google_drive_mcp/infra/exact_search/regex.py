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
    skip: int = 0,
) -> list[RawMatch]:
    """Up to ``remaining`` matches after the first ``skip``.

    Skipped matches are only counted, never built, so a deep continuation
    cursor costs time proportional to the matches passed over, not memory.
    """
    try:
        if line_oriented:
            return _line_matches(text, compiled, context_lines, remaining, skip)
        return _window_matches(text, compiled, remaining, skip)
    except re.error as exc:
        raise DomainError.of(ErrorCategory.SEARCH_ERROR) from exc
    except RecursionError as exc:
        raise DomainError.of(ErrorCategory.SEARCH_ERROR) from exc


def _line_matches(
    text: str, compiled: re.Pattern[str], context_lines: int, remaining: int, skip: int = 0
) -> list[RawMatch]:
    """One match per matching line; further hits on that line only raise occurrences.

    The context always holds the whole line, so a second hit on it would spend
    another max_matches slot on text the caller already has.
    """
    lines = text.splitlines()
    found: list[RawMatch] = []
    skipped = 0
    for index, line in enumerate(lines):
        if skipped < skip:
            if compiled.search(line) is not None:
                skipped += 1
            continue
        first: re.Match[str] | None = None
        occurrences = 0
        for match in compiled.finditer(line):
            if first is None:
                first = match
            occurrences += 1
        if first is None:
            continue
        start = max(0, index - context_lines)
        end = min(len(lines), index + context_lines + 1)
        found.append(
            RawMatch(
                matched_text=first.group(0),
                location={
                    "line": index + 1,
                    "offset": first.start(),
                    "occurrences": occurrences,
                },
                context="\n".join(lines[start:end]),
            )
        )
        if len(found) >= remaining:
            return found
    return found


def _window_matches(
    text: str, compiled: re.Pattern[str], remaining: int, skip: int = 0
) -> list[RawMatch]:
    found: list[RawMatch] = []
    skipped = 0
    for match in compiled.finditer(text):
        if skipped < skip:
            skipped += 1
            continue
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
