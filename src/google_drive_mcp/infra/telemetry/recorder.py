"""In-process connect counters plus JSON operational events (no PII)."""

from __future__ import annotations

import json
import sys
from threading import Lock

from google_drive_mcp.domain.connect_telemetry import (
    EVENT_DRIVE_FIRST_USE,
    EVENT_OAUTH_CONNECT,
    ConnectStats,
    FamilyCounts,
)


_FORBIDDEN = (
    "email",
    "ip",
    "remoteip",
    "user_agent",
    "useragent",
    "authorization",
    "access_token",
    "refresh_token",
    "client_id",
)


def emit_connect_event(event: str, connect_id: str, host_family: str) -> dict:
    payload = {
        "severity": "INFO",
        "event": event,
        "connect_id": connect_id,
        "host_family": host_family,
    }
    for key in payload:
        if key.lower() in _FORBIDDEN:
            raise ValueError(f"forbidden telemetry key {key}")
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return payload


class ConnectRecorder:
    """Best-effort process counts. Durable totals come from Cloud Logging."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._connects: dict[str, str] = {}
        self._first_use: dict[str, str] = {}

    def record_oauth_connect(self, connect_id: str, host_family: str) -> None:
        if not connect_id:
            return
        with self._lock:
            self._connects[connect_id] = host_family
        emit_connect_event(EVENT_OAUTH_CONNECT, connect_id, host_family)

    def record_drive_first_use(self, connect_id: str, host_family: str) -> bool:
        if not connect_id:
            return False
        with self._lock:
            if connect_id in self._first_use:
                return False
            self._first_use[connect_id] = host_family
        emit_connect_event(EVENT_DRIVE_FIRST_USE, connect_id, host_family)
        return True

    def snapshot(self) -> ConnectStats:
        with self._lock:
            connects = dict(self._connects)
            first = dict(self._first_use)
        stats = ConnectStats(source="process")
        stats.oauth_connects = len(connects)
        stats.drive_first_uses = len(first)
        families: dict[str, FamilyCounts] = {}
        for cid, family in connects.items():
            bucket = families.setdefault(family, FamilyCounts())
            bucket.oauth_connects += 1
        for cid, family in first.items():
            bucket = families.setdefault(family, FamilyCounts())
            bucket.drive_first_uses += 1
        stats.by_host_family = families
        return stats
