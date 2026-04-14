"""Integration tests for MCP tool invocation and OTel span recording (AGENT-004, AUDIT-001).

Validates ROADMAP Phase 2 Success Criterion 3:
A domain agent calls at least one Azure MCP Server tool, returns a structured
response, and the tool call is logged as an OpenTelemetry span with agentId,
toolName, toolParameters, outcome, and durationMs.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.compute.tools import ALLOWED_MCP_TOOLS
from agents.shared.otel import record_tool_call_span, setup_telemetry


@pytest.mark.integration
class TestMcpToolAllowlists:
    """Verify each agent has an explicit MCP tool allowlist (no wildcards)."""

    def test_compute_has_explicit_allowlist(self):
        assert isinstance(ALLOWED_MCP_TOOLS, list)
        assert len(ALLOWED_MCP_TOOLS) > 0

    def test_compute_allowlist_contains_compute(self):
        assert "compute" in ALLOWED_MCP_TOOLS

    def test_compute_allowlist_contains_monitor(self):
        assert "monitor" in ALLOWED_MCP_TOOLS

    def test_compute_allowlist_contains_resource_health(self):
        assert "resourcehealth" in ALLOWED_MCP_TOOLS

    def test_compute_allowlist_has_no_wildcard(self):
        """AGENT-009: No wildcard tool access."""
        assert "*" not in ALLOWED_MCP_TOOLS
        assert "all" not in [t.lower() for t in ALLOWED_MCP_TOOLS]

    def test_network_has_explicit_allowlist(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS as net_tools
        assert isinstance(net_tools, list)
        assert "*" not in net_tools

    def test_network_allowlist_is_non_empty(self):
        from agents.network.tools import ALLOWED_MCP_TOOLS as net_tools
        assert len(net_tools) > 0

    def test_storage_has_explicit_allowlist(self):
        from agents.storage.tools import ALLOWED_MCP_TOOLS as store_tools
        assert isinstance(store_tools, list)
        assert "storage" in store_tools
        assert "*" not in store_tools

    def test_security_has_explicit_allowlist(self):
        from agents.security.tools import ALLOWED_MCP_TOOLS as sec_tools
        assert isinstance(sec_tools, list)
        assert "keyvault" in sec_tools
        assert "*" not in sec_tools

    def test_sre_has_explicit_allowlist(self):
        from agents.sre.tools import ALLOWED_MCP_TOOLS as sre_tools
        assert isinstance(sre_tools, list)
        assert "monitor" in sre_tools
        assert "*" not in sre_tools

    def test_arc_has_explicit_allowlist(self):
        """Phase 3 upgrade: Arc agent now has a non-empty explicit allowlist (AGENT-005)."""
        from agents.arc.tools import ALLOWED_MCP_TOOLS as arc_tools
        assert isinstance(arc_tools, list)
        assert len(arc_tools) > 0
        assert "*" not in arc_tools

    def test_no_dotted_names_across_all_agents(self):
        """v2 MCP uses namespace names, not dotted names."""
        from agents.compute.tools import ALLOWED_MCP_TOOLS as compute_tools
        from agents.network.tools import ALLOWED_MCP_TOOLS as net_tools
        from agents.storage.tools import ALLOWED_MCP_TOOLS as store_tools
        from agents.security.tools import ALLOWED_MCP_TOOLS as sec_tools
        from agents.sre.tools import ALLOWED_MCP_TOOLS as sre_tools
        from agents.eol.tools import ALLOWED_MCP_TOOLS as eol_tools
        from agents.patch.tools import ALLOWED_MCP_TOOLS as patch_tools
        from agents.arc.tools import ALLOWED_MCP_TOOLS as arc_tools

        all_lists = {
            "compute": compute_tools,
            "network": net_tools,
            "storage": store_tools,
            "security": sec_tools,
            "sre": sre_tools,
            "eol": eol_tools,
            "patch": patch_tools,
            "arc": arc_tools,
        }
        for agent_name, tools in all_lists.items():
            for tool in tools:
                # Arc MCP tools use underscores (arc_servers_list) — not dotted
                assert "." not in tool, (
                    f"{agent_name}: dotted tool name '{tool}' — "
                    f"must use v2 namespace name"
                )


@pytest.mark.integration
class TestOtelSpanRecording:
    """Verify tool calls produce OpenTelemetry spans with all AUDIT-001 fields."""

    REQUIRED_SPAN_ATTRIBUTES = [
        "aiops.agent_id",
        "aiops.agent_name",
        "aiops.tool_name",
        "aiops.tool_parameters",
        "aiops.outcome",
        "aiops.duration_ms",
        "aiops.correlation_id",
        "aiops.thread_id",
    ]

    def test_record_tool_call_span_sets_all_audit_fields(self):
        """OTel span must contain all 8 AUDIT-001 fields."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = lambda _: mock_span
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

        with patch("agents.shared.otel.trace") as mock_trace:
            mock_trace.get_tracer.return_value = mock_tracer
            mock_trace.StatusCode = MagicMock()

            record_tool_call_span(
                agent_id="entra-object-id-123",
                agent_name="compute-agent",
                tool_name="compute.list_vms",
                tool_parameters={"subscription_id": "sub-1"},
                outcome="success",
                duration_ms=150,
                correlation_id="inc-001",
                thread_id="thread-abc",
            )

        # Verify all required attributes were set
        set_calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }
        for attr in self.REQUIRED_SPAN_ATTRIBUTES:
            assert attr in set_calls, f"Missing span attribute: {attr}"

    def test_span_agent_id_is_not_system(self):
        """AUDIT-005: agentId must be specific Entra object ID, not 'system'."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = lambda _: mock_span
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

        with patch("agents.shared.otel.trace") as mock_trace:
            mock_trace.get_tracer.return_value = mock_tracer
            mock_trace.StatusCode = MagicMock()

            record_tool_call_span(
                agent_id="entra-object-id-123",
                agent_name="compute-agent",
                tool_name="compute.list_vms",
                tool_parameters={},
                outcome="success",
                duration_ms=100,
                correlation_id="inc-001",
                thread_id="thread-abc",
            )

        set_calls = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }
        assert set_calls["aiops.agent_id"] == "entra-object-id-123"
        assert set_calls["aiops.agent_id"] != "system"

    def test_failure_outcome_sets_error_status(self):
        """Failed tool calls must set ERROR status on span."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = lambda _: mock_span
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

        with patch("agents.shared.otel.trace") as mock_trace:
            mock_trace.get_tracer.return_value = mock_tracer
            mock_trace.StatusCode = MagicMock()

            record_tool_call_span(
                agent_id="entra-123",
                agent_name="compute-agent",
                tool_name="compute.list_vms",
                tool_parameters={},
                outcome="failure",
                duration_ms=5000,
                correlation_id="inc-002",
                thread_id="thread-def",
            )

        mock_span.set_status.assert_called_once()
