"""Unit tests for SRE Agent tools — 22+ tests across 8 test classes.

Tests cover:
    TestAllowedMcpTools (3)          — ALLOWED_MCP_TOOLS list validation
    TestQueryAvailabilityMetrics (4) — availability computation and downtime windows
    TestQueryPerformanceBaselines (3)— baseline stats (avg, p95)
    TestQueryServiceHealth (3)       — service health events and region filter
    TestQueryAdvisorRecommendations (3) — advisor recommendations and category filter
    TestQueryChangeAnalysis (3)      — change analysis, datetime args, SDK guard
    TestCorrelateCrossDomain (3)     — pure Python correlation, approval, confidence
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


def _make_dp(average=None, maximum=None, minimum=None, time_stamp=None):
    dp = MagicMock()
    dp.average = average
    dp.maximum = maximum
    dp.minimum = minimum
    dp.time_stamp = time_stamp
    return dp


def _make_metric_response(datapoints):
    """Build a mock metrics.list() response with a single metric + timeseries."""
    ts = MagicMock()
    ts.data = datapoints
    metric = MagicMock()
    metric.name = MagicMock()
    metric.name.value = "Availability"
    metric.unit = MagicMock()
    metric.unit.value = "Percent"
    metric.timeseries = [ts]
    response = MagicMock()
    response.value = [metric]
    return response


# ---------------------------------------------------------------------------
# TestAllowedMcpTools
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_tools_is_list(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)

    def test_no_wildcard_in_allowed_tools(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        for entry in ALLOWED_MCP_TOOLS:
            assert "*" not in entry, f"Wildcard found in tool: {entry}"

    def test_allowed_tools_contains_resourcehealth_entry(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        assert "resourcehealth.get_availability_status" in ALLOWED_MCP_TOOLS


# ---------------------------------------------------------------------------
# TestQueryAvailabilityMetrics
# ---------------------------------------------------------------------------


class TestQueryAvailabilityMetrics:
    """Test query_availability_metrics — availability computation and downtime windows."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.MonitorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_success_returns_availability_percent(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # All datapoints at 100% — perfect availability
        dps = [_make_dp(average=100.0) for _ in range(5)]
        mock_client.metrics.list.return_value = _make_metric_response(dps)

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            timespan="PT24H",
        )

        assert result["query_status"] == "success"
        assert result["availability_percent"] == pytest.approx(100.0)
        assert result["data_point_count"] == 5

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.MonitorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_downtime_windows_detected_below_threshold(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # 2 points at 100%, 2 below threshold, 1 back at 100%
        t0 = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 4, 1, 0, 5, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 1, 0, 10, tzinfo=timezone.utc)
        t3 = datetime(2026, 4, 1, 0, 15, tzinfo=timezone.utc)
        t4 = datetime(2026, 4, 1, 0, 20, tzinfo=timezone.utc)

        dps = [
            _make_dp(average=100.0, time_stamp=t0),
            _make_dp(average=100.0, time_stamp=t1),
            _make_dp(average=50.0, time_stamp=t2),   # downtime starts
            _make_dp(average=50.0, time_stamp=t3),   # still down
            _make_dp(average=100.0, time_stamp=t4),  # recovery
        ]
        mock_client.metrics.list.return_value = _make_metric_response(dps)

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            timespan="PT24H",
        )

        assert result["query_status"] == "success"
        assert len(result["downtime_windows"]) >= 1

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.MonitorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_no_data_returns_none_availability(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # Empty timeseries — no datapoints
        mock_client.metrics.list.return_value = _make_metric_response([])

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            timespan="PT24H",
        )

        assert result["query_status"] == "success"
        assert result["availability_percent"] is None
        assert result["data_point_count"] == 0

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.MonitorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.metrics.list.side_effect = Exception("Monitor API unavailable")

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            timespan="PT24H",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert result["availability_percent"] is None


# ---------------------------------------------------------------------------
# TestQueryPerformanceBaselines
# ---------------------------------------------------------------------------


class TestQueryPerformanceBaselines:
    """Test query_performance_baselines — baseline stats and percentile computation."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.MonitorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_success_returns_baselines_list(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        dps = [_make_dp(average=float(i), maximum=float(i + 10)) for i in range(10)]
        mock_client.metrics.list.return_value = _make_metric_response(dps)

        from agents.sre.tools import query_performance_baselines

        result = query_performance_baselines(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            metric_names=["Percentage CPU"],
            baseline_period="P7D",
        )

        assert result["query_status"] == "success"
        assert len(result["baselines"]) == 1
        baseline = result["baselines"][0]
        assert baseline["metric_name"] == "Percentage CPU"
        assert baseline["avg"] is not None
        assert baseline["data_point_count"] == 10

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.MonitorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_p95_computed_from_timeseries(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # 100 datapoints: values 0..99
        dps = [_make_dp(average=float(i), maximum=float(i)) for i in range(100)]
        mock_client.metrics.list.return_value = _make_metric_response(dps)

        from agents.sre.tools import query_performance_baselines

        result = query_performance_baselines(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            metric_names=["Percentage CPU"],
            baseline_period="P7D",
        )

        assert result["query_status"] == "success"
        baseline = result["baselines"][0]
        # p95 index = int(100 * 0.95) = 95 (clamped to 99), sorted vals[95] = 95.0
        assert baseline["p95"] == 95.0
        # p99 index = int(100 * 0.99) = 99, sorted vals[99] = 99.0
        assert baseline["p99"] == 99.0

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.MonitorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.metrics.list.side_effect = Exception("SDK error")

        from agents.sre.tools import query_performance_baselines

        result = query_performance_baselines(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            metric_names=["Percentage CPU"],
            baseline_period="P7D",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert result["baselines"] == []


# ---------------------------------------------------------------------------
# TestQueryServiceHealth
# ---------------------------------------------------------------------------


def _make_service_health_event(title="OutageMock", region="eastus", service="Compute"):
    event = MagicMock()
    event.id = "/subscriptions/sub-1/providers/Microsoft.ResourceHealth/events/evt-1"
    props = MagicMock()
    props.event_type = "ServiceIssue"
    props.status = "Active"
    props.title = title
    props.activation_time = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    # Impacted regions
    region_mock = MagicMock()
    region_mock.region_name = region
    props.impacted_regions = [region_mock]
    # Impacted services
    svc_mock = MagicMock()
    svc_mock.service_name = service
    props.impact = [svc_mock]
    event.properties = props
    return event


class TestQueryServiceHealth:
    """Test query_service_health — events, region filter, SDK guard."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.ServiceHealthClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_success_returns_events_list(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.events.list_by_subscription_id.return_value = [
            _make_service_health_event()
        ]

        from agents.sre.tools import query_service_health

        result = query_service_health(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["event_count"] == 1
        assert result["events"][0]["title"] == "OutageMock"

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.ServiceHealthClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_region_filter_applied_when_provided(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # Two events in different regions
        evt_east = _make_service_health_event(title="East Outage", region="eastus")
        evt_west = _make_service_health_event(title="West Outage", region="westus")
        mock_client.events.list_by_subscription_id.return_value = [evt_east, evt_west]

        from agents.sre.tools import query_service_health

        result = query_service_health(
            subscription_id="sub-1", regions=["westus"]
        )

        assert result["query_status"] == "success"
        assert result["event_count"] == 1
        assert result["events"][0]["title"] == "West Outage"

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_sdk_not_installed_returns_error(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        import agents.sre.tools as tools_mod

        original = tools_mod.ServiceHealthClient
        tools_mod.ServiceHealthClient = None
        try:
            from agents.sre.tools import query_service_health

            result = query_service_health(subscription_id="sub-1")
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_mod.ServiceHealthClient = original


# ---------------------------------------------------------------------------
# TestQueryAdvisorRecommendations
# ---------------------------------------------------------------------------


def _make_advisor_rec(category="HighAvailability", impact="High"):
    rec = MagicMock()
    rec.id = "/subscriptions/sub-1/providers/Microsoft.Advisor/recommendations/rec-1"
    props = MagicMock()
    props.category = category
    props.impact = impact
    short_desc = MagicMock()
    short_desc.problem = "Consider enabling zone-redundant deployment"
    props.short_description = short_desc
    rec.properties = props
    return rec


class TestQueryAdvisorRecommendations:
    """Test query_advisor_recommendations — recommendations and category filter."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.AdvisorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_success_returns_recommendations(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.recommendations.list.return_value = [
            _make_advisor_rec(),
            _make_advisor_rec(category="Security", impact="Medium"),
        ]

        from agents.sre.tools import query_advisor_recommendations

        result = query_advisor_recommendations(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["total_count"] == 2
        assert result["category_filter"] is None

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.AdvisorManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_category_filter_passed_to_sdk(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.recommendations.list.return_value = [_make_advisor_rec()]

        from agents.sre.tools import query_advisor_recommendations

        result = query_advisor_recommendations(
            subscription_id="sub-1", category="HighAvailability"
        )

        assert result["query_status"] == "success"
        assert result["category_filter"] == "HighAvailability"
        # Verify filter was passed to the SDK
        call_kwargs = mock_client.recommendations.list.call_args
        assert call_kwargs is not None
        if call_kwargs[1]:
            assert "HighAvailability" in call_kwargs[1].get("filter", "")
        else:
            assert "HighAvailability" in str(call_kwargs)

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_sdk_not_installed_returns_error(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        import agents.sre.tools as tools_mod

        original = tools_mod.AdvisorManagementClient
        tools_mod.AdvisorManagementClient = None
        try:
            from agents.sre.tools import query_advisor_recommendations

            result = query_advisor_recommendations(subscription_id="sub-1")
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_mod.AdvisorManagementClient = original


# ---------------------------------------------------------------------------
# TestQueryChangeAnalysis
# ---------------------------------------------------------------------------


def _make_change(resource_id="/sub/rg/vm1", change_type="Update"):
    change = MagicMock()
    change.resource_id = resource_id
    props = MagicMock()
    props.change_type = change_type
    props.time_stamp = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    # Property changes
    pc = MagicMock()
    pc.property_name = "sku"
    pc.old_value = "Standard_D2s_v3"
    pc.new_value = "Standard_D4s_v3"
    props.property_changes = [pc]
    change.properties = props
    return change


class TestQueryChangeAnalysis:
    """Test query_change_analysis — changes list, datetime args, SDK guard."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.AzureChangeAnalysisManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_success_returns_changes_list(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.changes.list_changes_by_resource_group.return_value = [
            _make_change()
        ]

        from agents.sre.tools import query_change_analysis

        result = query_change_analysis(
            subscription_id="sub-1",
            resource_group="rg-prod",
            timespan_hours=24,
        )

        assert result["query_status"] == "success"
        assert result["total_count"] == 1
        assert result["changes"][0]["change_type"] == "Update"

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.AzureChangeAnalysisManagementClient")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_datetime_args_passed_to_sdk_not_strings(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.changes.list_changes_by_resource_group.return_value = []

        from agents.sre.tools import query_change_analysis

        query_change_analysis(
            subscription_id="sub-1", resource_group="rg", timespan_hours=24
        )

        call_kwargs = mock_client.changes.list_changes_by_resource_group.call_args[1]
        # Both start_time and end_time must be datetime objects, not strings
        assert isinstance(call_kwargs["start_time"], datetime), (
            f"start_time should be datetime, got {type(call_kwargs['start_time'])}"
        )
        assert isinstance(call_kwargs["end_time"], datetime), (
            f"end_time should be datetime, got {type(call_kwargs['end_time'])}"
        )

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    def test_sdk_not_installed_returns_error(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        import agents.sre.tools as tools_mod

        original = tools_mod.AzureChangeAnalysisManagementClient
        tools_mod.AzureChangeAnalysisManagementClient = None
        try:
            from agents.sre.tools import query_change_analysis

            result = query_change_analysis(
                subscription_id="sub-1",
                resource_group="rg-prod",
                timespan_hours=24,
            )
            assert result["query_status"] == "error"
            assert "not installed" in result["error"]
        finally:
            tools_mod.AzureChangeAnalysisManagementClient = original


# ---------------------------------------------------------------------------
# TestCorrelateCrossDomain
# ---------------------------------------------------------------------------


class TestCorrelateCrossDomain:
    """Test correlate_cross_domain — pure Python, no SDK mocks needed."""

    def test_requires_approval_always_true(self):
        from agents.sre.tools import correlate_cross_domain

        # No @patch needed — pure Python, no Azure SDK
        result = correlate_cross_domain(
            incident_id="INC-001",
            domain_findings=[
                {
                    "domain": "compute",
                    "finding_type": "cpu_spike",
                    "severity": "High",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "description": "CPU at 95%",
                }
            ],
        )
        assert result["requires_approval"] is True
        assert result["incident_id"] == "INC-001"

    def test_top_hypotheses_sorted_by_confidence(self):
        from agents.sre.tools import correlate_cross_domain

        # 3 domains with varying evidence counts — more findings → higher confidence
        findings = [
            # compute: 3 findings — highest score
            {
                "domain": "compute",
                "finding_type": "cpu_spike",
                "severity": "High",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": "CPU at 95%",
            },
            {
                "domain": "compute",
                "finding_type": "memory_pressure",
                "severity": "Medium",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": "Memory at 85%",
            },
            {
                "domain": "compute",
                "finding_type": "disk_io",
                "severity": "Low",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": "Disk IO elevated",
            },
            # network: 1 finding — lower score
            {
                "domain": "network",
                "finding_type": "nsg_block",
                "severity": "Low",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": "NSG rule blocking traffic",
            },
        ]

        result = correlate_cross_domain(incident_id="INC-002", domain_findings=findings)

        assert result["query_status"] if "query_status" in result else True
        assert len(result["top_hypotheses"]) >= 1
        # Compute should be first (most findings)
        assert result["top_hypotheses"][0]["domain"] == "compute"
        # Scores should be descending
        scores = [h["confidence_score"] for h in result["top_hypotheses"]]
        assert scores == sorted(scores, reverse=True)

    def test_empty_findings_returns_empty_hypotheses(self):
        from agents.sre.tools import correlate_cross_domain

        result = correlate_cross_domain(
            incident_id="INC-003",
            domain_findings=[],
        )

        assert result["requires_approval"] is True
        assert result["finding_count"] == 0
        assert result["top_hypotheses"] == []
        assert result["recommended_actions"] == []
