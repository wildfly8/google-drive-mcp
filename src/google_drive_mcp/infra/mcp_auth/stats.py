"""GET /stats — non-PII connect totals."""

from __future__ import annotations

import os

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


def stats_snapshot(recorder: ConnectRecorder) -> dict:
    if use_cloud_logging_stats():
        logged, reason = fetch_cloud_logging_stats(project=cloud_logging_project())
        if logged is not None:
            return _with_gcp_links(logged.to_dict())
        body = recorder.snapshot().to_dict()
        if reason:
            body["log_store"] = reason
        return _with_gcp_links(body)
    return _with_gcp_links(recorder.snapshot().to_dict())


def stats_get(_request: Request, recorder: ConnectRecorder) -> JSONResponse:
    return JSONResponse(stats_snapshot(recorder))
