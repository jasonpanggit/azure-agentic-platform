from __future__ import annotations
"""Tests for queue_depth_service.py — Phase 88.

Covers: namespace type classification, health thresholds, metrics parsing,
scan (ARG + metrics mocking), persist, get, summary.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.queue_depth_service import (
    _classify_namespace_type,
    _classify_health,
    _fetch_metrics,
    _get_bearer_token,
    _row_to_namespace,
    get_namespaces,
    get_queue_summary,
    persist_namespaces,
    scan_queue_namespaces,
    QueueNamespace,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_row(**overrides):
    base = {
        "resource_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.servicebus/namespaces/mybus",
        "name": "mybus",
        "type": "microsoft.servicebus/namespaces",
        "resource_group": "rg1",
        "subscription_id": "sub1",
        "location": "eastus",
        "sku_name": "Standard",
        "sku_tier": "Standard",
        "status": "Active",
        "created_at": "2025-01-01T00:00:00Z",
        "tags": {},
    }
    base.update(overrides)
    return base


def _make_ns(**overrides):
    defaults = dict(
        namespace_id=str(uuid.uuid4()),
        arm_id="/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.servicebus/namespaces/mybus",
        name="mybus",
        namespace_type="service_bus",
        resource_group="rg1",
        subscription_id="sub1",
        location="eastus",
        sku_name="Standard",
        status="Active",
        active_messages=0,
        dead_letter_messages=0,
        health_status="healthy",
        health_reason="within thresholds",
        scanned_at="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return QueueNamespace(**defaults)


# ---------------------------------------------------------------------------
# _classify_namespace_type
# ---------------------------------------------------------------------------

def test_classify_type_servicebus():
    assert _classify_namespace_type("microsoft.servicebus/namespaces") == "service_bus"

def test_classify_type_eventhub():
    assert _classify_namespace_type("microsoft.eventhub/namespaces") == "event_hub"

def test_classify_type_unknown_defaults_event_hub():
    assert _classify_namespace_type("microsoft.other/namespaces") == "event_hub"


# ---------------------------------------------------------------------------
# _classify_health thresholds
# ---------------------------------------------------------------------------

def test_health_both_none_is_unknown():
    status, reason = _classify_health(None, None)
    assert status == "unknown"

def test_health_critical_high_dlq():
    status, _ = _classify_health(0, 101)
    assert status == "critical"

def test_health_critical_boundary_dlq():
    status, _ = _classify_health(0, 100)
    # 100 is NOT > 100, so not critical on dlq alone
    assert status != "critical"

def test_health_critical_high_active():
    status, _ = _classify_health(10001, 0)
    assert status == "critical"

def test_health_warning_dlq_11():
    status, _ = _classify_health(0, 11)
    assert status == "warning"

def test_health_warning_dlq_boundary():
    status, _ = _classify_health(0, 10)
    # 10 is NOT > 10
    assert status != "warning"

def test_health_warning_active_1001():
    status, _ = _classify_health(1001, 0)
    assert status == "warning"

def test_health_healthy():
    status, _ = _classify_health(0, 0)
    assert status == "healthy"

def test_health_healthy_some_active():
    status, _ = _classify_health(500, 5)
    assert status == "healthy"

def test_health_reason_contains_count():
    _, reason = _classify_health(0, 200)
    assert "200" in reason


# ---------------------------------------------------------------------------
# _fetch_metrics
# ---------------------------------------------------------------------------

def _mock_metrics_response(active_max, dlq_max):
    """Build a mock requests.Response for the metrics REST API."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "value": [
            {
                "name": {"value": "ActiveMessages"},
                "timeseries": [{"data": [{"maximum": active_max}]}],
            },
            {
                "name": {"value": "DeadletteredMessages"},
                "timeseries": [{"data": [{"maximum": dlq_max}]}],
            },
        ]
    }
    return resp

def test_fetch_metrics_parses_values():
    with patch("services.api_gateway.queue_depth_service.requests.get", return_value=_mock_metrics_response(500, 15)):
        active, dlq = _fetch_metrics("/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.servicebus/namespaces/mybus", "tok")
    assert active == 500
    assert dlq == 15

def test_fetch_metrics_non_200_returns_none():
    resp = MagicMock()
    resp.status_code = 403
    with patch("services.api_gateway.queue_depth_service.requests.get", return_value=resp):
        active, dlq = _fetch_metrics("/arm/id", "tok")
    assert active is None
    assert dlq is None

def test_fetch_metrics_exception_returns_none():
    with patch("services.api_gateway.queue_depth_service.requests.get", side_effect=Exception("timeout")):
        active, dlq = _fetch_metrics("/arm/id", "tok")
    assert active is None
    assert dlq is None


# ---------------------------------------------------------------------------
# _get_bearer_token
# ---------------------------------------------------------------------------

def test_get_bearer_token_success():
    cred = MagicMock()
    cred.get_token.return_value = MagicMock(token="mytoken")
    assert _get_bearer_token(cred) == "mytoken"

def test_get_bearer_token_exception_returns_none():
    cred = MagicMock()
    cred.get_token.side_effect = Exception("auth error")
    assert _get_bearer_token(cred) is None


# ---------------------------------------------------------------------------
# scan_queue_namespaces
# ---------------------------------------------------------------------------

def test_scan_empty_subscriptions():
    result = scan_queue_namespaces(MagicMock(), [])
    assert result == []

def test_scan_arg_error_returns_empty():
    with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("ARG down")):
        result = scan_queue_namespaces(MagicMock(), ["sub1"])
    assert result == []

def test_scan_returns_namespaces_with_metrics():
    cred = MagicMock()
    cred.get_token.return_value = MagicMock(token="tok")
    rows = [_make_row(), _make_row(
        name="myeventhub",
        resource_id="/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.eventhub/namespaces/myeventhub",
        type="microsoft.eventhub/namespaces",
    )]
    with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows), \
         patch("services.api_gateway.queue_depth_service._fetch_metrics", return_value=(100, 5)):
        result = scan_queue_namespaces(cred, ["sub1"])
    assert len(result) == 2
    assert result[0].active_messages == 100
    assert result[0].dead_letter_messages == 5

def test_scan_metrics_unavailable_health_unknown():
    cred = MagicMock()
    cred.get_token.return_value = MagicMock(token="tok")
    with patch("services.api_gateway.arg_helper.run_arg_query", return_value=[_make_row()]), \
         patch("services.api_gateway.queue_depth_service._fetch_metrics", return_value=(None, None)):
        result = scan_queue_namespaces(cred, ["sub1"])
    assert result[0].health_status == "unknown"


# ---------------------------------------------------------------------------
# persist_namespaces
# ---------------------------------------------------------------------------

def test_persist_empty_no_op():
    cosmos = MagicMock()
    persist_namespaces(cosmos, "aap", [])
    cosmos.get_database_client.assert_not_called()

def test_persist_upserts_each():
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    persist_namespaces(cosmos, "aap", [_make_ns(), _make_ns(namespace_id=str(uuid.uuid4()))])
    assert container.upsert_item.call_count == 2

def test_persist_upsert_error_does_not_raise():
    cosmos = MagicMock()
    container = MagicMock()
    container.upsert_item.side_effect = Exception("cosmos error")
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    persist_namespaces(cosmos, "aap", [_make_ns()])

def test_persist_db_error_does_not_raise():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("db error")
    persist_namespaces(cosmos, "aap", [_make_ns()])


# ---------------------------------------------------------------------------
# get_namespaces
# ---------------------------------------------------------------------------

def test_get_namespaces_returns_items():
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = [{"id": "x"}]
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    result = get_namespaces(cosmos, "aap")
    assert len(result) == 1

def test_get_namespaces_with_all_filters():
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = []
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    result = get_namespaces(cosmos, "aap", ["sub1"], "critical", "service_bus")
    assert result == []

def test_get_namespaces_cosmos_error():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("error")
    assert get_namespaces(cosmos, "aap") == []


# ---------------------------------------------------------------------------
# get_queue_summary
# ---------------------------------------------------------------------------

def test_summary_aggregates_correctly():
    cosmos = MagicMock()
    items = [
        {"health_status": "healthy",  "active_messages": 100,  "dead_letter_messages": 0},
        {"health_status": "warning",  "active_messages": 2000, "dead_letter_messages": 15},
        {"health_status": "critical", "active_messages": 500,  "dead_letter_messages": 150},
    ]
    with patch("services.api_gateway.queue_depth_service.get_namespaces", return_value=items):
        summary = get_queue_summary(cosmos, "aap")
    assert summary["total"] == 3
    assert summary["healthy"] == 1
    assert summary["warning"] == 1
    assert summary["critical"] == 1
    assert summary["total_active_messages"] == 2600
    assert summary["total_dead_letter"] == 165

def test_summary_handles_none_counts():
    cosmos = MagicMock()
    items = [{"health_status": "unknown", "active_messages": None, "dead_letter_messages": None}]
    with patch("services.api_gateway.queue_depth_service.get_namespaces", return_value=items):
        summary = get_queue_summary(cosmos, "aap")
    assert summary["total"] == 1
    assert summary["total_active_messages"] == 0
    assert summary["total_dead_letter"] == 0

def test_summary_error_returns_zeros():
    cosmos = MagicMock()
    with patch("services.api_gateway.queue_depth_service.get_namespaces", side_effect=Exception("err")):
        summary = get_queue_summary(cosmos, "aap")
    assert summary["total"] == 0
