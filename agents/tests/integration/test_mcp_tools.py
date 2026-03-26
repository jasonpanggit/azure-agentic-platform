"""Integration tests for MCP tool invocation (AGENT-004).

Wave 0 stubs — implementations in Plan 02-05.
"""
import pytest


@pytest.mark.integration
class TestMcpToolInvocation:
    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_compute_agent_calls_list_vms(self):
        """Compute Agent calls compute.list_vms, returns structured response."""
        pass

    @pytest.mark.skip(reason="Wave 4 — depends on agent implementations (02-04)")
    def test_tool_call_creates_otel_span(self):
        """MCP tool call produces OTel span with all AUDIT-001 fields."""
        pass
