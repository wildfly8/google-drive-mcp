"""Non-PII connect telemetry. A Connect is not a person."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

HOST_CLAUDE = "claude"
HOST_CHATGPT = "chatgpt"
HOST_OTHER = "other"
EVENT_OAUTH_CONNECT = "oauth_connect"
EVENT_DRIVE_FIRST_USE = "drive_first_use"
LOOKBACK = "30d"
STATS_NOTE = (
    "Counts successful Connect completions and first Drive tool use per connect. "
    "Not unique people. No emails or IPs."
)


def host_family_from_client_id(client_id: str) -> str:
    raw = (client_id or "").strip().lower()
    host = ""
    if raw.startswith("https://") or raw.startswith("http://"):
        host = (urlparse(raw).hostname or "").lower()
    blob = f"{host} {raw}"
    if "claude.ai" in blob or "anthropic.com" in blob:
        return HOST_CLAUDE
    if "openai.com" in blob or "chatgpt.com" in blob:
        return HOST_CHATGPT
    return HOST_OTHER


@dataclass
class FamilyCounts:
    oauth_connects: int = 0
    drive_first_uses: int = 0

    def to_dict(self) -> dict:
        return {
            "oauth_connects": self.oauth_connects,
            "drive_first_uses": self.drive_first_uses,
        }


@dataclass
class ConnectStats:
    oauth_connects: int = 0
    drive_first_uses: int = 0
    by_host_family: dict[str, FamilyCounts] = field(default_factory=dict)
    lookback: str = LOOKBACK
    source: str = "process"
    truncated: bool = False
    note: str = STATS_NOTE

    def to_dict(self) -> dict:
        families = {
            name: counts.to_dict() for name, counts in sorted(self.by_host_family.items())
        }
        body = {
            "oauth_connects": self.oauth_connects,
            "drive_first_uses": self.drive_first_uses,
            "by_host_family": families,
            "lookback": self.lookback,
            "source": self.source,
            "note": self.note,
        }
        if self.truncated:
            body["truncated"] = True
        return body
