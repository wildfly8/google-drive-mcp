"""Host family and unique-id aggregation (no PII)."""

from __future__ import annotations

import json

from google_drive_mcp.domain.connect_telemetry import host_family_from_client_id
from google_drive_mcp.infra.telemetry.cloud_logging_stats import stats_from_log_payloads
from google_drive_mcp.infra.telemetry.recorder import ConnectRecorder, emit_connect_event


def test_host_family_from_client_id():
    assert host_family_from_client_id(
        "https://claude.ai/oauth/mcp-oauth-client-metadata"
    ) == "claude"
    assert host_family_from_client_id("https://chatgpt.com/apps") == "chatgpt"
    assert host_family_from_client_id("https://platform.openai.com/apps") == "chatgpt"
    assert host_family_from_client_id("random-dcr-uuid") == "other"


def test_emit_event_has_no_pii_keys():
    payload = emit_connect_event("oauth_connect", "cid-1", "claude")
    assert set(payload) == {"severity", "event", "connect_id", "host_family"}
    assert payload["connect_id"] == "cid-1"
    assert payload["host_family"] == "claude"


def test_first_use_once_per_connect():
    rec = ConnectRecorder()
    rec.record_oauth_connect("a", "claude")
    assert rec.record_drive_first_use("a", "claude") is True
    assert rec.record_drive_first_use("a", "claude") is False
    snap = rec.snapshot()
    assert snap.oauth_connects == 1
    assert snap.drive_first_uses == 1
    assert snap.by_host_family["claude"].oauth_connects == 1


def test_log_payloads_unique_connect_id():
    stats = stats_from_log_payloads(
        [
            {"event": "oauth_connect", "connect_id": "a", "host_family": "claude"},
            {"event": "oauth_connect", "connect_id": "a", "host_family": "claude"},
            {"event": "drive_first_use", "connect_id": "a", "host_family": "claude"},
            {"event": "drive_first_use", "connect_id": "a", "host_family": "claude"},
            {"event": "oauth_connect", "connect_id": "b", "host_family": "other"},
        ]
    )
    assert stats.oauth_connects == 2
    assert stats.drive_first_uses == 1
    assert stats.source == "cloud_logging"


def test_metric_filters_and_labels_are_non_pii():
    from google_drive_mcp.infra.telemetry.gcp_console import (
        DASHBOARD_DISPLAY_NAME,
        METRIC_DRIVE_FIRST_USES,
        METRIC_OAUTH_CONNECTS,
        assert_metric_labels_non_pii,
        console_links,
        dashboard_config,
        dashboard_filter,
        dashboard_update_config,
        load_gcp_telemetry_config,
        log_filter,
        log_metric_resource,
        log_metric_resource_for_id,
        metric_label_extractors,
    )

    cfg = load_gcp_telemetry_config()
    names = {m["name"] for m in cfg["metrics"]}
    assert names == {METRIC_OAUTH_CONNECTS, METRIC_DRIVE_FIRST_USES}
    extractors = metric_label_extractors()
    assert_metric_labels_non_pii(extractors)
    assert set(extractors) == {"host_family"}
    filt = log_filter(service_name="onto-kb", event="oauth_connect")
    body = log_metric_resource(
        name="onto_kb_oauth_connects",
        description="test",
        log_filter=filt,
    )
    assert body["labelExtractors"] == extractors
    assert "connect_id" not in json.dumps(body)
    assert "jsonPayload.event=\"oauth_connect\"" in filt
    assert "service_name=\"onto-kb\"" in filt
    assert "connect_id" not in filt
    assert "client_id" not in filt
    for metric_id in names:
        resource = log_metric_resource_for_id(metric_id)
        dumped = json.dumps(resource)
        assert resource["labelExtractors"] == extractors
        assert "connect_id" not in dumped
        assert "client_id" not in dumped
        assert "host_family" in dumped
    links = console_links("project-84207120-95a7-43ac-95e", service_name="onto-kb")
    assert "oauth_connect" in links["logs_oauth_connects"]
    assert "metrics-explorer" in links["metrics_explorer"]
    assert "monitoring/dashboards" in links["dashboards"]
    dash = dashboard_config(
        oauth_metric=METRIC_OAUTH_CONNECTS,
        drive_metric=METRIC_DRIVE_FIRST_USES,
        display_name=DASHBOARD_DISPLAY_NAME,
    )
    blob = json.dumps(dash)
    assert "onto_kb_oauth_connects" in blob
    assert "host_family" in blob
    assert "connect_id" not in blob
    assert "client_id" not in blob
    assert METRIC_OAUTH_CONNECTS in dashboard_filter(METRIC_OAUTH_CONNECTS)
    updated = dashboard_update_config(name="projects/p/dashboards/d", etag="abc")
    assert updated["name"] == "projects/p/dashboards/d"
    assert updated["etag"] == "abc"
    assert "connect_id" not in json.dumps(updated)
