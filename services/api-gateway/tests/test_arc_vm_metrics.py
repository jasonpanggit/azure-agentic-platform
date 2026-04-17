from __future__ import annotations
"""Tests for Arc VM metrics via Log Analytics (Perf table).

Covers the fix for "Arc VM metrics tab shows placeholder instead of actual data"
— Arc VMs now query the Log Analytics Perf table via LogsQueryClient instead of
Azure Monitor platform metrics (which return empty for Arc VMs).
"""
import os

import base64
import os
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")


def _encode(resource_id: str) -> str:
    return base64.urlsafe_b64encode(resource_id.encode()).decode().rstrip("=")


ARC_RID = (
    "/subscriptions/sub1/resourceGroups/rg-prod"
    "/providers/Microsoft.HybridCompute/machines/WIN-JBC7MM2NO8J"
)
ARC_ENCODED = _encode(ARC_RID)

AZURE_RID = (
    "/subscriptions/sub1/resourceGroups/rg-prod"
    "/providers/Microsoft.Compute/virtualMachines/vm-prod-001"
)
AZURE_ENCODED = _encode(AZURE_RID)

LA_WORKSPACE_RESOURCE_ID = (
    "/subscriptions/sub1/resourceGroups/rg-prod"
    "/providers/Microsoft.OperationalInsights/workspaces/law-aap-prod"
)


# ---------------------------------------------------------------------------
# Unit tests: _is_arc_vm
# ---------------------------------------------------------------------------

class TestIsArcVM:
    def test_arc_vm_detected(self):
        from services.api_gateway.vm_detail import _is_arc_vm
        assert _is_arc_vm(ARC_RID) is True

    def test_azure_vm_not_arc(self):
        from services.api_gateway.vm_detail import _is_arc_vm
        assert _is_arc_vm(AZURE_RID) is False


# ---------------------------------------------------------------------------
# Unit tests: _build_arc_metrics_kql
# ---------------------------------------------------------------------------

class TestBuildArcMetricsKql:
    def test_basic_kql_structure(self):
        from services.api_gateway.vm_detail import _build_arc_metrics_kql

        kql = _build_arc_metrics_kql(
            resource_id=ARC_RID,
            counters=["% Processor Time", "Available MBytes"],
            timespan="PT24H",
            interval="PT5M",
        )
        assert "Perf" in kql
        assert "% Processor Time" in kql
        assert "Available MBytes" in kql
        # ISO 8601 durations must be converted to KQL literals
        assert "ago(24h)" in kql
        assert "bin(TimeGenerated, 5m)" in kql
        # Raw ISO strings must NOT appear — they are invalid in KQL ago()/bin()
        assert "PT24H" not in kql
        assert "PT5M" not in kql
        assert ARC_RID.lower() in kql.lower()

    def test_7d_iso_converted_to_kql(self):
        """P7D must become ago(7d) not ago(P7D) — KQL rejects ISO 8601."""
        from services.api_gateway.vm_detail import _build_arc_metrics_kql

        kql = _build_arc_metrics_kql(
            resource_id=ARC_RID,
            counters=["% Processor Time"],
            timespan="P7D",
            interval="PT1H",
        )
        assert "ago(7d)" in kql
        assert "bin(TimeGenerated, 1h)" in kql
        assert "P7D" not in kql
        assert "PT1H" not in kql

    def test_all_supported_timespans_convert(self):
        """Every timespan the frontend sends must convert cleanly."""
        from services.api_gateway.vm_detail import _build_arc_metrics_kql, _ISO_TO_KQL_TIMESPAN

        for iso, kql_lit in _ISO_TO_KQL_TIMESPAN.items():
            kql = _build_arc_metrics_kql(ARC_RID, ["% Processor Time"], iso, "PT5M")
            assert f"ago({kql_lit})" in kql, f"Expected ago({kql_lit}) for {iso}"
            assert iso not in kql, f"Raw ISO {iso} must not appear in KQL"

    def test_sql_injection_safe(self):
        from services.api_gateway.vm_detail import _build_arc_metrics_kql

        malicious_rid = "/subscriptions/sub1/providers/'; drop table --"
        kql = _build_arc_metrics_kql(
            resource_id=malicious_rid,
            counters=["% Processor Time"],
            timespan="PT1H",
            interval="PT5M",
        )
        # Single quotes should be escaped
        assert "''" in kql


# ---------------------------------------------------------------------------
# Unit tests: _iso_to_timedelta
# ---------------------------------------------------------------------------

class TestIsoToTimedelta:
    def test_known_timespans_return_timedelta(self):
        import datetime
        from services.api_gateway.vm_detail import _iso_to_timedelta

        assert _iso_to_timedelta("PT1H") == datetime.timedelta(hours=1)
        assert _iso_to_timedelta("PT6H") == datetime.timedelta(hours=6)
        assert _iso_to_timedelta("PT24H") == datetime.timedelta(hours=24)
        assert _iso_to_timedelta("P7D") == datetime.timedelta(days=7)
        assert _iso_to_timedelta("P30D") == datetime.timedelta(days=30)

    def test_unknown_returns_none(self):
        from services.api_gateway.vm_detail import _iso_to_timedelta

        assert _iso_to_timedelta("P999D") is None
        assert _iso_to_timedelta("") is None
        assert _iso_to_timedelta("garbage") is None

    def test_never_returns_string(self):
        """Ensure no value in the mapping is a string — that would break the SDK call."""
        import datetime
        from services.api_gateway.vm_detail import _ISO_TO_TIMEDELTA

        for iso, td in _ISO_TO_TIMEDELTA.items():
            assert isinstance(td, datetime.timedelta), (
                f"_ISO_TO_TIMEDELTA[{iso!r}] is {td!r}, expected timedelta"
            )


# ---------------------------------------------------------------------------
# Unit tests: _parse_arc_metrics_response
# ---------------------------------------------------------------------------

class TestParseArcMetricsResponse:
    def test_basic_parsing(self):
        from services.api_gateway.vm_detail import _parse_arc_metrics_response

        rows = [
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": "45.2"},
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-12T10:05:00Z", "avg_CounterValue": "52.1"},
            {"CounterName": "Available MBytes", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": "2048.0"},
        ]
        result = _parse_arc_metrics_response(rows)

        assert len(result) == 2
        cpu = next(m for m in result if m["name"] == "Percentage CPU")
        assert len(cpu["timeseries"]) == 2
        assert cpu["unit"] == "Percent"
        assert cpu["timeseries"][0]["average"] == 45.2

        mem = next(m for m in result if m["name"] == "Available Memory Bytes")
        assert len(mem["timeseries"]) == 1

    def test_empty_rows(self):
        from services.api_gateway.vm_detail import _parse_arc_metrics_response

        result = _parse_arc_metrics_response([])
        assert result == []

    def test_unknown_counter_name(self):
        from services.api_gateway.vm_detail import _parse_arc_metrics_response

        rows = [
            {"CounterName": "CustomCounter", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": "99.0"},
        ]
        result = _parse_arc_metrics_response(rows)
        assert len(result) == 1
        assert result[0]["name"] == "CustomCounter"
        assert result[0]["unit"] == ""

    def test_deduplication_keeps_more_data(self):
        """When multiple counters map to the same metric name, keep the one with more data."""
        from services.api_gateway.vm_detail import _parse_arc_metrics_response

        rows = [
            # "Available MBytes" maps to "Available Memory Bytes" — 1 point
            {"CounterName": "Available MBytes", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": "2048.0"},
            # "Available Bytes" also maps to "Available Memory Bytes" — 3 points
            {"CounterName": "Available Bytes", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": "2147483648"},
            {"CounterName": "Available Bytes", "TimeGenerated": "2026-04-12T10:05:00Z", "avg_CounterValue": "2147483648"},
            {"CounterName": "Available Bytes", "TimeGenerated": "2026-04-12T10:10:00Z", "avg_CounterValue": "2147483648"},
        ]
        result = _parse_arc_metrics_response(rows)

        mem_metrics = [m for m in result if m["name"] == "Available Memory Bytes"]
        assert len(mem_metrics) == 1
        # Should keep the 3-point version (Available Bytes)
        assert len(mem_metrics[0]["timeseries"]) == 3

    def test_null_counter_value(self):
        from services.api_gateway.vm_detail import _parse_arc_metrics_response

        rows = [
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": None},
        ]
        result = _parse_arc_metrics_response(rows)
        assert len(result) == 1
        assert result[0]["timeseries"][0]["average"] is None


# ---------------------------------------------------------------------------
# Unit tests: _resolve_workspace_guid
# ---------------------------------------------------------------------------

class TestResolveWorkspaceGuid:
    def setup_method(self):
        # Clear the cache between tests
        from services.api_gateway import vm_detail
        vm_detail._workspace_guid_cache.clear()

    def test_empty_workspace_id(self):
        from services.api_gateway.vm_detail import _resolve_workspace_guid
        result = _resolve_workspace_guid(MagicMock(), "")
        assert result == ""

    @patch("services.api_gateway.vm_detail.LogAnalyticsManagementClient")
    def test_successful_resolution(self, mock_la_cls):
        from services.api_gateway.vm_detail import _resolve_workspace_guid

        mock_ws = MagicMock()
        mock_ws.customer_id = "abc-123-guid"
        mock_la_cls.return_value.workspaces.get.return_value = mock_ws

        result = _resolve_workspace_guid(MagicMock(), LA_WORKSPACE_RESOURCE_ID)
        assert result == "abc-123-guid"

    @patch("services.api_gateway.vm_detail.LogAnalyticsManagementClient")
    def test_cached_result(self, mock_la_cls):
        from services.api_gateway.vm_detail import _resolve_workspace_guid

        mock_ws = MagicMock()
        mock_ws.customer_id = "cached-guid"
        mock_la_cls.return_value.workspaces.get.return_value = mock_ws

        # First call resolves
        result1 = _resolve_workspace_guid(MagicMock(), LA_WORKSPACE_RESOURCE_ID)
        # Second call should use cache
        result2 = _resolve_workspace_guid(MagicMock(), LA_WORKSPACE_RESOURCE_ID)
        assert result1 == result2 == "cached-guid"
        # Only one actual API call
        assert mock_la_cls.return_value.workspaces.get.call_count == 1

    def test_unparseable_workspace_id(self):
        from services.api_gateway.vm_detail import _resolve_workspace_guid
        result = _resolve_workspace_guid(MagicMock(), "/invalid/path")
        assert result == ""

    @patch("services.api_gateway.vm_detail.LogAnalyticsManagementClient", None)
    def test_sdk_not_installed(self):
        from services.api_gateway.vm_detail import _resolve_workspace_guid
        result = _resolve_workspace_guid(MagicMock(), LA_WORKSPACE_RESOURCE_ID)
        assert result == ""


# ---------------------------------------------------------------------------
# Unit tests: _fetch_arc_vm_metrics_sync
# ---------------------------------------------------------------------------

def _mock_la_query_response(rows: List[Dict[str, Any]], status: str = "Success"):
    """Build a mock LogsQueryClient.query_workspace() response."""
    mock_response = MagicMock()
    mock_response.status = status

    if rows:
        col_names = list(rows[0].keys())
        mock_cols = []
        for name in col_names:
            col = MagicMock()
            col.name = name
            mock_cols.append(col)

        mock_table = MagicMock()
        mock_table.columns = mock_cols
        mock_table.rows = [
            [row.get(c, None) for c in col_names] for row in rows
        ]
        mock_response.tables = [mock_table]
    else:
        mock_response.tables = []

    return mock_response


class TestFetchArcVmMetricsSync:
    @patch("services.api_gateway.vm_detail.LogsQueryClient")
    @patch("services.api_gateway.vm_detail.LogsQueryStatus")
    def test_successful_fetch(self, mock_status_cls, mock_client_cls):
        from services.api_gateway.vm_detail import _fetch_arc_vm_metrics_sync

        mock_status_cls.SUCCESS = "Success"
        rows = [
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": "45.2"},
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-12T10:05:00Z", "avg_CounterValue": "52.1"},
        ]
        mock_client_cls.return_value.query_workspace.return_value = _mock_la_query_response(rows)

        result = _fetch_arc_vm_metrics_sync(
            credential=MagicMock(),
            workspace_guid="abc-guid",
            resource_id=ARC_RID,
            metric_names=["Percentage CPU"],
            timespan="PT24H",
            interval="PT5M",
        )

        assert len(result) == 1
        assert result[0]["name"] == "Percentage CPU"
        assert len(result[0]["timeseries"]) == 2

    @patch("services.api_gateway.vm_detail.LogsQueryClient", None)
    def test_sdk_not_installed(self):
        from services.api_gateway.vm_detail import _fetch_arc_vm_metrics_sync

        result = _fetch_arc_vm_metrics_sync(
            credential=MagicMock(),
            workspace_guid="abc-guid",
            resource_id=ARC_RID,
            metric_names=["Percentage CPU"],
            timespan="PT24H",
            interval="PT5M",
        )
        assert result == []

    @patch("services.api_gateway.vm_detail.LogsQueryClient")
    @patch("services.api_gateway.vm_detail.LogsQueryStatus")
    def test_empty_result(self, mock_status_cls, mock_client_cls):
        from services.api_gateway.vm_detail import _fetch_arc_vm_metrics_sync

        mock_status_cls.SUCCESS = "Success"
        mock_client_cls.return_value.query_workspace.return_value = _mock_la_query_response([])

        result = _fetch_arc_vm_metrics_sync(
            credential=MagicMock(),
            workspace_guid="abc-guid",
            resource_id=ARC_RID,
            metric_names=["Percentage CPU"],
            timespan="PT24H",
            interval="PT5M",
        )
        assert result == []

    @patch("services.api_gateway.vm_detail.LogsQueryClient")
    @patch("services.api_gateway.vm_detail.LogsQueryStatus")
    def test_fallback_to_default_counters(self, mock_status_cls, mock_client_cls):
        """When metric names don't map to any counters, fall back to defaults."""
        from services.api_gateway.vm_detail import _fetch_arc_vm_metrics_sync

        mock_status_cls.SUCCESS = "Success"
        rows = [
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-12T10:00:00Z", "avg_CounterValue": "30.0"},
        ]
        mock_client_cls.return_value.query_workspace.return_value = _mock_la_query_response(rows)

        result = _fetch_arc_vm_metrics_sync(
            credential=MagicMock(),
            workspace_guid="abc-guid",
            resource_id=ARC_RID,
            metric_names=["UnknownMetric"],
            timespan="PT24H",
            interval="PT5M",
        )
        # Should still get results from default counters
        assert len(result) >= 1

    @patch("services.api_gateway.vm_detail.LogsQueryClient")
    @patch("services.api_gateway.vm_detail.LogsQueryStatus")
    def test_query_exception_returns_empty(self, mock_status_cls, mock_client_cls):
        from services.api_gateway.vm_detail import _fetch_arc_vm_metrics_sync

        mock_status_cls.SUCCESS = "Success"
        mock_client_cls.return_value.query_workspace.side_effect = Exception("network error")

        result = _fetch_arc_vm_metrics_sync(
            credential=MagicMock(),
            workspace_guid="abc-guid",
            resource_id=ARC_RID,
            metric_names=["Percentage CPU"],
            timespan="PT24H",
            interval="PT5M",
        )
        assert result == []

    @patch("services.api_gateway.vm_detail.LogsQueryClient")
    @patch("services.api_gateway.vm_detail.LogsQueryStatus")
    def test_timespan_passed_as_timedelta_not_string(self, mock_status_cls, mock_client_cls):
        """query_workspace must receive a timedelta, never a raw ISO 8601 string.

        Passing a string (e.g. 'P7D') causes construct_iso8601() inside the SDK
        to raise ValueError, which our except-clause silently swallows → empty results.
        """
        import datetime
        from services.api_gateway.vm_detail import _fetch_arc_vm_metrics_sync

        mock_status_cls.SUCCESS = "Success"
        rows = [
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-09T01:00:00Z", "avg_CounterValue": "30.0"},
        ]
        mock_client_cls.return_value.query_workspace.return_value = _mock_la_query_response(rows)

        _fetch_arc_vm_metrics_sync(
            credential=MagicMock(),
            workspace_guid="abc-guid",
            resource_id=ARC_RID,
            metric_names=["Percentage CPU"],
            timespan="P7D",
            interval="PT1H",
        )

        call_kwargs = mock_client_cls.return_value.query_workspace.call_args
        passed_timespan = call_kwargs.kwargs.get("timespan") or call_kwargs[1].get("timespan")
        # Must be a timedelta (or None), never a raw string
        assert not isinstance(passed_timespan, str), (
            f"timespan was passed as a string ({passed_timespan!r}) — "
            "the SDK will raise ValueError and return empty results"
        )
        assert passed_timespan == datetime.timedelta(days=7)

    @patch("services.api_gateway.vm_detail.LogsQueryClient")
    @patch("services.api_gateway.vm_detail.LogsQueryStatus")
    def test_partial_failure_returns_partial_rows(self, mock_status_cls, mock_client_cls):
        """PARTIAL_FAILURE should return whatever rows are available, not empty list."""
        from services.api_gateway.vm_detail import _fetch_arc_vm_metrics_sync

        mock_status_cls.SUCCESS = "Success"
        rows = [
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-09T01:00:00Z", "avg_CounterValue": "55.0"},
            {"CounterName": "% Processor Time", "TimeGenerated": "2026-04-09T02:00:00Z", "avg_CounterValue": "60.0"},
        ]
        partial_response = _mock_la_query_response(rows, status="PartialFailure")
        mock_client_cls.return_value.query_workspace.return_value = partial_response

        result = _fetch_arc_vm_metrics_sync(
            credential=MagicMock(),
            workspace_guid="abc-guid",
            resource_id=ARC_RID,
            metric_names=["Percentage CPU"],
            timespan="PT24H",
            interval="PT1H",
        )
        # Partial data must be returned, not silently dropped
        assert len(result) == 1
        assert result[0]["name"] == "Percentage CPU"
        assert len(result[0]["timeseries"]) == 2


# ---------------------------------------------------------------------------
# Integration test: GET /api/v1/vms/{id}/metrics for Arc VMs
# ---------------------------------------------------------------------------

class TestGetVmMetricsArcEndpoint:
    """Test the get_vm_metrics endpoint branches correctly for Arc VMs."""

    def _make_test_client(self):
        from services.api_gateway.main import app
        from fastapi.testclient import TestClient

        app.state.credential = MagicMock()
        app.state.cosmos_client = None
        return TestClient(app)

    @patch("services.api_gateway.vm_detail._LA_WORKSPACE_RESOURCE_ID", LA_WORKSPACE_RESOURCE_ID)
    @patch("services.api_gateway.vm_detail._resolve_workspace_guid", return_value="abc-guid")
    @patch("services.api_gateway.vm_detail._fetch_arc_vm_metrics_sync")
    def test_arc_vm_uses_log_analytics(self, mock_fetch, mock_resolve):
        mock_fetch.return_value = [
            {"name": "Percentage CPU", "unit": "Percent", "timeseries": [
                {"timestamp": "2026-04-12T10:00:00Z", "average": 42.0, "maximum": 42.0, "minimum": 42.0}
            ]}
        ]

        tc = self._make_test_client()
        resp = tc.get(
            f"/api/v1/vms/{ARC_ENCODED}/metrics",
            params={"metrics": "Percentage CPU", "timespan": "PT24H", "interval": "PT5M"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "log_analytics"
        assert len(data["metrics"]) == 1
        assert data["metrics"][0]["name"] == "Percentage CPU"

    @patch("services.api_gateway.vm_detail._LA_WORKSPACE_RESOURCE_ID", "")
    def test_arc_vm_no_workspace_returns_empty(self):
        tc = self._make_test_client()
        resp = tc.get(
            f"/api/v1/vms/{ARC_ENCODED}/metrics",
            params={"metrics": "Percentage CPU"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "log_analytics"
        assert data["metrics"] == []
