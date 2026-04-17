from __future__ import annotations
"""Tests for app_service_health_service.py — Phase 87.

Covers: classification helpers, scan (ARG mocking), persist, get, summary.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.app_service_health_service import (
    _classify_app_type,
    _classify_health,
    _row_to_app,
    get_app_service_summary,
    get_app_services,
    persist_app_services,
    scan_app_services,
    AppServiceApp,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_row(**overrides):
    base = {
        "resource_id": "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.web/sites/myapp",
        "name": "myapp",
        "type": "microsoft.web/sites",
        "resource_group": "rg1",
        "subscription_id": "sub1",
        "location": "eastus",
        "sku_name": "S1",
        "sku_tier": "Standard",
        "state": "Running",
        "kind": "app",
        "enabled": True,
        "https_only": True,
        "min_tls_version": "1.2",
        "worker_count": 1,
        "reserved": False,
        "tags": {},
    }
    base.update(overrides)
    return base


def _make_app(**overrides):
    defaults = dict(
        app_id=str(uuid.uuid4()),
        arm_id="/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.web/sites/myapp",
        name="myapp",
        app_type="web_app",
        resource_group="rg1",
        subscription_id="sub1",
        location="eastus",
        state="Running",
        enabled=True,
        https_only=True,
        min_tls_version="1.2",
        sku_name="S1",
        health_status="healthy",
        issues=[],
        scanned_at="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return AppServiceApp(**defaults)


# ---------------------------------------------------------------------------
# _classify_app_type
# ---------------------------------------------------------------------------

def test_classify_app_type_web_app():
    assert _classify_app_type("app", "microsoft.web/sites") == "web_app"

def test_classify_app_type_function_app():
    assert _classify_app_type("functionapp", "microsoft.web/sites") == "function_app"

def test_classify_app_type_logic_app():
    assert _classify_app_type("workflowapp", "microsoft.web/sites") == "logic_app"

def test_classify_app_type_plan():
    assert _classify_app_type("", "microsoft.web/serverfarms") == "app_service_plan"

def test_classify_app_type_function_mixed_case():
    assert _classify_app_type("FunctionApp,linux", "microsoft.web/sites") == "function_app"


# ---------------------------------------------------------------------------
# _classify_health
# ---------------------------------------------------------------------------

def test_classify_health_stopped_when_disabled():
    row = _make_row(state="Stopped", enabled=False)
    status, issues = _classify_health(row)
    assert status == "stopped"
    assert issues == []

def test_classify_health_misconfigured_no_https():
    row = _make_row(https_only=False)
    status, issues = _classify_health(row)
    assert status == "misconfigured"
    assert any("HTTPS" in i for i in issues)

def test_classify_health_misconfigured_tls_10():
    row = _make_row(min_tls_version="1.0")
    status, issues = _classify_health(row)
    assert status == "misconfigured"
    assert any("TLS" in i for i in issues)

def test_classify_health_misconfigured_tls_11():
    row = _make_row(min_tls_version="1.1")
    status, issues = _classify_health(row)
    assert status == "misconfigured"

def test_classify_health_misconfigured_free_tier():
    row = _make_row(sku_name="F1")
    status, issues = _classify_health(row)
    assert status == "misconfigured"
    assert any("Free" in i for i in issues)

def test_classify_health_misconfigured_shared_tier():
    row = _make_row(sku_name="D1")
    status, issues = _classify_health(row)
    assert status == "misconfigured"

def test_classify_health_healthy():
    row = _make_row()
    status, issues = _classify_health(row)
    assert status == "healthy"
    assert issues == []

def test_classify_health_multiple_issues():
    row = _make_row(https_only=False, min_tls_version="1.0", sku_name="F1")
    status, issues = _classify_health(row)
    assert status == "misconfigured"
    assert len(issues) == 3

def test_classify_health_plan_free_tier():
    row = _make_row(type="microsoft.web/serverfarms", sku_name="F1")
    status, issues = _classify_health(row)
    assert status == "misconfigured"

def test_classify_health_plan_healthy():
    row = _make_row(type="microsoft.web/serverfarms", sku_name="S1")
    status, issues = _classify_health(row)
    assert status == "healthy"


# ---------------------------------------------------------------------------
# _row_to_app
# ---------------------------------------------------------------------------

def test_row_to_app_stable_id():
    row = _make_row()
    app1 = _row_to_app(row)
    app2 = _row_to_app(row)
    assert app1.app_id == app2.app_id

def test_row_to_app_fields():
    row = _make_row()
    app = _row_to_app(row)
    assert app.name == "myapp"
    assert app.subscription_id == "sub1"
    assert app.health_status == "healthy"
    assert app.app_type == "web_app"


# ---------------------------------------------------------------------------
# scan_app_services
# ---------------------------------------------------------------------------

def test_scan_empty_subscriptions():
    cred = MagicMock()
    result = scan_app_services(cred, [])
    assert result == []

def test_scan_arg_error_returns_empty():
    cred = MagicMock()
    with patch("services.api_gateway.arg_helper.run_arg_query", side_effect=Exception("ARG down")):
        result = scan_app_services(cred, ["sub1"])
    assert result == []

def test_scan_returns_apps():
    cred = MagicMock()
    rows = [_make_row(), _make_row(name="app2", resource_id="/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.web/sites/app2")]
    with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows):
        result = scan_app_services(cred, ["sub1"])
    assert len(result) == 2

def test_scan_bad_row_skipped():
    cred = MagicMock()
    rows = [_make_row(), {"resource_id": None, "name": None}]
    with patch("services.api_gateway.arg_helper.run_arg_query", return_value=rows):
        result = scan_app_services(cred, ["sub1"])
    # At least the valid row should be returned
    assert len(result) >= 1


# ---------------------------------------------------------------------------
# persist_app_services
# ---------------------------------------------------------------------------

def test_persist_empty_list_no_op():
    cosmos = MagicMock()
    persist_app_services(cosmos, "aap", [])
    cosmos.get_database_client.assert_not_called()

def test_persist_upserts_each_app():
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    apps = [_make_app(), _make_app(app_id=str(uuid.uuid4()), name="app2")]
    persist_app_services(cosmos, "aap", apps)
    assert container.upsert_item.call_count == 2

def test_persist_upsert_error_does_not_raise():
    cosmos = MagicMock()
    container = MagicMock()
    container.upsert_item.side_effect = Exception("Cosmos error")
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    apps = [_make_app()]
    # Should not raise
    persist_app_services(cosmos, "aap", apps)

def test_persist_cosmos_error_does_not_raise():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("DB error")
    persist_app_services(cosmos, "aap", [_make_app()])


# ---------------------------------------------------------------------------
# get_app_services
# ---------------------------------------------------------------------------

def test_get_app_services_no_filter():
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = [{"id": "x", "name": "myapp"}]
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    result = get_app_services(cosmos, "aap")
    assert len(result) == 1

def test_get_app_services_with_filters():
    cosmos = MagicMock()
    container = MagicMock()
    container.query_items.return_value = []
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    result = get_app_services(cosmos, "aap", ["sub1"], "healthy", "web_app")
    assert result == []

def test_get_app_services_cosmos_error():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("error")
    result = get_app_services(cosmos, "aap")
    assert result == []


# ---------------------------------------------------------------------------
# get_app_service_summary
# ---------------------------------------------------------------------------

def test_summary_counts():
    cosmos = MagicMock()
    items = [
        {"health_status": "healthy", "https_only": True, "min_tls_version": "1.2", "sku_name": "S1", "app_type": "web_app"},
        {"health_status": "stopped", "https_only": False, "min_tls_version": "1.2", "sku_name": "S1", "app_type": "web_app"},
        {"health_status": "misconfigured", "https_only": False, "min_tls_version": "1.0", "sku_name": "F1", "app_type": "web_app"},
    ]
    with patch("services.api_gateway.app_service_health_service.get_app_services", return_value=items):
        summary = get_app_service_summary(cosmos, "aap")
    assert summary["total"] == 3
    assert summary["healthy"] == 1
    assert summary["stopped"] == 1
    assert summary["misconfigured"] == 1
    assert summary["https_only_violations"] == 2
    assert summary["tls_violations"] == 1
    assert summary["free_tier_count"] == 1

def test_summary_error_returns_zeros():
    cosmos = MagicMock()
    with patch("services.api_gateway.app_service_health_service.get_app_services", side_effect=Exception("err")):
        summary = get_app_service_summary(cosmos, "aap")
    assert summary["total"] == 0
