"""Exact-search adapter: stdlib re for literals, the regex package for regex=true.

A literal cannot backtrack, so it keeps stdlib re. A regular expression runs on
the regex package, whose matching takes a timeout, so a pattern such as
(a|aa)+$ cannot hold a worker past the call's time budget.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from re import _parser as re_parser

import regex as regex_engine

from google_drive_mcp.domain.errors import DomainError, ErrorCategory

WINDOW_CHARS = 200
# The regex package writes out the minimum of every repeat when it compiles
# (about 270 bytes each), so (?:a{65535}){65535} would need terabytes.
MAX_UNROLLED_UNITS = 10_000

_REPEATS = (re_parser.MAX_REPEAT, re_parser.MIN_REPEAT, re_parser.POSSESSIVE_REPEAT)


@dataclass(frozen=True)
class RawMatch:
    matched_text: str
    location: dict
    context: str | None


class SearchTimeout(TimeoutError):
    """The regex ran out of time; ``found`` holds the matches finished before that."""

    def __init__(self, found: list[RawMatch]) -> None:
        super().__init__("regex search timed out")
        self.found = found


def compile_pattern(
    pattern: str, *, regex: bool, case_sensitive: bool
) -> re.Pattern[str] | regex_engine.Pattern:
    flags = 0 if case_sensitive else re.IGNORECASE
    if not regex:
        return re.compile(re.escape(pattern), flags)
    try:
        # Accept exactly the syntax stdlib re accepts, as before the regex package.
        parsed = re_parser.parse(pattern, flags)
        if _unrolled_units(parsed) > MAX_UNROLLED_UNITS:
            raise DomainError.of(ErrorCategory.INVALID_ARGUMENT)
        return regex_engine.compile(
            pattern, regex_engine.IGNORECASE if flags else 0, cache_pattern=False
        )
    except (re.error, regex_engine.error, OverflowError) as exc:
        raise DomainError.of(ErrorCategory.INVALID_ARGUMENT) from exc


def _unrolled_units(node) -> int:
    """Pattern items once the minimum of every repeat is written out."""
    total = 0
    for op, av in node:
        if op in _REPEATS:
            low, _high, body = av
            total += max(low, 1) * _unrolled_units(body)
        else:
            parts = _subpatterns(av)
            total += sum(_unrolled_units(part) for part in parts) if parts else 1
    return total


def _subpatterns(av) -> list:
    if isinstance(av, re_parser.SubPattern):
        return [av]
    if isinstance(av, tuple | list):
        return [part for item in av for part in _subpatterns(item)]
    return []


def search_text(
    text: str,
    compiled: re.Pattern[str] | regex_engine.Pattern,
    *,
    line_oriented: bool,
    context_lines: int,
    remaining: int,
    skip: int = 0,
    timeout: float | None = None,
) -> list[RawMatch]:
    """Up to ``remaining`` matches after the first ``skip``.

    Skipped matches are only counted, never built, so a deep continuation
    cursor costs time proportional to the matches passed over, not memory.

    ``timeout`` bounds the whole search in seconds for a regex package
    pattern; when it runs out, SearchTimeout carries the matches finished so
    far (in line-oriented text, only whole lines).
    """
    search, finditer = _timed(compiled, timeout)
    found: list[RawMatch] = []
    try:
        if line_oriented:
            _line_matches(text, search, finditer, context_lines, remaining, skip, found)
        else:
            _window_matches(text, finditer, remaining, skip, found)
    except TimeoutError as exc:
        raise SearchTimeout(found) from exc
    except (re.error, regex_engine.error) as exc:
        raise DomainError.of(ErrorCategory.SEARCH_ERROR) from exc
    except RecursionError as exc:
        raise DomainError.of(ErrorCategory.SEARCH_ERROR) from exc
    return found


def _timed(compiled, timeout: float | None):
    """search and finditer for ``compiled`` that share one deadline."""
    if timeout is None or not isinstance(compiled, regex_engine.Pattern):
        return compiled.search, compiled.finditer
    deadline = time.monotonic() + timeout

    def left() -> float:
        seconds = deadline - time.monotonic()
        # The regex package reads a negative timeout as none at all.
        if seconds <= 0:
            raise TimeoutError
        return seconds

    def search(text: str):
        return compiled.search(text, timeout=left())

    def finditer(text: str):
        return compiled.finditer(text, timeout=left())

    return search, finditer


def _line_matches(
    text: str, search, finditer, context_lines: int, remaining: int, skip: int, found: list
) -> None:
    """One match per matching line; further hits on that line only raise occurrences.

    The context always holds the whole line, so a second hit on it would spend
    another max_matches slot on text the caller already has.
    """
    lines = text.splitlines()
    skipped = 0
    for index, line in enumerate(lines):
        if skipped < skip:
            if search(line) is not None:
                skipped += 1
            continue
        first = None
        occurrences = 0
        for match in finditer(line):
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
            return


def _window_matches(text: str, finditer, remaining: int, skip: int, found: list) -> None:
    skipped = 0
    for match in finditer(text):
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
            return
