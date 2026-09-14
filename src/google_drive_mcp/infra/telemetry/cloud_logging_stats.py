"""Aggregate unique connect ids from Cloud Logging jsonPayload events."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx

from google_drive_mcp.domain.connect_telemetry import (
    EVENT_DRIVE_FIRST_USE,
    EVENT_OAUTH_CONNECT,
    LOOKBACK,
    ConnectStats,
    FamilyCounts,
)

_MAX_ENTRIES = 10000
_PAGE = 1000


def _lookback_start() -> str:
    start = datetime.now(UTC) - timedelta(days=30)
    return start.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stats_from_log_payloads(payloads: list[dict], *, truncated: bool = False) -> ConnectStats:
    connects: dict[str, str] = {}
    first: dict[str, str] = {}
    for payload in payloads:
        event = payload.get("event")
        cid = payload.get("connect_id")
        family = str(payload.get("host_family") or "other")
        if not isinstance(cid, str) or not cid:
            continue
        if event == EVENT_OAUTH_CONNECT:
            connects[cid] = family
        elif event == EVENT_DRIVE_FIRST_USE:
            first[cid] = family
    families: dict[str, FamilyCounts] = {}
    for cid, family in connects.items():
        families.setdefault(family, FamilyCounts()).oauth_connects += 1
    for cid, family in first.items():
        families.setdefault(family, FamilyCounts()).drive_first_uses += 1
    return ConnectStats(
        oauth_connects=len(connects),
        drive_first_uses=len(first),
        by_host_family=families,
        lookback=LOOKBACK,
        source="cloud_logging",
        truncated=truncated,
    )


def fetch_cloud_logging_stats(
    *, project: str, timeout_s: float = 15.0
) -> tuple[ConnectStats | None, str | None]:
    try:
        import google.auth
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError:
        return None, "auth"
    try:
        creds, detected = google.auth.default()
        project = project or (detected or "")
        if not project:
            return None, "no_project"
        creds.refresh(GoogleAuthRequest())
        token = creds.token
    except Exception:
        return None, "auth"
    if not token:
        return None, "auth"
    filt = (
        'resource.type="cloud_run_revision" AND '
        f'(jsonPayload.event="{EVENT_OAUTH_CONNECT}" OR '
        f'jsonPayload.event="{EVENT_DRIVE_FIRST_USE}") AND '
        f'timestamp>="{_lookback_start()}"'
    )
    payloads: list[dict] = []
    page_token = None
    headers = {"authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=timeout_s) as client:
            while len(payloads) < _MAX_ENTRIES:
                body: dict = {
                    "resourceNames": [f"projects/{project}"],
                    "filter": filt,
                    "pageSize": _PAGE,
                    "orderBy": "timestamp desc",
                }
                if page_token:
                    body["pageToken"] = page_token
                response = client.post(
                    "https://logging.googleapis.com/v2/entries:list",
                    headers=headers,
                    json=body,
                )
                if response.status_code != 200:
                    return None, f"http_{response.status_code}"
                data = response.json()
                for entry in data.get("entries") or []:
                    payload = entry.get("jsonPayload") or {}
                    if isinstance(payload, dict):
                        payloads.append(payload)
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
    except httpx.TimeoutException:
        return None, "timeout"
    except Exception:
        return None, "error"
    truncated = len(payloads) >= _MAX_ENTRIES
    return stats_from_log_payloads(payloads[:_MAX_ENTRIES], truncated=truncated), None


def cloud_logging_project() -> str:
    env = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
        or ""
    ).strip()
    if env:
        return env
    if not os.environ.get("K_SERVICE"):
        return ""
    try:
        with httpx.Client(timeout=1.0) as client:
            response = client.get(
                "http://metadata.google.internal/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
        if response.status_code == 200:
            return response.text.strip()
    except Exception:
        return ""
    return ""


def use_cloud_logging_stats() -> bool:
    flag = os.environ.get("MCP_STATS_FROM_LOGS", "").strip().lower()
    if flag in {"0", "false", "no"}:
        return False
    if flag in {"1", "true", "yes"}:
        return True
    return bool(os.environ.get("K_SERVICE"))
