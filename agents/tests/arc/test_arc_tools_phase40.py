"""Tests for Phase 40 Arc agent stub replacements and new HITL tool."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


def _instr_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


def _approval_mock(approval_id: str) -> MagicMock:
    """Return a plain MagicMock that behaves like a dict approval record."""
    m = MagicMock(spec=dict)
    m.__getitem__ = MagicMock(side_effect=lambda k: approval_id if k == "id" else None)
    m.get = MagicMock(side_effect=lambda k, *a: approval_id if k == "id" else (a[0] if a else None))
    return m


# ── query_activity_log ────────────────────────────────────────────────────────

class TestQueryActivityLogArc:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MonitorManagementClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_entries_from_sdk(self, mock_cred, mock_mon_cls, mock_id, mock_instr):
        """Real SDK path returns parsed activity log entries."""
        mock_instr.return_value = _instr_mock()
        mock_mon = MagicMock()
        mock_mon_cls.return_value = mock_mon
        event = MagicMock()
        event.event_timestamp.isoformat.return_value = "2026-04-11T10:00:00+00:00"
        event.operation_name.value = "Microsoft.HybridCompute/machines/write"
        event.caller = "admin@contoso.com"
        event.status.value = "Succeeded"
        event.resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"
        event.level.value = "Informational"
        event.description = "Arc machine updated"
        mock_mon.activity_logs.list.return_value = [event]

        from agents.arc.tools import query_activity_log

        result = query_activity_log(
            ["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"],
            timespan_hours=2,
        )
        assert result["query_status"] == "success"
        assert len(result["entries"]) == 1
        assert result["entries"][0]["operationName"] == "Microsoft.HybridCompute/machines/write"

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MonitorManagementClient", None)
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        """Returns error dict (not raises) when azure-mgmt-monitor not installed."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_activity_log

        result = query_activity_log(["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"])
        assert result["query_status"] == "error"
        assert "error" in result

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MonitorManagementClient")
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_on_sdk_exception(self, mock_cred, mock_mon_cls, mock_id, mock_instr):
        """SDK raises → returns error dict, not propagates exception."""
        mock_instr.return_value = _instr_mock()
        mock_mon = MagicMock()
        mock_mon_cls.return_value = mock_mon
        mock_mon.activity_logs.list.side_effect = Exception("ARM 403 Forbidden")

        from agents.arc.tools import query_activity_log

        result = query_activity_log(["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"])
        assert result["query_status"] == "error"
        assert "ARM 403" in result["error"]


# ── query_log_analytics ───────────────────────────────────────────────────────

class TestQueryLogAnalyticsArc:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.LogsQueryClient")
    @patch("agents.arc.tools.LogsQueryStatus")
    @patch("agents.arc.tools.get_credential")
    def test_returns_rows_on_success(self, mock_cred, mock_status_cls, mock_client_cls, mock_id, mock_instr):
        """SUCCESS status returns parsed rows."""
        mock_instr.return_value = _instr_mock()
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_status_cls.SUCCESS = "SUCCESS"

        col = MagicMock(); col.name = "Computer"
        table = MagicMock()
        table.columns = [col]
        table.rows = [["arc-vm1"]]
        response = MagicMock()
        response.status = "SUCCESS"
        response.tables = [table]
        mock_client.query_workspace.return_value = response

        from agents.arc.tools import query_log_analytics

        result = query_log_analytics("ws-id", "Heartbeat | limit 10", "PT2H")
        assert result["query_status"] == "success"
        assert len(result["rows"]) == 1
        assert result["rows"][0]["Computer"] == "arc-vm1"

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.get_credential")
    def test_skips_when_workspace_id_empty(self, mock_cred, mock_id, mock_instr):
        """Empty workspace_id returns query_status='skipped' without calling SDK."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_log_analytics

        result = query_log_analytics("", "Heartbeat | limit 10", "PT2H")
        assert result["query_status"] == "skipped"
        assert result["rows"] == []

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.LogsQueryClient", None)
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        """Returns error dict when azure-monitor-query not installed."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_log_analytics

        result = query_log_analytics("ws-id", "Heartbeat | limit 10", "PT2H")
        assert result["query_status"] == "error"


# ── query_resource_health ─────────────────────────────────────────────────────

class TestQueryResourceHealthArc:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MicrosoftResourceHealth")
    @patch("agents.arc.tools.get_credential")
    def test_returns_real_availability_state(self, mock_cred, mock_rh_cls, mock_id, mock_instr):
        """Real SDK path returns availability_state from ARM."""
        mock_instr.return_value = _instr_mock()
        mock_rh = MagicMock()
        mock_rh_cls.return_value = mock_rh
        status = MagicMock()
        status.properties.availability_state.value = "Available"
        status.properties.summary = "The resource is available."
        status.properties.reason_type = None
        status.properties.occurred_time = None
        mock_rh.availability_statuses.get_by_resource.return_value = status

        from agents.arc.tools import query_resource_health

        result = query_resource_health(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"
        )
        assert result["query_status"] == "success"
        assert result["availability_state"] == "Available"
        assert result["summary"] == "The resource is available."

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.MicrosoftResourceHealth", None)
    @patch("agents.arc.tools.get_credential")
    def test_returns_error_when_sdk_missing(self, mock_cred, mock_id, mock_instr):
        """Returns error dict when azure-mgmt-resourcehealth not installed."""
        mock_instr.return_value = _instr_mock()

        from agents.arc.tools import query_resource_health

        result = query_resource_health(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1"
        )
        assert result["query_status"] == "error"
        assert result["availability_state"] == "Unknown"

    def test_no_longer_returns_stub_pending_message(self):
        """Confirm stub string 'Resource Health query pending.' is gone from source."""
        from agents.arc import tools as arc_tools

        src = inspect.getsource(arc_tools.query_resource_health)
        assert "Resource Health query pending." not in src
        assert "MicrosoftResourceHealth" in src


# ── propose_arc_extension_install ─────────────────────────────────────────────

class TestProposeArcExtensionInstall:
    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record", new_callable=MagicMock)
    def test_creates_pending_approval(self, mock_create, mock_id, mock_instr):
        """Returns pending_approval status with approval_id from create_approval_record."""
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_ext_001", "status": "pending"}

        from agents.arc.tools import propose_arc_extension_install

        result = propose_arc_extension_install(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc-vm1",
            resource_group="rg",
            machine_name="arc-vm1",
            subscription_id="sub",
            extension_name="AzureMonitorWindowsAgent",
            extension_publisher="Microsoft.Azure.Monitor",
            incident_id="inc-001",
            thread_id="t1",
            reason="AMA missing — no Heartbeat in Log Analytics",
        )
        assert result["status"] == "pending_approval"
        assert result["approval_id"] == "appr_ext_001"
        assert "arc-vm1" in result["message"]
        assert "AzureMonitorWindowsAgent" in result["message"]

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record", new_callable=MagicMock)
    def test_calls_create_approval_with_medium_risk(self, mock_create, mock_id, mock_instr):
        """Approval record is created with risk_level='medium'."""
        mock_instr.return_value = _instr_mock()
        mock_create.return_value = {"id": "appr_002"}

        from agents.arc.tools import propose_arc_extension_install

        propose_arc_extension_install(
            resource_id="/subscriptions/sub/rg/providers/Microsoft.HybridCompute/machines/vm",
            resource_group="rg",
            machine_name="vm",
            subscription_id="sub",
            extension_name="AzureMonitorLinuxAgent",
            extension_publisher="Microsoft.Azure.Monitor",
            incident_id="inc-002",
            thread_id="t2",
            reason="AMA missing",
        )
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["risk_level"] == "medium"
        assert call_kwargs["proposal"]["action"] == "arc_extension_install"

    @patch("agents.arc.tools.instrument_tool_call")
    @patch("agents.arc.tools.get_agent_identity", return_value="id")
    @patch("agents.arc.tools.create_approval_record", new_callable=MagicMock)
    def test_returns_error_on_exception(self, mock_create, mock_id, mock_instr):
        """create_approval_record raises → returns error dict, not propagates."""
        mock_instr.return_value = _instr_mock()
        mock_create.side_effect = Exception("Cosmos unavailable")

        from agents.arc.tools import propose_arc_extension_install

        result = propose_arc_extension_install(
            resource_id="/subscriptions/sub/rg/providers/Microsoft.HybridCompute/machines/vm",
            resource_group="rg",
            machine_name="vm",
            subscription_id="sub",
            extension_name="AzureMonitorLinuxAgent",
            extension_publisher="Microsoft.Azure.Monitor",
            incident_id="inc-003",
            thread_id="t3",
            reason="AMA missing",
        )
        assert result["status"] == "error"
        assert "Cosmos unavailable" in result["message"]


# ── agent.py registration ─────────────────────────────────────────────────────

class TestArcAgentRegistration:
    def test_all_8_tools_importable_from_agent_module(self):
        """All 8 @ai_function tools can be imported from arc.tools module."""
        import arc.tools as arc_tools

        expected = [
            "query_activity_log",
            "query_log_analytics",
            "query_resource_health",
            "query_arc_extension_health",
            "query_arc_connectivity",
            "query_arc_guest_config",
            "propose_arc_assessment",
            "propose_arc_extension_install",
        ]
        for name in expected:
            assert hasattr(arc_tools, name), f"Tool '{name}' missing from arc.tools"

    def test_propose_arc_extension_install_in_allowed_tools_prompt(self):
        """The system prompt contains propose_arc_extension_install in Allowed Tools."""
        from agents.arc.agent import ARC_AGENT_SYSTEM_PROMPT

        assert "propose_arc_extension_install" in ARC_AGENT_SYSTEM_PROMPT

    def test_system_prompt_contains_all_8_ai_function_tools(self):
        """The Allowed Tools section of the system prompt lists all 8 ai_function tools."""
        from agents.arc.agent import ARC_AGENT_SYSTEM_PROMPT

        for tool_name in [
            "query_activity_log",
            "query_log_analytics",
            "query_resource_health",
            "query_arc_extension_health",
            "query_arc_connectivity",
            "query_arc_guest_config",
            "propose_arc_assessment",
            "propose_arc_extension_install",
        ]:
            assert tool_name in ARC_AGENT_SYSTEM_PROMPT, (
                f"Tool '{tool_name}' not found in ARC_AGENT_SYSTEM_PROMPT"
            )
