"""Tests for Phase 39 VM cost intelligence tool functions.

Covers: query_advisor_rightsizing_recommendations, query_vm_cost_7day,
        propose_vm_sku_downsize.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    """Return a context-manager-compatible MagicMock."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ---------------------------------------------------------------------------
# TestQueryAdvisorRightsizingRecommendations
# ---------------------------------------------------------------------------


class TestQueryAdvisorRightsizingRecommendations:
    _VM_NAME = "vm-prod-01"
    _SUB_ID = "sub-test-1"
    _RG = "rg-prod"

    def _make_rec(self, category="Cost", impacted_field="Microsoft.Compute/virtualMachines",
                  impacted_value="vm-prod-01", resource_id=None, ext=None):
        """Build a mock Advisor recommendation."""
        rec = MagicMock()
        rec.category = category
        rec.impacted_field = impacted_field
        rec.impacted_value = impacted_value
        rec.impact = "High"
        rec.short_description = MagicMock()
        rec.short_description.solution = "Downsize to Standard_B2s"
        rec.last_updated = None
        rec.id = "rec-id-1"
        rec.resource_metadata = MagicMock()
        rec.resource_metadata.resource_id = resource_id or (
            f"/subscriptions/{self._SUB_ID}/resourceGroups/{self._RG}"
            f"/providers/Microsoft.Compute/virtualMachines/{self._VM_NAME}"
        )
        rec.extended_properties = ext or {
            "recommendedSkuName": "Standard_B2s",
            "savingsAmount": "45.50",
            "annualSavingsAmount": "546.00",
            "savingsCurrency": "USD",
        }
        return rec

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_success_with_cost_recommendations(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """Returns recommendation list when Advisor has Cost recs for the VM."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        mock_client.recommendations.list.return_value = [self._make_rec()]

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["recommendation_count"] == 1
        assert result["recommendations"][0]["target_sku"] == "Standard_B2s"
        assert result["recommendations"][0]["estimated_monthly_savings"] == 45.50
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_success_no_recommendations(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """Returns empty list when no Cost recommendations exist for the VM."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        mock_client.recommendations.list.return_value = []

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["recommendation_count"] == 0
        assert result["recommendations"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_filters_non_cost_and_non_vm_recommendations(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """Filters out non-Cost and non-VM recommendations."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        # One HA rec (wrong category), one storage rec (wrong type), one valid cost/VM rec
        mock_client.recommendations.list.return_value = [
            self._make_rec(category="HighAvailability"),
            self._make_rec(impacted_field="Microsoft.Storage/storageAccounts"),
            self._make_rec(),  # valid
        ]

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert result["recommendation_count"] == 1
        assert result["recommendations"][0]["target_sku"] == "Standard_B2s"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.AdvisorManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_raises_exception_returns_error_dict(
        self, mock_cred, mock_advisor_cls, mock_identity, mock_instr,
    ):
        """SDK error returns error dict without re-raising."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_advisor_cls.return_value = mock_client
        mock_client.recommendations.list.side_effect = Exception("Advisor API error")

        from agents.compute.tools import query_advisor_rightsizing_recommendations

        result = query_advisor_rightsizing_recommendations(
            vm_name=self._VM_NAME,
            subscription_id=self._SUB_ID,
            resource_group=self._RG,
            thread_id="thread-1",
        )

        assert "error" in result
        assert "Advisor API error" in result["error"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_unavailable_returns_error_dict(
        self, mock_cred, mock_identity, mock_instr,
    ):
        """When AdvisorManagementClient is None (not installed), returns error dict."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute import tools as tools_mod
        original = tools_mod.AdvisorManagementClient
        tools_mod.AdvisorManagementClient = None

        try:
            from agents.compute.tools import query_advisor_rightsizing_recommendations

            result = query_advisor_rightsizing_recommendations(
                vm_name=self._VM_NAME,
                subscription_id=self._SUB_ID,
                resource_group=self._RG,
                thread_id="thread-1",
            )

            assert "error" in result
            assert "not installed" in result["error"]
        finally:
            tools_mod.AdvisorManagementClient = original


# ---------------------------------------------------------------------------
# TestQueryVmCost7day
# ---------------------------------------------------------------------------


class TestQueryVmCost7day:
    _RESOURCE_ID = (
        "/subscriptions/sub-1/resourceGroups/rg1"
        "/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
    )
    _SUB_ID = "sub-1"

    def _make_cost_result(self, rows=None):
        """Build a mock Cost Management query result."""
        result = MagicMock()
        result.columns = [
            MagicMock(name="Cost"),
            MagicMock(name="UsageDate"),
            MagicMock(name="Currency"),
        ]
        # Use sentinel to distinguish "no argument" from "explicit empty list"
        if rows is None:
            result.rows = [
                [12.50, "20260404", "USD"],
                [11.80, "20260405", "USD"],
                [13.20, "20260406", "USD"],
            ]
        else:
            result.rows = rows
        return result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.TimeframeType")
    @patch("agents.compute.tools.GranularityType")
    @patch("agents.compute.tools.QueryTimePeriod")
    @patch("agents.compute.tools.QueryDataset")
    @patch("agents.compute.tools.QueryAggregation")
    @patch("agents.compute.tools.QueryGrouping")
    @patch("agents.compute.tools.get_credential")
    def test_success_returns_daily_costs(
        self, mock_cred, mock_qg, mock_qa, mock_qds, mock_qtp, mock_gt, mock_tf, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """Returns daily cost breakdown and total."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        mock_client.query.usage.return_value = self._make_cost_result()

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["total_cost_7d"] == pytest.approx(37.50)
        assert len(result["daily_costs"]) == 3
        assert result["currency"] == "USD"
        assert "data_lag_note" in result
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.TimeframeType")
    @patch("agents.compute.tools.GranularityType")
    @patch("agents.compute.tools.QueryTimePeriod")
    @patch("agents.compute.tools.QueryDataset")
    @patch("agents.compute.tools.QueryAggregation")
    @patch("agents.compute.tools.QueryGrouping")
    @patch("agents.compute.tools.get_credential")
    def test_success_no_rows_returns_zero_cost(
        self, mock_cred, mock_qg, mock_qa, mock_qds, mock_qtp, mock_gt, mock_tf, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """Returns zero cost and empty daily_costs when no rows returned."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        mock_client.query.usage.return_value = self._make_cost_result(rows=[])

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["total_cost_7d"] == 0.0
        assert result["daily_costs"] == []

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.TimeframeType")
    @patch("agents.compute.tools.GranularityType")
    @patch("agents.compute.tools.QueryTimePeriod")
    @patch("agents.compute.tools.QueryDataset")
    @patch("agents.compute.tools.QueryAggregation")
    @patch("agents.compute.tools.QueryGrouping")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_raises_exception_returns_error_dict(
        self, mock_cred, mock_qg, mock_qa, mock_qds, mock_qtp, mock_gt, mock_tf, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """SDK error returns error dict without re-raising."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        mock_client.query.usage.side_effect = Exception("Cost Management 403 Forbidden")

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        assert "error" in result
        assert "403 Forbidden" in result["error"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.get_credential")
    def test_sdk_unavailable_returns_error_dict(
        self, mock_cred, mock_identity, mock_instr,
    ):
        """When CostManagementClient is None, returns error dict."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute import tools as tools_mod
        original = tools_mod.CostManagementClient
        tools_mod.CostManagementClient = None

        try:
            from agents.compute.tools import query_vm_cost_7day

            result = query_vm_cost_7day(
                resource_id=self._RESOURCE_ID,
                subscription_id=self._SUB_ID,
                thread_id="thread-1",
            )

            assert "error" in result
            assert "not installed" in result["error"]
        finally:
            tools_mod.CostManagementClient = original

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.CostManagementClient")
    @patch("agents.compute.tools.QueryDefinition")
    @patch("agents.compute.tools.TimeframeType")
    @patch("agents.compute.tools.GranularityType")
    @patch("agents.compute.tools.QueryTimePeriod")
    @patch("agents.compute.tools.QueryDataset")
    @patch("agents.compute.tools.QueryAggregation")
    @patch("agents.compute.tools.QueryGrouping")
    @patch("agents.compute.tools.get_credential")
    def test_daily_costs_sorted_ascending_by_date(
        self, mock_cred, mock_qg, mock_qa, mock_qds, mock_qtp, mock_gt, mock_tf, mock_qd, mock_cost_cls, mock_identity, mock_instr,
    ):
        """Daily costs are sorted ascending by date regardless of API response order."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_cost_cls.return_value = mock_client
        # Deliberately out of order
        mock_client.query.usage.return_value = self._make_cost_result(rows=[
            [5.0, "20260407", "USD"],
            [3.0, "20260405", "USD"],
            [4.0, "20260406", "USD"],
        ])

        from agents.compute.tools import query_vm_cost_7day

        result = query_vm_cost_7day(
            resource_id=self._RESOURCE_ID,
            subscription_id=self._SUB_ID,
            thread_id="thread-1",
        )

        dates = [d["date"] for d in result["daily_costs"]]
        assert dates == sorted(dates), "daily_costs should be sorted ascending by date"


# ---------------------------------------------------------------------------
# TestProposeVmSkuDownsize
# ---------------------------------------------------------------------------


class TestProposeVmSkuDownsize:
    _RESOURCE_ID = (
        "/subscriptions/sub-1/resourceGroups/rg1"
        "/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
    )

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record", new_callable=MagicMock)
    def test_success_returns_pending_approval(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """Returns pending_approval status with approval_id."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-uuid-123"}

        from agents.compute.tools import propose_vm_sku_downsize

        result = propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="CPU <5% for 7 days; Advisor recommends Standard_B2s",
            thread_id="thread-1",
        )

        assert result["status"] == "pending_approval"
        assert result["approval_id"] == "approval-uuid-123"
        assert "vm-prod-01" in result["message"]
        assert "Standard_B2s" in result["message"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record", new_callable=MagicMock)
    def test_approval_record_uses_medium_risk(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """Approval record uses risk_level='medium' (not 'high')."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-456"}

        from agents.compute.tools import propose_vm_sku_downsize

        propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="test",
            thread_id="thread-1",
        )

        call_kwargs = mock_approval.call_args[1]
        assert call_kwargs["risk_level"] == "medium"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record", new_callable=MagicMock)
    def test_approval_record_uses_empty_incident_id(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """Approval record uses incident_id='' (cost proposal has no incident context)."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-789"}

        from agents.compute.tools import propose_vm_sku_downsize

        propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="test",
            thread_id="thread-1",
        )

        call_kwargs = mock_approval.call_args[1]
        assert call_kwargs["incident_id"] == ""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record", new_callable=MagicMock)
    def test_approval_record_raises_returns_error_dict(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """If create_approval_record raises, returns error dict without re-raising."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.side_effect = Exception("Cosmos DB unavailable")

        from agents.compute.tools import propose_vm_sku_downsize

        result = propose_vm_sku_downsize(
            resource_id=self._RESOURCE_ID,
            resource_group="rg1",
            vm_name="vm-prod-01",
            subscription_id="sub-1",
            target_sku="Standard_B2s",
            justification="test",
            thread_id="thread-1",
        )

        assert result["status"] == "error"
        assert "Cosmos DB unavailable" in result["message"]
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.create_approval_record", new_callable=MagicMock)
    def test_proposal_never_makes_arm_calls(
        self, mock_approval, mock_identity, mock_instr,
    ):
        """No Azure SDK clients are instantiated — only create_approval_record is called."""
        mock_instr.return_value = _instrument_mock()
        mock_approval.return_value = {"id": "approval-abc"}

        from agents.compute.tools import propose_vm_sku_downsize

        # With no ComputeManagementClient or AdvisorManagementClient mock patches,
        # the test passes only if the tool never calls them.
        with patch("agents.compute.tools.ComputeManagementClient") as mock_compute:
            with patch("agents.compute.tools.AdvisorManagementClient") as mock_advisor:
                propose_vm_sku_downsize(
                    resource_id=self._RESOURCE_ID,
                    resource_group="rg1",
                    vm_name="vm-prod-01",
                    subscription_id="sub-1",
                    target_sku="Standard_B2s",
                    justification="test",
                    thread_id="thread-1",
                )
                mock_compute.assert_not_called()
                mock_advisor.assert_not_called()
