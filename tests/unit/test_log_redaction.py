"""Log lines carry no credentials and no exception text, whichever field they arrive in.

test_logging_hygiene covers the field whitelist and a Bearer token in the message. These
cover the other ways a secret can reach a log line: an Authorization header that is not a
Bearer one, a secret inside a whitelisted field, and the text of an exception (which can
carry document text or addresses).
"""

from __future__ import annotations

import json
import logging
import sys

from google_drive_mcp.infra.logging import JsonFormatter, redact


def _record(message: str = "chain", *, exc_info=None, **fields) -> logging.LogRecord:
    record = logging.LogRecord(
        "google_drive_mcp", logging.INFO, __file__, 1, message, None, exc_info
    )
    for name, value in fields.items():
        setattr(record, name, value)
    return record


def _entry(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def test_an_authorization_header_that_is_not_bearer_is_redacted():
    for header in ("Authorization: Basic dXNlcjpwYXNz", "authorization:Token abc123"):
        out = redact(f"upstream sent {header} back")
        assert "dXNlcjpwYXNz" not in out and "abc123" not in out
        assert "Authorization: [REDACTED]" in out
    assert redact("Bearer abc.def.ghi") == "Bearer [REDACTED]"


def test_a_secret_in_a_whitelisted_string_field_is_redacted():
    entry = _entry(
        _record(
            request_id="req Bearer abc.def.ghi",
            error_category="upstream said Authorization: Basic dXNlcjpwYXNz",
        )
    )
    assert entry["request_id"] == "req Bearer [REDACTED]"
    assert "dXNlcjpwYXNz" not in entry["error_category"]
    assert "abc.def.ghi" not in json.dumps(entry)


def test_an_exception_is_logged_by_type_and_never_by_text():
    try:
        raise ValueError("the document said: the launch date is 14 March")
    except ValueError:
        record = _record("failed", exc_info=sys.exc_info())
    entry = _entry(record)
    assert entry["exception"] == "ValueError"
    assert "launch date" not in json.dumps(entry)
