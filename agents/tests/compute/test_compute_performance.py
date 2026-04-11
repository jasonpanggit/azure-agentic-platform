"""Tests for Phase 37 performance intelligence tool functions.

Covers: get_vm_forecast, query_vm_performance_baseline, detect_performance_drift.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    """Return a context-manager-compatible MagicMock."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ---------------------------------------------------------------------------
# TestGetVmForecast
# ---------------------------------------------------------------------------


class TestGetVmForecast:
    _RESOURCE_ID = (
        "/subscriptions/sub-1/resourceGroups/rg1"
        "/providers/Microsoft.Compute/virtualMachines/vm-prod"
    )

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ForecasterClient")
    @patch("agents.compute.tools.CosmosClient")
    @patch("agents.compute.tools.get_credential")
    def test_get_vm_forecast_success_multiple_metrics(
        self, mock_cred, mock_cosmos_cls, mock_forecaster_cls, mock_identity, mock_instr,
        monkeypatch,
    ):
        """Multiple forecasts returned with correct imminent_breach flags."""
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos.example.com")
        mock_instr.return_value = _instrument_mock()

        mock_forecaster = MagicMock()
        mock_forecaster_cls.return_value = mock_forecaster
        mock_forecaster.get_forecasts.return_value = [
            {
                "metric_name": "Percentage CPU",
                "time_to_breach_minutes": 120.0,
                "confidence": "high",
                "mape": 8.5,
                "level": 75.0,
                "trend": 0.5,
                "threshold": 90.0,
                "last_updated": "2026-04-11T00:00:00Z",
            },
            {
                "metric_name": "Available Memory Bytes",
                "time_to_breach_minutes": 45.0,
                "confidence": "medium",
                "mape": 18.0,
                "level": 0.5,
                "trend": -0.02,
                "threshold": 0.1,
                "last_updated": "2026-04-11T00:00:00Z",
            },
        ]

        from agents.compute.tools import get_vm_forecast

        result = get_vm_forecast(
            resource_id=self._RESOURCE_ID,
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["total_forecasts"] == 2
        assert "duration_ms" in result
        forecasts = result["forecasts"]
        cpu_fc = next(f for f in forecasts if f["metric_name"] == "Percentage CPU")
        mem_fc = next(f for f in forecasts if f["metric_name"] == "Available Memory Bytes")
        assert cpu_fc["imminent_breach"] is False   # 120 min > 60
        assert mem_fc["imminent_breach"] is True    # 45 min < 60
        assert result["imminent_breach_count"] == 1

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ForecasterClient")
    @patch("agents.compute.tools.CosmosClient")
    @patch("agents.compute.tools.get_credential")
    def test_get_vm_forecast_imminent_breach_all_metrics(
        self, mock_cred, mock_cosmos_cls, mock_forecaster_cls, mock_identity, mock_instr,
        monkeypatch,
    ):
        """All three metrics breach within 60 min — imminent_breach_count == 3."""
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos.example.com")
        mock_instr.return_value = _instrument_mock()

        mock_forecaster = MagicMock()
        mock_forecaster_cls.return_value = mock_forecaster
        mock_forecaster.get_forecasts.return_value = [
            {"metric_name": "Percentage CPU", "time_to_breach_minutes": 30.0, "confidence": "high", "mape": 5.0, "level": 88.0, "trend": 0.3, "threshold": 90.0, "last_updated": "2026-04-11T00:00:00Z"},
            {"metric_name": "Available Memory Bytes", "time_to_breach_minutes": 20.0, "confidence": "medium", "mape": 22.0, "level": 0.2, "trend": -0.01, "threshold": 0.1, "last_updated": "2026-04-11T00:00:00Z"},
            {"metric_name": "OS Disk Queue Depth", "time_to_breach_minutes": 55.0, "confidence": "low", "mape": 35.0, "level": 9.0, "trend": 0.1, "threshold": 10.0, "last_updated": "2026-04-11T00:00:00Z"},
        ]

        from agents.compute.tools import get_vm_forecast

        result = get_vm_forecast(
            resource_id=self._RESOURCE_ID,
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["imminent_breach_count"] == 3
        assert all(f["imminent_breach"] is True for f in result["forecasts"])

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CosmosClient")
    @patch("agents.compute.tools.get_credential")
    def test_get_vm_forecast_missing_cosmos_env(
        self, mock_cred, mock_cosmos_cls, mock_identity, mock_instr, monkeypatch
    ):
        """Missing COSMOS_ENDPOINT env var → error dict, no SDK call."""
        monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import get_vm_forecast

        result = get_vm_forecast(
            resource_id=self._RESOURCE_ID,
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "COSMOS_ENDPOINT" in result["error"]
        assert "duration_ms" in result
        mock_cosmos_cls.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CosmosClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_get_vm_forecast_sdk_unavailable(
        self, mock_cred, mock_identity, mock_instr, monkeypatch
    ):
        """CosmosClient is None (ImportError path) → graceful error dict."""
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos.example.com")
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import get_vm_forecast

        result = get_vm_forecast(
            resource_id=self._RESOURCE_ID,
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ForecasterClient")
    @patch("agents.compute.tools.CosmosClient")
    @patch("agents.compute.tools.get_credential")
    def test_get_vm_forecast_sdk_exception(
        self, mock_cred, mock_cosmos_cls, mock_forecaster_cls, mock_identity, mock_instr,
        monkeypatch,
    ):
        """ForecasterClient.get_forecasts raises → error dict, no re-raise."""
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos.example.com")
        mock_instr.return_value = _instrument_mock()

        mock_forecaster = MagicMock()
        mock_forecaster_cls.return_value = mock_forecaster
        mock_forecaster.get_forecasts.side_effect = RuntimeError("Cosmos unavailable")

        from agents.compute.tools import get_vm_forecast

        result = get_vm_forecast(
            resource_id=self._RESOURCE_ID,
            subscription_id="sub-1",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "Cosmos unavailable" in result["error"]
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# TestQueryVmPerformanceBaseline
# ---------------------------------------------------------------------------


class TestQueryVmPerformanceBaseline:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_baseline_perf_table_success(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """Perf table returns rows → metrics dict with p50/p95/p99."""
        mock_instr.return_value = _instrument_mock()

        col_obj = MagicMock()
        col_obj.name = "ObjectName"
        col_counter = MagicMock()
        col_counter.name = "CounterName"
        col_p50 = MagicMock()
        col_p50.name = "p50"
        col_p95 = MagicMock()
        col_p95.name = "p95"
        col_p99 = MagicMock()
        col_p99.name = "p99"
        col_count = MagicMock()
        col_count.name = "sample_count"

        mock_table = MagicMock()
        mock_table.columns = [col_obj, col_counter, col_p50, col_p95, col_p99, col_count]
        mock_table.rows = [
            ["Processor", "% Processor Time", 42.0, 78.5, 89.0, 8640],
            ["Memory", "Available MBytes", 3200.0, 2100.0, 1800.0, 8640],
        ]

        mock_resp = MagicMock()
        mock_resp.status = mock_status_cls.SUCCESS
        mock_resp.tables = [mock_table]

        mock_client = MagicMock()
        mock_client.query_workspace.return_value = mock_resp
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import query_vm_performance_baseline

        result = query_vm_performance_baseline(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["baseline_window_days"] == 30
        assert result["used_fallback_table"] is False
        assert "cpu_pct" in result["metrics"]
        assert "memory_available_mb" in result["metrics"]
        cpu = result["metrics"]["cpu_pct"]
        assert cpu["p50"] == 42.0
        assert cpu["p95"] == 78.5
        assert cpu["p99"] == 89.0
        assert cpu["sample_count"] == 8640
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_baseline_insights_metrics_fallback(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """Perf table returns empty rows → InsightsMetrics fallback used."""
        mock_instr.return_value = _instrument_mock()

        # First call (Perf): empty table
        empty_table = MagicMock()
        empty_table.columns = []
        empty_table.rows = []
        empty_resp = MagicMock()
        empty_resp.status = mock_status_cls.SUCCESS
        empty_resp.tables = [empty_table]

        # Second call (InsightsMetrics): has data
        col_ns = MagicMock()
        col_ns.name = "Namespace"
        col_name = MagicMock()
        col_name.name = "Name"
        col_p50 = MagicMock()
        col_p50.name = "p50"
        col_p95 = MagicMock()
        col_p95.name = "p95"
        col_p99 = MagicMock()
        col_p99.name = "p99"
        col_cnt = MagicMock()
        col_cnt.name = "sample_count"

        fallback_table = MagicMock()
        fallback_table.columns = [col_ns, col_name, col_p50, col_p95, col_p99, col_cnt]
        fallback_table.rows = [
            ["Processor", "UtilizationPercentage", 50.0, 82.0, 91.0, 4320],
        ]
        fallback_resp = MagicMock()
        fallback_resp.status = mock_status_cls.SUCCESS
        fallback_resp.tables = [fallback_table]

        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = [empty_resp, fallback_resp]
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import query_vm_performance_baseline

        result = query_vm_performance_baseline(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["used_fallback_table"] is True
        assert "cpu_pct" in result["metrics"]
        assert mock_client.query_workspace.call_count == 2

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_baseline_missing_workspace_id(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """Empty workspace_id → skipped status, no SDK call."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_vm_performance_baseline

        result = query_vm_performance_baseline(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="",
            thread_id="thread-1",
        )

        assert result["query_status"] == "skipped"
        assert "duration_ms" in result
        mock_logs_cls.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_baseline_empty_result_set(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """Both Perf and InsightsMetrics return empty → success with empty metrics."""
        mock_instr.return_value = _instrument_mock()

        empty_table = MagicMock()
        empty_table.columns = []
        empty_table.rows = []
        empty_resp = MagicMock()
        empty_resp.status = mock_status_cls.SUCCESS
        empty_resp.tables = [empty_table]

        mock_client = MagicMock()
        mock_client.query_workspace.return_value = empty_resp
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import query_vm_performance_baseline

        result = query_vm_performance_baseline(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["metric_count"] == 0
        assert result["metrics"] == {}

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_baseline_sdk_exception(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """LogsQueryClient raises → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = RuntimeError("workspace timeout")
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import query_vm_performance_baseline

        result = query_vm_performance_baseline(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "duration_ms" in result
        assert "workspace timeout" in result["error"]


# ---------------------------------------------------------------------------
# TestDetectPerformanceDrift
# ---------------------------------------------------------------------------


class TestDetectPerformanceDrift:
    def _make_drift_responses(self, mock_status_cls, baseline_p95: float, recent_p95: float):
        """Build paired mock responses for baseline (30d) and recent (24h) queries."""
        def _make_table(col_names, rows):
            table = MagicMock()
            cols = []
            for name in col_names:
                c = MagicMock()
                c.name = name
                cols.append(c)
            table.columns = cols
            table.rows = rows
            return table

        # Baseline response
        baseline_table = _make_table(
            ["ObjectName", "CounterName", "baseline_p95"],
            [["Processor", "% Processor Time", baseline_p95]],
        )
        baseline_resp = MagicMock()
        baseline_resp.status = mock_status_cls.SUCCESS
        baseline_resp.tables = [baseline_table]

        # Recent response
        recent_table = _make_table(
            ["ObjectName", "CounterName", "recent_avg", "recent_p95"],
            [["Processor", "% Processor Time", recent_p95 * 0.9, recent_p95]],
        )
        recent_resp = MagicMock()
        recent_resp.status = mock_status_cls.SUCCESS
        recent_resp.tables = [recent_table]

        return baseline_resp, recent_resp

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_drift_score_above_threshold_flagged(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """CPU P95 well above baseline → drift_score > 30 and is_drifting=True."""
        mock_instr.return_value = _instrument_mock()

        baseline_resp, recent_resp = self._make_drift_responses(
            mock_status_cls, baseline_p95=50.0, recent_p95=85.0
        )
        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = [baseline_resp, recent_resp]
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import detect_performance_drift

        result = detect_performance_drift(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["is_drifting"] is True
        cpu_drift = result["drift_metrics"]["cpu_pct"]
        assert cpu_drift["drift_score"] > 30
        assert cpu_drift["is_drifting"] is True
        # drift_score = min(100, int((85/50 - 1) * 100)) = min(100, 70) = 70
        assert cpu_drift["drift_score"] == 70
        assert "above normal" in result["narrative"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_drift_score_nominal_no_flag(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """CPU P95 close to baseline → drift_score <= 30 and is_drifting=False."""
        mock_instr.return_value = _instrument_mock()

        baseline_resp, recent_resp = self._make_drift_responses(
            mock_status_cls, baseline_p95=50.0, recent_p95=55.0
        )
        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = [baseline_resp, recent_resp]
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import detect_performance_drift

        result = detect_performance_drift(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["is_drifting"] is False
        cpu_drift = result["drift_metrics"]["cpu_pct"]
        # drift_score = min(100, int((55/50 - 1) * 100)) = min(100, 10) = 10
        assert cpu_drift["drift_score"] == 10
        assert cpu_drift["is_drifting"] is False

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_drift_missing_workspace_id(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """Empty workspace_id → skipped status, no SDK call."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import detect_performance_drift

        result = detect_performance_drift(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="",
            thread_id="thread-1",
        )

        assert result["query_status"] == "skipped"
        assert "duration_ms" in result
        mock_logs_cls.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_drift_baseline_zero_guard(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """Baseline P95 is zero → drift_score is 0, no ZeroDivisionError."""
        mock_instr.return_value = _instrument_mock()

        baseline_resp, recent_resp = self._make_drift_responses(
            mock_status_cls, baseline_p95=0.0, recent_p95=50.0
        )
        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = [baseline_resp, recent_resp]
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import detect_performance_drift

        result = detect_performance_drift(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        # Must not raise; drift_score should be 0 when baseline is 0
        assert result["query_status"] == "success"
        assert result["drift_metrics"]["cpu_pct"]["drift_score"] == 0

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_drift_sdk_exception(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """LogsQueryClient raises → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = RuntimeError("Log Analytics offline")
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import detect_performance_drift

        result = detect_performance_drift(
            resource_group="rg1",
            vm_name="vm-prod",
            subscription_id="sub-1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "duration_ms" in result
        assert "Log Analytics offline" in result["error"]
