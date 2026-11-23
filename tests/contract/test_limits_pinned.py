"""The rate limits and request caps in front of every route are the documented numbers.

They are pinned by value. The rate-limit tests count requests up to the limit, so a limit
raised a thousandfold would not fail them: it would only make them run for minutes. This file
sorts before them on purpose, so a wrong number fails here first.
"""

from __future__ import annotations

from google_drive_mcp.mcp import limits


def test_the_rate_limits_per_address_are_the_documented_numbers():
    assert limits.RATE_LIMITS == {
        ("POST", "/register"): (20, 3600),
        ("POST", "/token"): (600, 60),
        ("POST", "/authorize"): (120, 60),
        ("GET", "/authorize"): (120, 60),
    }


def test_the_request_body_caps_are_the_documented_numbers():
    assert limits.MCP_BODY_LIMIT == 4 * 1024 * 1024
    assert limits.WEBHOOK_BODY_LIMIT == 1024 * 1024
    assert limits.DEFAULT_BODY_LIMIT == 64 * 1024
