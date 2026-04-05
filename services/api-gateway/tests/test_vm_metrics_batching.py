"""Tests for per-metric concurrent fetching in GET /api/v1/vms/{id}/metrics.

Covers the fix for "Select All metrics shows no data" — Azure Monitor returns
empty when any unsupported metric is included in a batched request.  The fix
fetches each metric individually and filters out None (unsupported) results.
"""
from __future__ import annotations

import base64
import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


def _encode(resource_id: str) -> str:
    return base64.urlsafe_b64encode(resource_id.encode()).decode().rstrip("=")


RID = (
    "/subscriptions/sub1/resourceGroups/rg-prod"
    "/providers/Microsoft.Compute/virtualMachines/vm-prod-001"
)
ENCODED = _encode(RID)


# ---------------------------------------------------------------------------
# Helper: build a mock Azure Monitor metric response for a single metric
# ---------------------------------------------------------------------------

def _mock_metric_response(name: str, unit: str = "Percent", values: list | None = None):
    """Return a mock ``client.metrics.list()`` response for one metric."""
    from datetime import datetime, timezone

    if values is None:
        values = [42.0]

    dp_list = []
    for v in values:
        dp = MagicMock()
        dp.time_stamp = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)
        dp.average = v
        dp.maximum = v
        dp.minimum = v
        dp_list.append(dp)

    ts = MagicMock()
    ts.data = dp_list

    metric = MagicMock()
    metric.name.value = name
    metric.unit.value = unit
    metric.timeseries = [ts]

    response = MagicMock()
    response.value = [metric]
    return response


def _mock_empty_response():
    """Return a mock response with no metrics in ``value`` (unsupported SKU)."""
    response = MagicMock()
    response.value = []
    return response


def _monitor_sys_modules_patch():
    """Return a ``patch.dict`` that injects a fake ``azure.mgmt.monitor`` module.

    ``MonitorManagementClient`` is imported lazily inside the endpoint
    function body (``from azure.mgmt.monitor import MonitorManagementClient``).
    Because ``azure.mgmt.monitor`` is not installed in the test environment,
    we inject a stub module so the lazy import succeeds.  Patching the module
    via ``sys.modules`` is the canonical approach used throughout this test
    suite for optional Azure SDK packages.
    """
    mock_monitor_module = MagicMock()
    mock_monitor_cls = MagicMock()
    mock_monitor_module.MonitorManagementClient = mock_monitor_cls
    return patch.dict(
        "sys.modules",
        {"azure.mgmt.monitor": mock_monitor_module},
    ), mock_monitor_cls


# ---------------------------------------------------------------------------
# Unit tests: _fetch_single_metric
# ---------------------------------------------------------------------------

class TestFetchSingleMetric:
    """Unit tests for the _fetch_single_metric helper."""

    def test_returns_metric_dict_on_success(self):
        from services.api_gateway.vm_detail import _fetch_single_metric

        client = MagicMock()
        client.metrics.list.return_value = _mock_metric_response("Percentage CPU", "Percent", [55.0])

        result = _fetch_single_metric(client, RID, "Percentage CPU", "PT24H", "PT5M")

        assert result is not None
        assert result["name"] == "Percentage CPU"
        assert result["unit"] == "Percent"
        assert len(result["timeseries"]) == 1
        assert result["timeseries"][0]["average"] == 55.0

    def test_returns_none_when_response_value_empty(self):
        """Empty response.value means the metric is unsupported for this SKU."""
        from services.api_gateway.vm_detail import _fetch_single_metric

        client = MagicMock()
        client.metrics.list.return_value = _mock_empty_response()

        result = _fetch_single_metric(client, RID, "CPU Credits Remaining", "PT24H", "PT5M")

        assert result is None

    def test_returns_none_on_exception(self):
        """Exceptions are caught per-metric — never propagated."""
        from services.api_gateway.vm_detail import _fetch_single_metric

        client = MagicMock()
        client.metrics.list.side_effect = RuntimeError("Azure Monitor API error")

        result = _fetch_single_metric(client, RID, "Percentage CPU", "PT24H", "PT5M")

        assert result is None

    def test_passes_correct_args_to_sdk(self):
        """SDK is called with a single metric name (not a comma-joined batch)."""
        from services.api_gateway.vm_detail import _fetch_single_metric

        client = MagicMock()
        client.metrics.list.return_value = _mock_metric_response("Percentage CPU")

        _fetch_single_metric(client, RID, "Percentage CPU", "PT1H", "PT1M")

        client.metrics.list.assert_called_once_with(
            resource_uri=RID,
            metricnames="Percentage CPU",
            timespan="PT1H",
            interval="PT1M",
            aggregation="Average,Maximum,Minimum",
        )

    def test_metric_with_no_timeseries_data(self):
        """Metric exists but has no data points — still returns the metric dict."""
        from services.api_gateway.vm_detail import _fetch_single_metric

        ts = MagicMock()
        ts.data = []

        metric = MagicMock()
        metric.name.value = "Percentage CPU"
        metric.unit.value = "Percent"
        metric.timeseries = [ts]

        response = MagicMock()
        response.value = [metric]

        client = MagicMock()
        client.metrics.list.return_value = response

        result = _fetch_single_metric(client, RID, "Percentage CPU", "PT24H", "PT5M")

        assert result is not None
        assert result["name"] == "Percentage CPU"
        assert result["timeseries"] == []


# ---------------------------------------------------------------------------
# Integration tests: GET /api/v1/vms/{id}/metrics endpoint
# ---------------------------------------------------------------------------

class TestGetVmMetricsEndpoint:
    """Integration tests for the /metrics endpoint with per-metric strategy.

    These tests patch ``_fetch_single_metric`` at the module level and inject a
    stub ``azure.mgmt.monitor`` module so the lazy SDK import inside the
    endpoint does not require the real package to be installed.
    """

    def _make_test_client(self):
        from services.api_gateway.main import app
        from fastapi.testclient import TestClient

        app.state.credential = MagicMock()
        app.state.cosmos_client = None
        return TestClient(app)

    def test_all_metrics_supported_returns_all(self):
        """When all metrics are supported, all are returned."""
        sys_patch, _ = _monitor_sys_modules_patch()

        with sys_patch, patch("services.api_gateway.vm_detail._fetch_single_metric") as mock_fetch:
            mock_fetch.side_effect = lambda client, rid, name, ts, iv: {
                "name": name,
                "unit": "Percent",
                "timeseries": [{"timestamp": "2026-04-05T12:00:00+00:00", "average": 10.0, "maximum": 10.0, "minimum": 10.0}],
            }

            tc = self._make_test_client()
            resp = tc.get(
                f"/api/v1/vms/{ENCODED}/metrics?metrics=Percentage+CPU,Available+Memory+Bytes",
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["metrics"]) == 2
        assert {m["name"] for m in data["metrics"]} == {"Percentage CPU", "Available Memory Bytes"}

    def test_one_unsupported_metric_omitted_others_returned(self):
        """An unsupported metric (None) is filtered; other metrics still returned."""
        sys_patch, _ = _monitor_sys_modules_patch()

        def _side_effect(client: Any, rid: str, name: str, ts: str, iv: str):
            if name == "CPU Credits Remaining":
                return None  # unsupported on non-B-series
            return {
                "name": name,
                "unit": "Count",
                "timeseries": [{"timestamp": "2026-04-05T12:00:00+00:00", "average": 5.0, "maximum": 5.0, "minimum": 5.0}],
            }

        with sys_patch, patch("services.api_gateway.vm_detail._fetch_single_metric") as mock_fetch:
            mock_fetch.side_effect = _side_effect

            tc = self._make_test_client()
            resp = tc.get(
                f"/api/v1/vms/{ENCODED}/metrics"
                "?metrics=Percentage+CPU,CPU+Credits+Remaining,Network+In+Total",
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        returned_names = {m["name"] for m in data["metrics"]}
        assert "CPU Credits Remaining" not in returned_names
        assert "Percentage CPU" in returned_names
        assert "Network In Total" in returned_names
        assert len(data["metrics"]) == 2

    def test_all_13_catalog_metrics_partial_results(self):
        """Selecting all 13 catalog metrics returns data for supported ones only."""
        sku_specific = {
            "CPU Credits Remaining",
            "CPU Credits Consumed",
            "VM Availability Metric",
            "OS Disk Queue Depth",
            "OS Disk Bandwidth Consumed Percentage",
        }

        def _side_effect(client: Any, rid: str, name: str, ts: str, iv: str):
            if name in sku_specific:
                return None
            return {"name": name, "unit": "Various", "timeseries": []}

        sys_patch, _ = _monitor_sys_modules_patch()

        all_13 = [
            "Percentage CPU",
            "Available Memory Bytes",
            "Disk Read Bytes",
            "Disk Write Bytes",
            "Disk Read Operations/Sec",
            "Disk Write Operations/Sec",
            "Network In Total",
            "Network Out Total",
            "CPU Credits Remaining",
            "CPU Credits Consumed",
            "VM Availability Metric",
            "OS Disk Queue Depth",
            "OS Disk Bandwidth Consumed Percentage",
        ]
        metrics_param = ",".join(all_13)

        with sys_patch, patch("services.api_gateway.vm_detail._fetch_single_metric") as mock_fetch:
            mock_fetch.side_effect = _side_effect

            tc = self._make_test_client()
            resp = tc.get(
                f"/api/v1/vms/{ENCODED}/metrics?metrics={metrics_param}",
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        # 8 default metrics supported, 5 SKU-specific filtered out
        assert len(data["metrics"]) == 8
        returned_names = {m["name"] for m in data["metrics"]}
        for name in sku_specific:
            assert name not in returned_names

    def test_all_metrics_unsupported_returns_empty_list(self):
        """When every metric is unsupported, returns an empty list (not an error)."""
        sys_patch, _ = _monitor_sys_modules_patch()

        with sys_patch, patch("services.api_gateway.vm_detail._fetch_single_metric") as mock_fetch:
            mock_fetch.return_value = None

            tc = self._make_test_client()
            resp = tc.get(
                f"/api/v1/vms/{ENCODED}/metrics?metrics=CPU+Credits+Remaining,VM+Availability+Metric",
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"] == []
        assert data["resource_id"] == RID

    def test_single_metric_request_still_works(self):
        """Single metric selection continues to work correctly."""
        sys_patch, _ = _monitor_sys_modules_patch()

        with sys_patch, patch("services.api_gateway.vm_detail._fetch_single_metric") as mock_fetch:
            mock_fetch.return_value = {
                "name": "Percentage CPU",
                "unit": "Percent",
                "timeseries": [{"timestamp": "2026-04-05T12:00:00+00:00", "average": 75.0, "maximum": 80.0, "minimum": 70.0}],
            }

            tc = self._make_test_client()
            resp = tc.get(
                f"/api/v1/vms/{ENCODED}/metrics?metrics=Percentage+CPU",
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["metrics"]) == 1
        assert data["metrics"][0]["name"] == "Percentage CPU"
        assert data["metrics"][0]["timeseries"][0]["average"] == 75.0

    def test_default_8_metrics_behavior_unchanged(self):
        """Default 8 metrics are each fetched individually and all returned."""
        from services.api_gateway.vm_detail import DEFAULT_METRICS

        sys_patch, _ = _monitor_sys_modules_patch()

        with sys_patch, patch("services.api_gateway.vm_detail._fetch_single_metric") as mock_fetch:
            mock_fetch.side_effect = lambda client, rid, name, ts, iv: {
                "name": name,
                "unit": "Various",
                "timeseries": [],
            }

            metrics_param = ",".join(DEFAULT_METRICS)
            tc = self._make_test_client()
            resp = tc.get(
                f"/api/v1/vms/{ENCODED}/metrics?metrics={metrics_param}",
                headers={"Authorization": "Bearer test-token"},
            )

            call_count = mock_fetch.call_count

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["metrics"]) == len(DEFAULT_METRICS)
        # _fetch_single_metric called once per metric
        assert call_count == len(DEFAULT_METRICS)

    def test_bad_resource_id_returns_400(self):
        """Malformed base64 resource ID returns 400 before any SDK calls."""
        tc = self._make_test_client()
        resp = tc.get(
            "/api/v1/vms/!!!invalid!!!/metrics",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 400

    def test_monitor_client_instantiation_failure_returns_502(self):
        """If MonitorManagementClient instantiation raises, endpoint returns 502."""
        mock_monitor_module = MagicMock()
        mock_monitor_module.MonitorManagementClient = MagicMock(
            side_effect=RuntimeError("Credential error")
        )

        with patch.dict("sys.modules", {"azure.mgmt.monitor": mock_monitor_module}):
            tc = self._make_test_client()
            resp = tc.get(
                f"/api/v1/vms/{ENCODED}/metrics?metrics=Percentage+CPU",
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 502
        assert "Metrics unavailable" in resp.json()["detail"]
