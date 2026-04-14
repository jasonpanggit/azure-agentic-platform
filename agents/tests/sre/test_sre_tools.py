"""Unit tests for SRE Agent tools (Phase 20 — Plan 20-04).

Tests all 7 SRE tools + ALLOWED_MCP_TOOLS.
Each tool has success path, error path, and SDK-missing path tests.
Pattern follows agents/tests/patch/test_patch_tools.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _mock_with_name(mock_name: str, **kwargs) -> MagicMock:
    """Create a MagicMock with .name as a real attribute."""
    m = MagicMock(**kwargs)
    m.name = mock_name
    return m


# ---------------------------------------------------------------------------
# ALLOWED_MCP_TOOLS
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_mcp_tools_has_exactly_nine_entries(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 9

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        expected = [
            "monitor.query_logs",
            "monitor.query_metrics",
            "applicationinsights.query",
            "advisor.list_recommendations",
            "resourcehealth.get_availability_status",
            "resourcehealth.list_events",
            "containerapps.list_apps",
            "containerapps.get_app",
            "containerapps.list_revisions",
        ]
        for tool in expected:
            assert tool in ALLOWED_MCP_TOOLS, f"Missing: {tool}"

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"


# ---------------------------------------------------------------------------
# query_availability_metrics
# ---------------------------------------------------------------------------


class TestQueryAvailabilityMetrics:
    """Verify query_availability_metrics returns expected structure."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient")
    def test_returns_success_with_availability(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_dp = MagicMock(
            time_stamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            average=99.95,
            minimum=99.8,
        )
        mock_ts = MagicMock(data=[mock_dp])
        mock_metric = _mock_with_name("Availability", timeseries=[mock_ts])
        mock_response = MagicMock(value=[mock_metric])
        mock_client_cls.return_value.metrics.list.return_value = mock_response

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
        )

        assert result["query_status"] == "success"
        assert result["availability_percent"] == pytest.approx(99.95)
        assert result["data_point_count"] == 1

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient")
    def test_returns_none_availability_when_no_data(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_ts = MagicMock(data=[])
        mock_metric = _mock_with_name("Availability", timeseries=[mock_ts])
        mock_response = MagicMock(value=[mock_metric])
        mock_client_cls.return_value.metrics.list.return_value = mock_response

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
        )

        assert result["query_status"] == "success"
        assert result["availability_percent"] is None
        assert result["data_point_count"] == 0

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.metrics.list.side_effect = Exception("Monitor unavailable")

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
        )

        assert result["query_status"] == "error"
        assert "Monitor unavailable" in result["error"]

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.sre.tools import query_availability_metrics

        result = query_availability_metrics(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_performance_baselines
# ---------------------------------------------------------------------------


class TestQueryPerformanceBaselines:
    """Verify query_performance_baselines returns expected structure."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient")
    def test_returns_success_with_baselines(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        # Create 10 data points
        data_points = []
        for i in range(1, 11):
            dp = MagicMock(average=float(i * 10), minimum=float(i * 10 - 5), maximum=float(i * 10 + 5))
            data_points.append(dp)

        mock_ts = MagicMock(data=data_points)
        mock_metric = MagicMock(timeseries=[mock_ts])
        mock_metric.name = MagicMock(value="Percentage CPU")
        mock_response = MagicMock(value=[mock_metric])
        mock_client_cls.return_value.metrics.list.return_value = mock_response

        from agents.sre.tools import query_performance_baselines

        result = query_performance_baselines(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            metric_names=["Percentage CPU"],
        )

        assert result["query_status"] == "success"
        assert len(result["baselines"]) == 1
        assert result["baselines"][0]["metric_name"] == "Percentage CPU"
        assert result["baselines"][0]["avg"] == pytest.approx(55.0)
        assert result["baselines"][0]["data_point_count"] == 10
        # p95 should be at index int(0.95 * 9) = 8 of sorted [10..100] = 90
        assert result["baselines"][0]["p95"] == 90.0

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient")
    def test_returns_empty_baselines_when_no_data(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_ts = MagicMock(data=[])
        mock_metric = MagicMock(timeseries=[mock_ts])
        mock_metric.name = MagicMock(value="Percentage CPU")
        mock_response = MagicMock(value=[mock_metric])
        mock_client_cls.return_value.metrics.list.return_value = mock_response

        from agents.sre.tools import query_performance_baselines

        result = query_performance_baselines(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            metric_names=["Percentage CPU"],
        )

        assert result["query_status"] == "success"
        assert len(result["baselines"]) == 1
        assert result["baselines"][0]["avg"] is None
        assert result["baselines"][0]["p95"] is None

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.metrics.list.side_effect = Exception("Monitor unavailable")

        from agents.sre.tools import query_performance_baselines

        result = query_performance_baselines(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            metric_names=["Percentage CPU"],
        )

        assert result["query_status"] == "error"
        assert "Monitor unavailable" in result["error"]

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.MonitorManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.sre.tools import query_performance_baselines

        result = query_performance_baselines(
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            metric_names=["Percentage CPU"],
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# propose_remediation
# ---------------------------------------------------------------------------


class TestProposeRemediation:
    """Verify propose_remediation returns expected structure."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    def test_returns_success_with_approval_required(
        self, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.sre.tools import propose_remediation

        result = propose_remediation(
            incident_id="inc-001",
            hypothesis="Memory leak causing OOM",
            affected_resources=["/sub/vm-1"],
            action_type="restart",
            description="Restart VM to clear memory leak",
            risk_level="low",
            reversibility="Fully reversible",
        )

        assert result["requires_approval"] is True
        assert result["incident_id"] == "inc-001"

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    def test_contains_all_required_fields(
        self, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.sre.tools import propose_remediation

        result = propose_remediation(
            incident_id="inc-002",
            hypothesis="Network partition",
            affected_resources=["/sub/nsg-1", "/sub/vnet-1"],
            action_type="escalate",
            description="Escalate to network team",
            risk_level="medium",
            reversibility="N/A — escalation only",
        )

        required_fields = [
            "incident_id", "hypothesis", "affected_resources",
            "action_type", "description", "risk_level",
            "reversibility", "requires_approval",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# query_service_health
# ---------------------------------------------------------------------------


class TestQueryServiceHealth:
    """Verify query_service_health returns expected structure."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.ResourceHealthMgmtClient")
    def test_returns_success_with_events(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_event = MagicMock(
            event_type="ServiceIssue",
            summary="Compute degradation in West US 2",
            status="Active",
            impact_start_time=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            last_update_time=datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            header="Service Issue",
            level="Warning",
        )
        mock_client_cls.return_value.events.list_by_subscription_id.return_value = [mock_event]

        from agents.sre.tools import query_service_health

        result = query_service_health(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["event_count"] == 1
        assert result["active_count"] == 1
        assert result["events"][0]["event_type"] == "ServiceIssue"

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.ResourceHealthMgmtClient")
    def test_event_type_filter(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        ev1 = MagicMock(
            event_type="ServiceIssue", summary="Issue 1", status="Active",
            impact_start_time=None, last_update_time=None, header=None, level="Warning",
        )
        ev2 = MagicMock(
            event_type="PlannedMaintenance", summary="Maintenance 1", status="Active",
            impact_start_time=None, last_update_time=None, header=None, level="Information",
        )
        mock_client_cls.return_value.events.list_by_subscription_id.return_value = [ev1, ev2]

        from agents.sre.tools import query_service_health

        result = query_service_health(
            subscription_id="sub-test-1",
            event_type="ServiceIssue",
        )

        assert result["query_status"] == "success"
        assert result["event_count"] == 1
        assert result["events"][0]["event_type"] == "ServiceIssue"

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.ResourceHealthMgmtClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.events.list_by_subscription_id.side_effect = Exception(
            "Health service unavailable"
        )

        from agents.sre.tools import query_service_health

        result = query_service_health(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Health service unavailable" in result["error"]

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.ResourceHealthMgmtClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.sre.tools import query_service_health

        result = query_service_health(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_advisor_recommendations
# ---------------------------------------------------------------------------


class TestQueryAdvisorRecommendations:
    """Verify query_advisor_recommendations returns expected structure."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AdvisorManagementClient")
    def test_returns_success_with_recommendations(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_rec = MagicMock(
            category="HighAvailability",
            impact="High",
            impacted_field="Microsoft.Compute/virtualMachines",
            impacted_value="vm-1",
            short_description=MagicMock(problem="VM not in availability set", solution="Add to AS"),
            resource_metadata=MagicMock(resource_id="/sub/vm-1"),
        )
        mock_client_cls.return_value.recommendations.list.return_value = [mock_rec]

        from agents.sre.tools import query_advisor_recommendations

        result = query_advisor_recommendations(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["recommendation_count"] == 1
        assert result["high_impact_count"] == 1
        assert result["recommendations"][0]["category"] == "HighAvailability"

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AdvisorManagementClient")
    def test_category_filter(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        rec_ha = MagicMock(
            category="HighAvailability", impact="High", impacted_field="vm",
            impacted_value="vm-1", short_description=None, resource_metadata=None,
        )
        rec_cost = MagicMock(
            category="Cost", impact="Medium", impacted_field="vm",
            impacted_value="vm-2", short_description=None, resource_metadata=None,
        )
        rec_sec = MagicMock(
            category="Security", impact="High", impacted_field="nsg",
            impacted_value="nsg-1", short_description=None, resource_metadata=None,
        )
        mock_client_cls.return_value.recommendations.list.return_value = [
            rec_ha, rec_cost, rec_sec
        ]

        from agents.sre.tools import query_advisor_recommendations

        result = query_advisor_recommendations(
            subscription_id="sub-test-1",
            category="HighAvailability",
        )

        assert result["query_status"] == "success"
        assert result["recommendation_count"] == 1

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AdvisorManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.recommendations.list.side_effect = Exception(
            "Advisor unavailable"
        )

        from agents.sre.tools import query_advisor_recommendations

        result = query_advisor_recommendations(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Advisor unavailable" in result["error"]

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AdvisorManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.sre.tools import query_advisor_recommendations

        result = query_advisor_recommendations(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_change_analysis
# ---------------------------------------------------------------------------


class TestQueryChangeAnalysis:
    """Verify query_change_analysis returns expected structure."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AzureChangeAnalysisManagementClient")
    def test_returns_success_subscription_level(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_pc = MagicMock(property_name="vmSize", old_value="Standard_D2s_v3",
                            new_value="Standard_D4s_v3")
        mock_change = MagicMock(
            resource_id="/sub/vm-1",
            change_type="Update",
            time_stamp=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
            initiated_by_list=["admin@contoso.com"],
            property_changes=[mock_pc],
        )
        mock_client_cls.return_value.changes.list_changes_by_subscription.return_value = [
            mock_change
        ]

        from agents.sre.tools import query_change_analysis

        result = query_change_analysis(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["change_count"] == 1
        assert result["changes"][0]["resource_id"] == "/sub/vm-1"
        mock_client_cls.return_value.changes.list_changes_by_subscription.assert_called_once()

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AzureChangeAnalysisManagementClient")
    def test_returns_success_resource_group_level(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_change = MagicMock(
            resource_id="/sub/vm-1",
            change_type="Update",
            time_stamp=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
            initiated_by_list=[],
            property_changes=[],
        )
        mock_client_cls.return_value.changes.list_changes_by_resource_group.return_value = [
            mock_change
        ]

        from agents.sre.tools import query_change_analysis

        result = query_change_analysis(
            subscription_id="sub-test-1",
            resource_group="rg-test",
        )

        assert result["query_status"] == "success"
        assert result["change_count"] == 1
        mock_client_cls.return_value.changes.list_changes_by_resource_group.assert_called_once()

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AzureChangeAnalysisManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.changes.list_changes_by_subscription.side_effect = Exception(
            "Change Analysis unavailable"
        )

        from agents.sre.tools import query_change_analysis

        result = query_change_analysis(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Change Analysis unavailable" in result["error"]

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.get_credential", return_value=MagicMock())
    @patch("agents.sre.tools.AzureChangeAnalysisManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.sre.tools import query_change_analysis

        result = query_change_analysis(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# correlate_cross_domain
# ---------------------------------------------------------------------------


class TestCorrelateCrossDomain:
    """Verify correlate_cross_domain returns expected structure."""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.query_advisor_recommendations")
    @patch("agents.sre.tools.query_availability_metrics")
    @patch("agents.sre.tools.query_change_analysis")
    @patch("agents.sre.tools.query_service_health")
    def test_returns_success_with_all_sub_results(
        self, mock_health, mock_changes, mock_avail, mock_advisor,
        mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_health.return_value = {
            "query_status": "success",
            "events": [{"status": "Active", "event_type": "ServiceIssue", "summary": "Issue"}],
        }
        mock_changes.return_value = {
            "query_status": "success",
            "changes": [{"time_stamp": "2026-01-01T14:00:00", "resource_id": "/sub/vm-1"}],
        }
        mock_avail.return_value = {
            "query_status": "success",
            "availability_percent": 99.5,
            "downtime_windows": [],
            "data_point_count": 24,
        }
        mock_advisor.return_value = {
            "query_status": "success",
            "recommendations": [
                {"resource_id": "/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                 "category": "HighAvailability"},
            ],
        }

        from agents.sre.tools import correlate_cross_domain

        result = correlate_cross_domain(
            subscription_id="sub-test-1",
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        )

        assert result["query_status"] == "success"
        assert len(result["platform_events"]) == 1
        assert len(result["recent_changes"]) == 1
        assert result["availability_impact"]["availability_percent"] == 99.5
        assert len(result["relevant_recommendations"]) == 1
        assert result["correlation_summary"] != ""

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.query_advisor_recommendations")
    @patch("agents.sre.tools.query_availability_metrics")
    @patch("agents.sre.tools.query_change_analysis")
    @patch("agents.sre.tools.query_service_health")
    def test_partial_failure_still_succeeds(
        self, mock_health, mock_changes, mock_avail, mock_advisor,
        mock_identity, mock_instrument
    ):
        """One sub-call raises; composite tool still returns success with partial data."""
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_health.side_effect = Exception("Health API down")
        mock_changes.return_value = {
            "query_status": "success",
            "changes": [{"time_stamp": "2026-01-01T14:00:00", "resource_id": "/sub/vm-1"}],
        }
        mock_avail.return_value = {
            "query_status": "success",
            "availability_percent": 99.9,
            "downtime_windows": [],
            "data_point_count": 24,
        }
        mock_advisor.return_value = {
            "query_status": "success",
            "recommendations": [],
        }

        from agents.sre.tools import correlate_cross_domain

        result = correlate_cross_domain(
            subscription_id="sub-test-1",
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        )

        assert result["query_status"] == "success"
        assert result["platform_events"] == []  # Health failed
        assert len(result["recent_changes"]) == 1  # Changes worked
        assert "partial failures" in result["correlation_summary"]
        assert "service_health" in result["correlation_summary"]

    @patch("agents.sre.tools.instrument_tool_call")
    @patch("agents.sre.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.sre.tools.query_advisor_recommendations")
    @patch("agents.sre.tools.query_availability_metrics")
    @patch("agents.sre.tools.query_change_analysis")
    @patch("agents.sre.tools.query_service_health")
    def test_all_sub_calls_fail_still_succeeds(
        self, mock_health, mock_changes, mock_avail, mock_advisor,
        mock_identity, mock_instrument
    ):
        """All 4 sub-calls fail; composite tool still returns success with empty data."""
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_health.side_effect = Exception("Health API down")
        mock_changes.side_effect = Exception("Changes API down")
        mock_avail.side_effect = Exception("Metrics API down")
        mock_advisor.side_effect = Exception("Advisor API down")

        from agents.sre.tools import correlate_cross_domain

        result = correlate_cross_domain(
            subscription_id="sub-test-1",
            resource_id="/subscriptions/sub-test-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        )

        assert result["query_status"] == "success"
        assert result["platform_events"] == []
        assert result["recent_changes"] == []
        assert result["availability_impact"] == {}
        assert result["relevant_recommendations"] == []
        assert "partial failures" in result["correlation_summary"]


# ---------------------------------------------------------------------------
# _percentile helper
# ---------------------------------------------------------------------------


class TestPercentile:
    """Verify the _percentile helper function."""

    def test_empty_list_returns_none(self):
        from agents.sre.tools import _percentile

        assert _percentile([], 0.95) is None

    def test_single_element(self):
        from agents.sre.tools import _percentile

        assert _percentile([42.0], 0.95) == 42.0

    def test_p95_of_ten_elements(self):
        from agents.sre.tools import _percentile

        data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        # idx = int(0.95 * 9) = 8 → value 90.0
        assert _percentile(data, 0.95) == 90.0

    def test_p99_of_ten_elements(self):
        from agents.sre.tools import _percentile

        data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        # idx = int(0.99 * 9) = 8 → value 90.0
        assert _percentile(data, 0.99) == 90.0
