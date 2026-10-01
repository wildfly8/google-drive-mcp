"""GET /stats — non-PII connect totals."""

from __future__ import annotations

import os
import threading
import time

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from google_drive_mcp.infra.telemetry.cloud_logging_stats import (
    cloud_logging_project,
    fetch_cloud_logging_stats,
    use_cloud_logging_stats,
)
from google_drive_mcp.infra.telemetry.gcp_console import DEFAULT_SERVICE, console_links
from google_drive_mcp.infra.telemetry.recorder import ConnectRecorder


def _with_gcp_links(body: dict) -> dict:
    project = cloud_logging_project()
    if not project:
        return body
    service = os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_SERVICE") or DEFAULT_SERVICE
    body["gcp"] = console_links(project, service_name=service)
    return body


# /stats is public: reuse one Cloud Logging scan for a minute so anonymous
# requests cannot spend the project's Logging read quota.
_LOG_SCAN_TTL = 60.0
_log_scan: dict = {"at": 0.0, "result": None}
_log_scan_lock = threading.Lock()


def _logged_stats():
    stale = _log_scan["result"]
    # While another request scans, serve the last result instead of holding a
    # worker thread in the queue. Only the very first scan is waited for.
    if not _log_scan_lock.acquire(blocking=stale is None):
        return stale
    try:
        cached = _log_scan["result"]
        if cached is not None and time.monotonic() - _log_scan["at"] < _LOG_SCAN_TTL:
            return cached
        result = fetch_cloud_logging_stats(project=cloud_logging_project())
        _log_scan.update(at=time.monotonic(), result=result)
        return result
    finally:
        _log_scan_lock.release()


def stats_snapshot(recorder: ConnectRecorder, *, links: bool = True) -> dict:
    """Non-PII totals. links=False leaves out console links, which name the project."""
    add_links = _with_gcp_links if links else (lambda body: body)
    if use_cloud_logging_stats():
        logged, reason = _logged_stats()
        if logged is not None:
            return add_links(logged.to_dict())
        body = recorder.snapshot().to_dict()
        if reason:
            body["log_store"] = reason
        return add_links(body)
    return add_links(recorder.snapshot().to_dict())


async def stats_get(
    _request: Request, recorder: ConnectRecorder, *, links: bool = True
) -> JSONResponse:
    # The log scan is blocking HTTP: keep it off the event loop.
    return JSONResponse(await run_in_threadpool(stats_snapshot, recorder, links=links))
