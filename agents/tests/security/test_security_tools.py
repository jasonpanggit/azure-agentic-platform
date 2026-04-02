"""Unit tests for Security Agent tools — ~28 tests across 8 test classes."""
from __future__ import annotations

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


def _make_alert(name="alert-1", severity="High", status="Active"):
    a = MagicMock()
    a.id = f"/subscriptions/sub-1/providers/Microsoft.Security/locations/eastus/alerts/{name}"
    a.name = name
    a.properties = MagicMock()
    a.properties.severity = severity
    a.properties.status = status
    a.properties.start_time_utc = None
    a.properties.description = f"Test alert {name}"
    a.properties.resource_identifiers = []
    return a


def _make_activity_event(op_name="Microsoft.Authorization/roleAssignments/write"):
    event = MagicMock()
    event.operation_name = MagicMock()
    event.operation_name.value = op_name
    event.event_timestamp = None
    event.caller = "user@contoso.com"
    event.status = MagicMock()
    event.status.value = "Succeeded"
    event.resource_id = "/subscriptions/sub-1/resourceGroups/rg"
    return event


def _make_assignment(principal_id="sp-1", role_def_id="role-1", scope="/subscriptions/sub-1"):
    a = MagicMock()
    a.id = f"/subscriptions/sub-1/roleAssignments/{principal_id}"
    a.principal_id = principal_id
    a.principal_type = "ServicePrincipal"
    a.role_definition_id = role_def_id
    a.scope = scope
    return a


def _make_policy_state(resource_id="/subscriptions/sub-1/rg/vm-1"):
    s = MagicMock()
    s.resource_id = resource_id
    s.policy_assignment_name = "deny-public-ips"
    s.policy_definition_id = "/providers/Microsoft.Authorization/policyDefinitions/abc"
    s.compliance_state = "NonCompliant"
    s.timestamp = None
    return s


def _make_public_ip(name="pip-1", ip_address="20.1.2.3", has_association=True):
    ip = MagicMock()
    ip.id = (
        "/subscriptions/sub-1/resourceGroups/rg-test/providers/"
        f"Microsoft.Network/publicIPAddresses/{name}"
    )
    ip.name = name
    ip.ip_address = ip_address
    ip.public_ip_allocation_method = "Static"
    ip.sku = MagicMock()
    ip.sku.name = "Standard"
    if has_association:
        ip.ip_configuration = MagicMock()
        ip.ip_configuration.id = (
            "/subscriptions/sub-1/resourceGroups/rg-test/providers/"
            "Microsoft.Network/networkInterfaces/nic-1/ipConfigurations/ipconfig1"
        )
    else:
        ip.ip_configuration = None
    return ip


def _make_logs_query_response(rows=None):
    response = MagicMock()
    # Use a sentinel value that compares equal to LogsQueryStatus.SUCCESS;
    # azure.monitor.query may not be installed in all test environments.
    status_success = MagicMock()
    response.status = status_success
    table = MagicMock()
    col_tg = MagicMock()
    col_tg.name = "TimeGenerated"
    col_on = MagicMock()
    col_on.name = "OperationName"
    col_ip = MagicMock()
    col_ip.name = "CallerIPAddress"
    col_rt = MagicMock()
    col_rt.name = "ResultType"
    col_oid = MagicMock()
    col_oid.name = "identity_claim_oid_g"
    table.columns = [col_tg, col_on, col_ip, col_rt, col_oid]
    table.rows = rows or []
    response.tables = [table]
    return response


# ---------------------------------------------------------------------------
# TestAllowedMcpTools
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_tools_is_list(self):
        from agents.security.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)

    def test_no_wildcard_in_allowed_tools(self):
        from agents.security.tools import ALLOWED_MCP_TOOLS

        for entry in ALLOWED_MCP_TOOLS:
            assert "*" not in entry, f"Wildcard found in tool: {entry}"

    def test_allowed_tools_contains_keyvault_entry(self):
        from agents.security.tools import ALLOWED_MCP_TOOLS

        assert any("keyvault" in t for t in ALLOWED_MCP_TOOLS)


# ---------------------------------------------------------------------------
# TestQueryDefenderAlerts
# ---------------------------------------------------------------------------


class TestQueryDefenderAlerts:
    """Verify query_defender_alerts — SDK calls, severity filter, and error handling."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.SecurityCenter")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_success_returns_alerts_list(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        alert = _make_alert(name="alert-1", severity="High")
        mock_client_cls.return_value.alerts.list.return_value = [alert]

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["alert_count"] == 1
        assert result["alerts"][0]["name"] == "alert-1"
        assert result["alerts"][0]["severity"] == "High"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.SecurityCenter")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_severity_filter_applied_when_provided(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        high_alert = _make_alert(name="high-1", severity="High")
        low_alert = _make_alert(name="low-1", severity="Low")
        mock_client_cls.return_value.alerts.list.return_value = [high_alert, low_alert]

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-1", severity="High")

        assert result["query_status"] == "success"
        assert result["alert_count"] == 1
        assert result["alerts"][0]["severity"] == "High"
        assert result["severity_filter"] == "High"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.SecurityCenter")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_no_severity_filter_returns_all(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        alerts = [_make_alert(name=f"alert-{i}", severity=s) for i, s in
                  enumerate(["High", "Medium", "Low"])]
        mock_client_cls.return_value.alerts.list.return_value = alerts

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["alert_count"] == 3
        assert result["severity_filter"] is None

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.SecurityCenter")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.alerts.list.side_effect = Exception(
            "AuthorizationFailed"
        )

        from agents.security.tools import query_defender_alerts

        result = query_defender_alerts(subscription_id="sub-1")

        assert result["query_status"] == "error"
        assert "AuthorizationFailed" in result["error"]


# ---------------------------------------------------------------------------
# TestQueryIamChanges
# ---------------------------------------------------------------------------


class TestQueryIamChanges:
    """Verify query_iam_changes — RBAC/KV separation and error handling."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.MonitorManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_success_separates_rbac_and_keyvault_changes(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        rbac_event = _make_activity_event(
            "Microsoft.Authorization/roleAssignments/write"
        )
        kv_event = _make_activity_event(
            "Microsoft.KeyVault/vaults/accessPolicies/write"
        )
        mock_client_cls.return_value.activity_logs.list.return_value = [
            rbac_event,
            kv_event,
        ]

        from agents.security.tools import query_iam_changes

        result = query_iam_changes(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert len(result["rbac_changes"]) == 1
        assert len(result["keyvault_policy_changes"]) == 1
        assert result["rbac_changes"][0]["operationName"].startswith(
            "Microsoft.Authorization/roleAssignments"
        )

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.MonitorManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_timespan_hours_passed_to_filter(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.activity_logs.list.return_value = []

        from agents.security.tools import query_iam_changes

        result = query_iam_changes(subscription_id="sub-1", timespan_hours=6)

        assert result["timespan_hours"] == 6
        call_kwargs = mock_client_cls.return_value.activity_logs.list.call_args[1]
        assert "filter" in call_kwargs

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.MonitorManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.activity_logs.list.side_effect = Exception(
            "ServiceUnavailable"
        )

        from agents.security.tools import query_iam_changes

        result = query_iam_changes(subscription_id="sub-1")

        assert result["query_status"] == "error"
        assert "ServiceUnavailable" in result["error"]


# ---------------------------------------------------------------------------
# TestQueryKeyvaultDiagnostics
# ---------------------------------------------------------------------------


class TestQueryKeyvaultDiagnostics:
    """Verify query_keyvault_diagnostics — workspace_id guard, KV log queries."""

    def test_empty_workspace_id_returns_skipped(self):
        with patch("agents.security.tools.instrument_tool_call") as mock_inst, \
             patch("agents.security.tools.get_agent_identity", return_value="test-id"):
            mock_inst.return_value = _make_instrument_mock()

            from agents.security.tools import query_keyvault_diagnostics

            result = query_keyvault_diagnostics(vault_name="kv-test", workspace_id="")

            assert result["query_status"] == "skipped"
            assert result["operations"] == []
            assert result["anomaly_indicators"] == []

    def test_none_workspace_id_returns_skipped(self):
        with patch("agents.security.tools.instrument_tool_call") as mock_inst, \
             patch("agents.security.tools.get_agent_identity", return_value="test-id"):
            mock_inst.return_value = _make_instrument_mock()

            from agents.security.tools import query_keyvault_diagnostics

            result = query_keyvault_diagnostics(vault_name="kv-test", workspace_id=None)

            assert result["query_status"] == "skipped"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.LogsQueryClient")
    @patch("agents.security.tools.LogsQueryStatus")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_success_returns_operations_list(
        self, mock_cred, mock_status_cls, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        row = ["2026-04-01T10:00:00Z", "SecretGet", "10.0.0.1", "Success", "oid-1"]
        response = _make_logs_query_response(rows=[row])
        # response.status must equal LogsQueryStatus.SUCCESS — align sentinel with mock
        response.status = mock_status_cls.SUCCESS
        mock_client_cls.return_value.query_workspace.return_value = response

        from agents.security.tools import query_keyvault_diagnostics

        result = query_keyvault_diagnostics(
            vault_name="kv-test",
            workspace_id="/subscriptions/sub-1/resourceGroups/rg/workspaces/ws-1",
        )

        assert result["query_status"] == "success"
        assert len(result["operations"]) == 1
        assert result["operations"][0]["operation_name"] == "SecretGet"
        assert result["operations"][0]["caller_ip"] == "10.0.0.1"
        assert result["operations"][0]["result_type"] == "Success"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.LogsQueryClient")
    @patch("agents.security.tools.LogsQueryStatus")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_unauthorized_operations_in_anomaly_indicators(
        self, mock_cred, mock_status_cls, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        rows = [
            ["2026-04-01T10:00:00Z", "SecretGet", "10.0.0.1", "Unauthorized", "oid-1"],
            ["2026-04-01T10:01:00Z", "KeyGet", "10.0.0.2", "Success", "oid-2"],
        ]
        response = _make_logs_query_response(rows=rows)
        # response.status must equal LogsQueryStatus.SUCCESS — align sentinel with mock
        response.status = mock_status_cls.SUCCESS
        mock_client_cls.return_value.query_workspace.return_value = response

        from agents.security.tools import query_keyvault_diagnostics

        result = query_keyvault_diagnostics(
            vault_name="kv-test",
            workspace_id="/subscriptions/sub-1/resourceGroups/rg/workspaces/ws-1",
        )

        assert result["query_status"] == "success"
        assert len(result["anomaly_indicators"]) == 1
        assert result["anomaly_indicators"][0]["result_type"] == "Unauthorized"


# ---------------------------------------------------------------------------
# TestQuerySecureScore
# ---------------------------------------------------------------------------


class TestQuerySecureScore:
    """Verify query_secure_score — ascScore lookup, field extraction, error paths."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.SecurityCenter")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_success_returns_score_percentage(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        score_mock = MagicMock()
        score_mock.properties = MagicMock()
        score_mock.properties.score = MagicMock()
        score_mock.properties.score.percentage = 72.5
        score_mock.properties.score.current = 58.0
        score_mock.properties.score.max = 80.0
        score_mock.properties.unhealthy_resource_count = 12
        mock_client_cls.return_value.secure_scores.get.return_value = score_mock

        from agents.security.tools import query_secure_score

        result = query_secure_score(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["score_percentage"] == 72.5
        assert result["current_score"] == 58.0
        assert result["max_score"] == 80.0
        assert result["unhealthy_resource_count"] == 12

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.SecurityCenter")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_asc_score_name_passed_to_sdk(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        score_mock = MagicMock()
        score_mock.properties = MagicMock()
        score_mock.properties.score = MagicMock()
        score_mock.properties.score.percentage = 50.0
        score_mock.properties.score.current = 40.0
        score_mock.properties.score.max = 80.0
        score_mock.properties.unhealthy_resource_count = 5
        mock_client_cls.return_value.secure_scores.get.return_value = score_mock

        from agents.security.tools import query_secure_score

        query_secure_score(subscription_id="sub-1")

        mock_client_cls.return_value.secure_scores.get.assert_called_once_with(
            "sub-1", "ascScore"
        )

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.SecurityCenter")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.secure_scores.get.side_effect = Exception(
            "SecureScoreNotFound"
        )

        from agents.security.tools import query_secure_score

        result = query_secure_score(subscription_id="sub-1")

        assert result["query_status"] == "error"
        assert "SecureScoreNotFound" in result["error"]

    def test_sdk_not_installed_returns_error(self):
        import agents.security.tools as tools_mod

        original = tools_mod.SecurityCenter
        tools_mod.SecurityCenter = None
        try:
            with patch("agents.security.tools.instrument_tool_call") as mock_inst, \
                 patch("agents.security.tools.get_agent_identity", return_value="test-id"):
                mock_inst.return_value = _make_instrument_mock()
                from agents.security.tools import query_secure_score

                result = query_secure_score(subscription_id="sub-1")
                assert result["query_status"] == "error"
                assert "not installed" in result["error"]
        finally:
            tools_mod.SecurityCenter = original


# ---------------------------------------------------------------------------
# TestQueryRbacAssignments
# ---------------------------------------------------------------------------


class TestQueryRbacAssignments:
    """Verify query_rbac_assignments — listing, max_results cap, scope filtering."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.AuthorizationManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_success_returns_assignments_list(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        assignment = _make_assignment(principal_id="sp-1")
        mock_client_cls.return_value.role_assignments.list_for_subscription.return_value = [
            assignment
        ]

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["total_count"] == 1
        assert result["assignments"][0]["principal_id"] == "sp-1"
        assert result["truncated"] is False

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.AuthorizationManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_max_results_cap_applied(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_assignments = [_make_assignment(principal_id=f"sp-{i}") for i in range(150)]
        mock_client_cls.return_value.role_assignments.list_for_subscription.return_value = iter(
            mock_assignments
        )

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(subscription_id="sub-1", max_results=100)

        assert result["total_count"] == 100

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.AuthorizationManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_truncated_true_when_cap_hit(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_assignments = [_make_assignment(principal_id=f"sp-{i}") for i in range(150)]
        mock_client_cls.return_value.role_assignments.list_for_subscription.return_value = iter(
            mock_assignments
        )

        from agents.security.tools import query_rbac_assignments

        result = query_rbac_assignments(subscription_id="sub-1", max_results=100)

        assert result["truncated"] is True

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.AuthorizationManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_scope_passed_to_sdk_when_provided(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.role_assignments.list_for_scope.return_value = []

        from agents.security.tools import query_rbac_assignments

        scope = "/subscriptions/sub-1/resourceGroups/rg-prod"
        result = query_rbac_assignments(subscription_id="sub-1", scope=scope)

        assert result["query_status"] == "success"
        mock_client_cls.return_value.role_assignments.list_for_scope.assert_called_once_with(
            scope
        )
        mock_client_cls.return_value.role_assignments.list_for_subscription.assert_not_called()


# ---------------------------------------------------------------------------
# TestQueryPolicyCompliance
# ---------------------------------------------------------------------------


class TestQueryPolicyCompliance:
    """Verify query_policy_compliance — non-compliant filter, policy_definition_id."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.PolicyInsightsClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_success_returns_non_compliant_states(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        state = _make_policy_state()
        mock_client_cls.return_value.policy_states.list_query_results_for_subscription.return_value = [
            state
        ]

        from agents.security.tools import query_policy_compliance

        result = query_policy_compliance(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["non_compliant_count"] == 1
        assert result["policy_states"][0]["compliance_state"] == "NonCompliant"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.PolicyInsightsClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_policy_definition_id_filter_applied(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.policy_states.list_query_results_for_subscription.return_value = []

        from agents.security.tools import query_policy_compliance

        policy_def_id = "/providers/Microsoft.Authorization/policyDefinitions/test-policy"
        result = query_policy_compliance(
            subscription_id="sub-1",
            policy_definition_id=policy_def_id,
        )

        assert result["query_status"] == "success"
        assert result["policy_definition_id"] == policy_def_id
        # Verify the call was made (filter is inside QueryOptions so we check it was called)
        mock_client_cls.return_value.policy_states.list_query_results_for_subscription.assert_called_once()

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.PolicyInsightsClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.policy_states.list_query_results_for_subscription.side_effect = Exception(
            "PolicyClientError"
        )

        from agents.security.tools import query_policy_compliance

        result = query_policy_compliance(subscription_id="sub-1")

        assert result["query_status"] == "error"
        assert "PolicyClientError" in result["error"]


# ---------------------------------------------------------------------------
# TestScanPublicEndpoints
# ---------------------------------------------------------------------------


class TestScanPublicEndpoints:
    """Verify scan_public_endpoints — IP enumeration, resource group extraction, errors."""

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.NetworkManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_success_returns_public_ips(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        ip = _make_public_ip(name="pip-1", ip_address="20.1.2.3")
        mock_client_cls.return_value.public_ip_addresses.list_all.return_value = [ip]

        from agents.security.tools import scan_public_endpoints

        result = scan_public_endpoints(subscription_id="sub-1")

        assert result["query_status"] == "success"
        assert result["total_count"] == 1
        assert result["public_ips"][0]["name"] == "pip-1"
        assert result["public_ips"][0]["ip_address"] == "20.1.2.3"
        assert result["public_ips"][0]["sku"] == "Standard"

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.NetworkManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_resource_group_extracted_from_id(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        ip = _make_public_ip(name="pip-2")
        mock_client_cls.return_value.public_ip_addresses.list_all.return_value = [ip]

        from agents.security.tools import scan_public_endpoints

        result = scan_public_endpoints(subscription_id="sub-1")

        assert result["query_status"] == "success"
        # The resource group is extracted from the ID (case-insensitive)
        assert result["public_ips"][0]["resource_group"] is not None
        assert "rg-test" in result["public_ips"][0]["resource_group"].lower()

    @patch("agents.security.tools.instrument_tool_call")
    @patch("agents.security.tools.get_agent_identity", return_value="test-id")
    @patch("agents.security.tools.NetworkManagementClient")
    @patch("agents.security.tools.get_credential", return_value=MagicMock())
    def test_error_returns_error_status(
        self, mock_cred, mock_client_cls, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_client_cls.return_value.public_ip_addresses.list_all.side_effect = Exception(
            "NetworkError"
        )

        from agents.security.tools import scan_public_endpoints

        result = scan_public_endpoints(subscription_id="sub-1")

        assert result["query_status"] == "error"
        assert "NetworkError" in result["error"]
