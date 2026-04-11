"""Unit tests for Security Agent tools (Phase 20 — Plan 20-04).

Tests all 7 security tools + ALLOWED_MCP_TOOLS.
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

    def test_allowed_mcp_tools_has_exactly_seven_entries(self):
        from agents.security.tools import ALLOWED_MCP_TOOLS

        assert len(ALLOWED_MCP_TOOLS) == 7

    def test_allowed_mcp_tools_contains_expected_entries(self):
        from agents.security.tools import ALLOWED_MCP_TOOLS

        expected = [
            "keyvault.list_vaults",
            "keyvault.get_vault",
            "role.list_assignments",
            "monitor.query_logs",
            "monitor.query_metrics",
            "resourcehealth.get_availability_status",
            "advisor.list_recommendations",
        ]
        for tool in expected:
            assert tool in ALLOWED_MCP_TOOLS, f"Missing: {tool}"

    def test_allowed_mcp_tools_no_wildcards(self):
        from agents.security.tools import ALLOWED_MCP_TOOLS

        for tool in ALLOWED_MCP_TOOLS:
            assert "*" not in tool, f"Wildcard found in tool: {tool}"


# ---------------------------------------------------------------------------
# query_defender_alerts
# ---------------------------------------------------------------------------


class TestQueryDefenderAlerts:
    """Verify query_defender_alerts returns expected structure."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.SecurityCenter")
    def test_returns_success_with_alerts(
        self, mock_sc_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_alert = MagicMock(
            alert_display_name="SQL Injection Attempt",
            severity="High",
            status="Active",
            description="Potential SQL injection",
            compromised_entity="sql-server-1",
            time_generated_utc=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            alert_type="SqlInjection",
            product_name="Azure Defender for SQL",
        )
        mock_sc_cls.return_value.alerts.list.return_value = [mock_alert]

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["alert_count"] == 1
        assert result["alerts"][0]["alert_display_name"] == "SQL Injection Attempt"
        assert result["alerts"][0]["severity"] == "High"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.SecurityCenter")
    def test_severity_filter_applied(
        self, mock_sc_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        alert_high = MagicMock(
            alert_display_name="High Alert",
            severity="High",
            status="Active",
            description="High severity",
            compromised_entity="vm-1",
            time_generated_utc=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            alert_type="HighAlert",
            product_name="Defender",
        )
        alert_low = MagicMock(
            alert_display_name="Low Alert",
            severity="Low",
            status="Active",
            description="Low severity",
            compromised_entity="vm-2",
            time_generated_utc=datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
            alert_type="LowAlert",
            product_name="Defender",
        )
        mock_sc_cls.return_value.alerts.list.return_value = [alert_high, alert_low]

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-test-1", severity="High")

        assert result["query_status"] == "success"
        assert result["alert_count"] == 1
        assert result["alerts"][0]["severity"] == "High"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.SecurityCenter")
    def test_returns_error_on_sdk_exception(
        self, mock_sc_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_sc_cls.return_value.alerts.list.side_effect = Exception("Defender unavailable")

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Defender unavailable" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.SecurityCenter", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_keyvault_diagnostics
# ---------------------------------------------------------------------------


class TestQueryKeyvaultDiagnostics:
    """Verify query_keyvault_diagnostics returns expected structure."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.LogsQueryStatus")
    @patch("agents.security.tools.LogsQueryClient")
    def test_returns_success_with_operations(
        self, mock_client_cls, mock_status_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_col1 = MagicMock()
        mock_col1.name = "OperationName"
        mock_col2 = MagicMock()
        mock_col2.name = "CallerIPAddress"
        mock_col3 = MagicMock()
        mock_col3.name = "ResultType"
        mock_table = MagicMock()
        mock_table.columns = [mock_col1, mock_col2, mock_col3]
        mock_table.rows = [["SecretGet", "10.0.0.1", "Success"]]

        mock_response = MagicMock()
        mock_response.status = mock_status_cls.SUCCESS
        mock_response.tables = [mock_table]
        mock_client_cls.return_value.query_workspace.return_value = mock_response

        from agents.security.tools import query_keyvault_diagnostics

        result = query_keyvault_diagnostics(
            vault_name="kv-test",
            workspace_id="ws-test-123",
        )

        assert result["query_status"] == "success"
        assert result["operation_count"] == 1
        assert result["operations"][0]["OperationName"] == "SecretGet"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.LogsQueryClient")
    def test_returns_error_when_no_workspace_id(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import query_keyvault_diagnostics

        # Ensure env var not set
        with patch.dict("os.environ", {}, clear=True):
            result = query_keyvault_diagnostics(
                vault_name="kv-test",
                workspace_id=None,
            )

        assert result["query_status"] == "error"
        assert "workspace_id is required" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.LogsQueryClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.query_workspace.side_effect = Exception("Query failed")

        from agents.security.tools import query_keyvault_diagnostics

        result = query_keyvault_diagnostics(
            vault_name="kv-test",
            workspace_id="ws-test-123",
        )

        assert result["query_status"] == "error"
        assert "Query failed" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.LogsQueryClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import query_keyvault_diagnostics

        result = query_keyvault_diagnostics(
            vault_name="kv-test",
            workspace_id="ws-test-123",
        )

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_iam_changes
# ---------------------------------------------------------------------------


class TestQueryIamChanges:
    """Verify query_iam_changes returns expected structure."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.MonitorManagementClient")
    def test_returns_success_with_categorized_changes(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        rbac_event = MagicMock(
            operation_name=MagicMock(value="Microsoft.Authorization/roleAssignments/write"),
            event_timestamp=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
            caller="admin@contoso.com",
            status=MagicMock(value="Succeeded"),
            resource_id="/sub/role-assignment-1",
            level=MagicMock(value="Informational"),
            description="Created role assignment",
        )
        kv_event = MagicMock(
            operation_name=MagicMock(value="Microsoft.KeyVault/vaults/accessPolicies/write"),
            event_timestamp=datetime(2026, 1, 1, 14, 5, 0, tzinfo=timezone.utc),
            caller="admin@contoso.com",
            status=MagicMock(value="Succeeded"),
            resource_id="/sub/kv-1",
            level=MagicMock(value="Informational"),
            description="Updated access policy",
        )
        mock_client_cls.return_value.activity_logs.list.return_value = [rbac_event, kv_event]

        from agents.security.tools import query_iam_changes

        result = query_iam_changes(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert len(result["rbac_changes"]) == 1
        assert len(result["keyvault_policy_changes"]) == 1
        assert result["total_changes"] == 2

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.MonitorManagementClient")
    def test_returns_empty_when_no_events(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.activity_logs.list.return_value = []

        from agents.security.tools import query_iam_changes

        result = query_iam_changes(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["total_changes"] == 0
        assert result["rbac_changes"] == []
        assert result["keyvault_policy_changes"] == []
        assert result["identity_operations"] == []

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.MonitorManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.activity_logs.list.side_effect = Exception(
            "Activity log unavailable"
        )

        from agents.security.tools import query_iam_changes

        result = query_iam_changes(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Activity log unavailable" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.MonitorManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import query_iam_changes

        result = query_iam_changes(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_secure_score
# ---------------------------------------------------------------------------


class TestQuerySecureScore:
    """Verify query_secure_score returns expected structure."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.SecurityCenter")
    def test_returns_success_with_score(
        self, mock_sc_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_score = MagicMock(
            current_score=72.5,
            max_score=100,
            percentage=0.725,
            weight=50,
        )
        mock_sc_cls.return_value.secure_scores.get.return_value = mock_score

        from agents.security.tools import query_secure_score

        result = query_secure_score(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["current_score"] == 72.5
        assert result["max_score"] == 100
        assert result["percentage"] == 0.725
        assert result["weight"] == 50

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.SecurityCenter")
    def test_returns_error_on_sdk_exception(
        self, mock_sc_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_sc_cls.return_value.secure_scores.get.side_effect = Exception("Score unavailable")

        from agents.security.tools import query_secure_score

        result = query_secure_score(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Score unavailable" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.SecurityCenter", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import query_secure_score

        result = query_secure_score(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_rbac_assignments
# ---------------------------------------------------------------------------


class TestQueryRbacAssignments:
    """Verify query_rbac_assignments returns expected structure."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.AuthorizationManagementClient")
    def test_returns_success_subscription_wide(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_ra = MagicMock(
            id="/sub/role-assignment-1",
            principal_id="pid-1",
            principal_type="ServicePrincipal",
            role_definition_id="/sub/role-def-1",
            scope="/subscriptions/sub-test-1",
            created_on=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_on=None,
        )
        mock_client_cls.return_value.role_assignments.list_for_subscription.return_value = [
            mock_ra
        ]

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["assignment_count"] == 1
        assert result["assignments"][0]["principal_id"] == "pid-1"
        mock_client_cls.return_value.role_assignments.list_for_subscription.assert_called_once()

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.AuthorizationManagementClient")
    def test_returns_success_scoped(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_ra = MagicMock(
            id="/sub/role-assignment-2",
            principal_id="pid-2",
            principal_type="User",
            role_definition_id="/sub/role-def-2",
            scope="/subscriptions/sub-test-1/resourceGroups/rg-1",
            created_on=None,
            updated_on=None,
        )
        mock_client_cls.return_value.role_assignments.list_for_scope.return_value = [
            mock_ra
        ]

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(
            subscription_id="sub-test-1",
            scope="/subscriptions/sub-test-1/resourceGroups/rg-1",
        )

        assert result["query_status"] == "success"
        assert result["assignment_count"] == 1
        mock_client_cls.return_value.role_assignments.list_for_scope.assert_called_once()

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.AuthorizationManagementClient")
    def test_principal_id_filter(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        ra1 = MagicMock(id="/ra-1", principal_id="pid-1", principal_type="User",
                        role_definition_id="/rd-1", scope="/sub", created_on=None, updated_on=None)
        ra2 = MagicMock(id="/ra-2", principal_id="pid-2", principal_type="User",
                        role_definition_id="/rd-2", scope="/sub", created_on=None, updated_on=None)
        ra3 = MagicMock(id="/ra-3", principal_id="pid-1", principal_type="User",
                        role_definition_id="/rd-3", scope="/sub", created_on=None, updated_on=None)
        mock_client_cls.return_value.role_assignments.list_for_subscription.return_value = [
            ra1, ra2, ra3
        ]

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(
            subscription_id="sub-test-1",
            principal_id="pid-1",
        )

        assert result["query_status"] == "success"
        assert result["assignment_count"] == 2

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.AuthorizationManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.role_assignments.list_for_subscription.side_effect = (
            Exception("Auth unavailable")
        )

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Auth unavailable" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.AuthorizationManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# query_policy_compliance
# ---------------------------------------------------------------------------


class TestQueryPolicyCompliance:
    """Verify query_policy_compliance returns expected structure."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.PolicyInsightsClient")
    def test_returns_success_with_states(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_state = MagicMock(
            resource_id="/sub/vm-1",
            policy_assignment_id="/sub/pa-1",
            policy_definition_id="/sub/pd-1",
            compliance_state="NonCompliant",
            resource_type="Microsoft.Compute/virtualMachines",
            resource_group="rg-test",
            is_compliant=False,
            policy_definition_action="audit",
        )
        mock_client_cls.return_value.policy_states.list_query_results_for_subscription.return_value = [
            mock_state
        ]

        from agents.security.tools import query_policy_compliance

        result = query_policy_compliance(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["non_compliant_count"] == 1
        assert result["policy_states"][0]["compliance_state"] == "NonCompliant"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.PolicyInsightsClient")
    def test_max_results_cap(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        # Create 150 NonCompliant states
        states = []
        for i in range(150):
            s = MagicMock(
                resource_id=f"/sub/resource-{i}",
                policy_assignment_id=f"/sub/pa-{i}",
                policy_definition_id=f"/sub/pd-{i}",
                compliance_state="NonCompliant",
                resource_type="Microsoft.Compute/virtualMachines",
                resource_group="rg-test",
                is_compliant=False,
                policy_definition_action="audit",
            )
            states.append(s)
        mock_client_cls.return_value.policy_states.list_query_results_for_subscription.return_value = states

        from agents.security.tools import query_policy_compliance

        result = query_policy_compliance(subscription_id="sub-test-1", max_results=100)

        assert result["query_status"] == "success"
        assert result["non_compliant_count"] == 100  # Capped at max_results

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.PolicyInsightsClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.policy_states.list_query_results_for_subscription.side_effect = (
            Exception("Policy service unavailable")
        )

        from agents.security.tools import query_policy_compliance

        result = query_policy_compliance(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Policy service unavailable" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.PolicyInsightsClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import query_policy_compliance

        result = query_policy_compliance(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]


# ---------------------------------------------------------------------------
# scan_public_endpoints
# ---------------------------------------------------------------------------


class TestScanPublicEndpoints:
    """Verify scan_public_endpoints returns expected structure."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.NetworkManagementClient")
    def test_returns_success_with_public_ips(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        pip1 = _mock_with_name("pip-1")
        pip1.id = "/subscriptions/sub/resourceGroups/rg-1/providers/Microsoft.Network/publicIPAddresses/pip-1"
        pip1.ip_address = "20.1.2.3"
        pip1.public_ip_allocation_method = "Static"
        pip1.ip_configuration = MagicMock(id="/sub/nic-1")
        pip1.dns_settings = None
        pip1.sku = MagicMock()
        pip1.sku.name = "Standard"

        pip2 = _mock_with_name("pip-2")
        pip2.id = "/subscriptions/sub/resourceGroups/rg-1/providers/Microsoft.Network/publicIPAddresses/pip-2"
        pip2.ip_address = "20.4.5.6"
        pip2.public_ip_allocation_method = "Dynamic"
        pip2.ip_configuration = None
        pip2.dns_settings = None
        pip2.sku = MagicMock()
        pip2.sku.name = "Basic"

        mock_client_cls.return_value.public_ip_addresses.list_all.return_value = [pip1, pip2]

        from agents.security.tools import scan_public_endpoints

        result = scan_public_endpoints(subscription_id="sub-test-1")

        assert result["query_status"] == "success"
        assert result["public_ip_count"] == 2
        assert result["associated_count"] == 1
        assert result["unassociated_count"] == 1
        assert result["public_ips"][0]["name"] == "pip-1"
        assert result["public_ips"][0]["associated"] is True
        assert result["public_ips"][1]["associated"] is False

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.NetworkManagementClient")
    def test_returns_error_on_sdk_exception(
        self, mock_client_cls, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        mock_client_cls.return_value.public_ip_addresses.list_all.side_effect = Exception(
            "Network unavailable"
        )

        from agents.security.tools import scan_public_endpoints

        result = scan_public_endpoints(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "Network unavailable" in result["error"]

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    @patch("agents.security.tools.NetworkManagementClient", None)
    def test_returns_error_when_sdk_missing(
        self, mock_cred, mock_identity, mock_instrument
    ):
        mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

        from agents.security.tools import scan_public_endpoints

        result = scan_public_endpoints(subscription_id="sub-test-1")

        assert result["query_status"] == "error"
        assert "not installed" in result["error"]
