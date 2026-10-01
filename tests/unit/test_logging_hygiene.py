"""Logs carry no API keys or typed emails, and app events are JSON lines with a severity.

httpx logs every request URL at INFO; the mcp library sets the root logger to INFO with
a bare "%(message)s" format. Network calls are faked with httpx.MockTransport.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from fakes.fake_drive import FakeDrive
from google_drive_mcp.infra.billing import routes
from google_drive_mcp.infra.billing.email_link import IdentityPlatformEmailLink
from google_drive_mcp.infra.billing.entitlement import COOKIE_NAME, verify_entitlement
from google_drive_mcp.infra.billing.stripe_api import StripeHttpGateway
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.logging import (
    JsonFormatter,
    configure_logging,
    get_logger,
    log_retrieval,
)
from google_drive_mcp.mcp.middleware import Runtime
from google_drive_mcp.mcp.server import create_server, streamable_app

API_KEY = "AIzaTestOnlyIdentityKey0123456789abcd"
EMAIL = "KbSubscriber7731@example.com"
# The local part, lower-cased: an email in a URL shows up percent-encoded.
EMAIL_MARK = "kbsubscriber7731"
CUSTOMER = "cus_logtest77"


def _settings() -> Settings:
    return Settings.for_tests().model_copy(
        update={
            "mcp_subscription_required": True,
            "stripe_price_id": "price_test",
            "stripe_secret_key": SecretStr("sk_test_logging_only"),
            "identity_toolkit_api_key": SecretStr(API_KEY),
        }
    )


def _json_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if isinstance(h.formatter, JsonFormatter)]


@pytest.fixture
def app_logging():
    """Let a test call configure_logging, then put the loggers back as they were."""
    loggers = [logging.getLogger(name) for name in ("google_drive_mcp", "httpx", "httpcore")]
    saved = [(logger.level, logger.propagate) for logger in loggers]
    app = loggers[0]
    # A handler left by an earlier main() writes to a stdout capsys does not see.
    earlier = _json_handlers(app)
    for handler in earlier:
        app.removeHandler(handler)
    app.propagate = True
    yield
    for handler in _json_handlers(app):
        app.removeHandler(handler)
    for handler in earlier:
        app.addHandler(handler)
    for logger, (level, propagate) in zip(loggers, saved, strict=True):
        logger.setLevel(level)
        logger.propagate = propagate


class FakeServices:
    """Stripe and Identity Toolkit over one MockTransport; records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "api.stripe.com":
            if path == "/v1/customers":
                data = [{"id": CUSTOMER, "email": EMAIL.lower()}]
                return httpx.Response(200, json={"data": data}, request=request)
            if path == "/v1/subscriptions":
                data = [{"status": "active"}] if request.url.params["customer"] == CUSTOMER else []
                return httpx.Response(200, json={"data": data}, request=request)
        if request.url.host == "identitytoolkit.googleapis.com":
            if path == "/v1/accounts:signInWithEmailLink":
                body = {"email": EMAIL.lower(), "idToken": "id-token-logtest"}
                return httpx.Response(200, json=body, request=request)
            if path in {"/v1/accounts:sendOobCode", "/v1/accounts:delete"}:
                return httpx.Response(200, json={}, request=request)
        raise AssertionError(f"unexpected call {request.method} {request.url.path}")

    def identity_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == "identitytoolkit.googleapis.com"]


def test_email_routes_log_no_email_and_no_api_key(
    fake_drive: FakeDrive, caplog, capsys, monkeypatch, app_logging
):
    monkeypatch.setattr(routes, "_LIMITS", routes._RateLimit())
    configure_logging()
    caplog.set_level(logging.DEBUG)
    settings = _settings()
    services = FakeServices()
    http = httpx.Client(transport=httpx.MockTransport(services))
    runtime = Runtime(
        settings=settings,
        drive=fake_drive,
        billing=StripeHttpGateway(settings, client=http),
        email_link=IdentityPlatformEmailLink(settings, client=http),
    )
    with TestClient(streamable_app(runtime, json_response=True)) as client:
        sent = client.post("/subscribe/email", data={"email": EMAIL})
        assert sent.status_code == 200
        assert [r.url.path for r in services.identity_calls()] == ["/v1/accounts:sendOobCode"]
        done = client.post(
            "/subscribe/email/verify", data={"oobCode": "oob-logtest"}, follow_redirects=False
        )
        assert done.status_code == 303
        assert verify_entitlement(done.cookies[COOKIE_NAME], settings) == CUSTOMER
    # The typed email went to Stripe in the query string.
    assert any(r.url.path == "/v1/customers" for r in services.requests)
    captured = capsys.readouterr()
    logs = caplog.text + captured.out + captured.err
    assert API_KEY not in logs
    assert EMAIL_MARK not in logs.lower()
    assert CUSTOMER not in logs
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_identity_toolkit_key_goes_in_a_header_not_the_url():
    services = FakeServices()
    http = httpx.Client(transport=httpx.MockTransport(services))
    link = IdentityPlatformEmailLink(_settings(), client=http)
    assert link.send_link(EMAIL, "https://example.test/subscribe/email/verify")
    assert link.verified_email(EMAIL, "oob-logtest") == EMAIL.lower()
    calls = services.identity_calls()
    assert [r.url.path for r in calls] == [
        "/v1/accounts:sendOobCode",
        "/v1/accounts:signInWithEmailLink",
        "/v1/accounts:delete",
    ]
    for request in calls:
        assert request.headers["x-goog-api-key"] == API_KEY
        assert API_KEY not in str(request.url)
        assert "key" not in request.url.params


def test_app_events_are_one_json_line_with_severity(fake_drive: FakeDrive, capsys, app_logging):
    # MCPServer runs logging.basicConfig with a bare "%(message)s" format.
    create_server(Runtime(settings=Settings.for_tests(), drive=fake_drive))
    configure_logging()
    configure_logging()  # a second call adds no second handler
    capsys.readouterr()
    log_retrieval(
        request_id="req-log-1",
        tool="drive_read",
        file_count=1,
        bytes_processed=12,
        duration_ms=3.456,
        result_count=0,
        status="ERROR",
        error_category="DRIVE_API_ERROR",
    )
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["severity"] == "WARNING"
    assert entry["message"] == "retrieval"
    assert entry["error_category"] == "DRIVE_API_ERROR"
    assert entry["request_id"] == "req-log-1"
    assert entry["tool"] == "drive_read"
    assert entry["duration_ms"] == 3.46

    log_retrieval(
        request_id="req-log-2",
        tool="drive_ls",
        file_count=2,
        bytes_processed=0,
        duration_ms=1.0,
        result_count=2,
        status="COMPLETE",
    )
    entry = json.loads(capsys.readouterr().out.strip())
    assert entry["severity"] == "INFO"
    assert "error_category" not in entry


def test_main_configures_logging_and_turns_off_the_access_log(
    fake_drive: FakeDrive, monkeypatch, app_logging
):
    import uvicorn

    from google_drive_mcp.mcp import server

    runs: list[dict] = []
    monkeypatch.setattr(
        server, "build_runtime", lambda: Runtime(settings=Settings.for_tests(), drive=fake_drive)
    )
    monkeypatch.setattr(server, "check_allowed_folder_in_drive", lambda _settings: None)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: runs.append(kwargs))
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    server.main()
    # Query strings carry sign-in codes, Allow tickets and Checkout session ids.
    assert len(runs) == 1 and runs[0]["access_log"] is False
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    app_logger = logging.getLogger("google_drive_mcp")
    assert app_logger.propagate is False
    assert len(_json_handlers(app_logger)) == 1


def test_only_whitelisted_fields_are_written_and_redacted(capsys, app_logging):
    configure_logging()
    capsys.readouterr()
    get_logger().info(
        "chain Bearer abc.def",
        extra={"request_id": "req-3", "email": EMAIL, "content": "secret document text"},
    )
    entry = json.loads(capsys.readouterr().out.strip())
    assert entry == {
        "severity": "INFO",
        "message": "chain Bearer [REDACTED]",
        "request_id": "req-3",
    }


def _gateway(handler) -> StripeHttpGateway:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return StripeHttpGateway(_settings(), client=http)


def test_stripe_failures_log_only_the_status(capsys, app_logging):
    configure_logging()
    capsys.readouterr()

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": CUSTOMER}}, request=request)

    def timed_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    assert _gateway(refused).subscription_state(CUSTOMER) is None
    assert _gateway(timed_out).subscription_state(CUSTOMER) is None
    with pytest.raises(httpx.HTTPStatusError):
        _gateway(refused).create_checkout_url(
            success_url="https://example.test/ok",
            cancel_url="https://example.test/no",
            reference="ref-1",
        )
    out = capsys.readouterr().out
    entries = [json.loads(line) for line in out.strip().splitlines()]
    assert [(e["severity"], e["message"]) for e in entries] == [
        ("WARNING", "stripe_subscription_check_failed"),
        ("WARNING", "stripe_subscription_check_failed"),
        ("WARNING", "stripe_checkout_failed"),
    ]
    assert entries[0]["http_status"] == 401
    assert entries[1]["error_category"] == "ReadTimeout"
    assert entries[2]["http_status"] == 401
    assert CUSTOMER not in out and "sk_test" not in out
