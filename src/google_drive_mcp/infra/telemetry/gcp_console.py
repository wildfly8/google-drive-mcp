"""GCP console links and log-based metric filters. No PII in labels or URLs."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from google_drive_mcp.domain.connect_telemetry import (
    EVENT_DRIVE_FIRST_USE,
    EVENT_OAUTH_CONNECT,
)

DASHBOARD_DISPLAY_NAME = "onto-kb connect counter"
METRIC_OAUTH_CONNECTS = "onto_kb_oauth_connects"
METRIC_DRIVE_FIRST_USES = "onto_kb_drive_first_uses"
DEFAULT_SERVICE = "onto-kb"
_FORBIDDEN_LABELS = frozenset(
    {
        "email",
        "ip",
        "remoteip",
        "user_agent",
        "useragent",
        "authorization",
        "access_token",
        "client_id",
        "connect_id",
        "cid",
    }
)


def _config_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "deploy" / "connect-telemetry-gcp.json"
        if candidate.is_file():
            return candidate
    return Path("deploy/connect-telemetry-gcp.json")


def load_gcp_telemetry_config() -> dict:
    path = _config_path()
    return json.loads(path.read_text())


def log_filter(*, service_name: str, event: str) -> str:
    service = (service_name or DEFAULT_SERVICE).strip() or DEFAULT_SERVICE
    return (
        'resource.type="cloud_run_revision" AND '
        f'resource.labels.service_name="{service}" AND '
        f'jsonPayload.event="{event}"'
    )


def metric_label_extractors() -> dict[str, str]:
    return {"host_family": "EXTRACT(jsonPayload.host_family)"}


def assert_metric_labels_non_pii(extractors: dict[str, str]) -> None:
    for key in extractors:
        if key.lower() in _FORBIDDEN_LABELS:
            raise ValueError(f"forbidden metric label {key}")


def logs_explorer_url(project: str, *, service_name: str, event: str) -> str:
    query = log_filter(service_name=service_name, event=event).replace(" AND ", "\n")
    return (
        "https://console.cloud.google.com/logs/query;query="
        f"{quote(query, safe='')};project={quote(project, safe='')}"
    )


def console_links(project: str, *, service_name: str = DEFAULT_SERVICE) -> dict[str, str]:
    project = project.strip()
    service = (service_name or DEFAULT_SERVICE).strip() or DEFAULT_SERVICE
    return {
        "logs_oauth_connects": logs_explorer_url(
            project, service_name=service, event=EVENT_OAUTH_CONNECT
        ),
        "logs_drive_first_uses": logs_explorer_url(
            project, service_name=service, event=EVENT_DRIVE_FIRST_USE
        ),
        "metrics_explorer": (
            "https://console.cloud.google.com/monitoring/metrics-explorer"
            f"?project={quote(project, safe='')}"
        ),
        "dashboards": (
            "https://console.cloud.google.com/monitoring/dashboards"
            f"?project={quote(project, safe='')}"
        ),
    }


def log_metric_resource(*, name: str, description: str, log_filter: str) -> dict:
    extractors = metric_label_extractors()
    assert_metric_labels_non_pii(extractors)
    return {
        "name": name,
        "description": description,
        "filter": log_filter,
        "metricDescriptor": {
            "metricKind": "DELTA",
            "valueType": "INT64",
            "labels": [
                {
                    "key": "host_family",
                    "valueType": "STRING",
                    "description": "claude, chatgpt, or other",
                }
            ],
        },
        "labelExtractors": extractors,
    }


def log_metric_resource_for_id(metric_id: str, *, service_name: str | None = None) -> dict:
    cfg = load_gcp_telemetry_config()
    service = (service_name or cfg.get("service_name") or DEFAULT_SERVICE).strip()
    for metric in cfg["metrics"]:
        if metric["name"] == metric_id:
            return log_metric_resource(
                name=metric["name"],
                description=metric["description"],
                log_filter=log_filter(service_name=service, event=metric["event"]),
            )
    raise KeyError(f"unknown log metric {metric_id}")


def dashboard_filter(metric_name: str) -> str:
    return (
        f'metric.type="logging.googleapis.com/user/{metric_name}" '
        'resource.type="cloud_run_revision"'
    )


def dashboard_config(
    *,
    oauth_metric: str = METRIC_OAUTH_CONNECTS,
    drive_metric: str = METRIC_DRIVE_FIRST_USES,
    display_name: str = DASHBOARD_DISPLAY_NAME,
) -> dict:
    def chart(title: str, metric_name: str) -> dict:
        return {
            "title": title,
            "xyChart": {
                "chartOptions": {"mode": "COLOR"},
                "dataSets": [
                    {
                        "plotType": "STACKED_BAR",
                        "targetAxis": "Y1",
                        "minAlignmentPeriod": "3600s",
                        "timeSeriesQuery": {
                            "timeSeriesFilter": {
                                "filter": dashboard_filter(metric_name),
                                "aggregation": {
                                    "alignmentPeriod": "3600s",
                                    "perSeriesAligner": "ALIGN_SUM",
                                    "crossSeriesReducer": "REDUCE_SUM",
                                    "groupByFields": ["metric.label.host_family"],
                                },
                            }
                        },
                    }
                ],
                "timeshiftDuration": "0s",
                "yAxis": {"label": "count", "scale": "LINEAR"},
            },
        }

    return {
        "displayName": display_name,
        "mosaicLayout": {
            "columns": 12,
            "tiles": [
                {"width": 6, "height": 4, "widget": chart("OAuth Connects", oauth_metric)},
                {
                    "xPos": 6,
                    "width": 6,
                    "height": 4,
                    "widget": chart("First Drive tool uses", drive_metric),
                },
            ],
        },
    }


def dashboard_update_config(*, name: str, etag: str) -> dict:
    body = dashboard_config()
    body["name"] = name
    body["etag"] = etag
    return body
