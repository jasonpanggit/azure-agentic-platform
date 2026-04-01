"""Unit tests for Compute Agent tools (query_os_version and ALLOWED_MCP_TOOLS)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ALLOWED_MCP_TOOLS
# ---------------------------------------------------------------------------


class TestAllowedMcpTools:
    """Verify ALLOWED_MCP_TOOLS list is correct and has no wildcards."""

    def test_allowed_tools_is_list(self):
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        assert isinstance(ALLOWED_MCP_TOOLS, list)

    def test_no_wildcard_in_allowed_tools(self):
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        for entry in ALLOWED_MCP_TOOLS:
            assert "*" not in entry, f"Wildcard found in tool: {entry}"

    def test_allowed_tools_contains_expected_entries(self):
        from agents.compute.tools import ALLOWED_MCP_TOOLS

        assert "compute.list_vms" in ALLOWED_MCP_TOOLS
        assert "monitor.query_logs" in ALLOWED_MCP_TOOLS
        assert "resourcehealth.get_availability_status" in ALLOWED_MCP_TOOLS


# ---------------------------------------------------------------------------
# query_os_version
# ---------------------------------------------------------------------------


def _make_empty_response():
    resp = MagicMock()
    resp.data = []
    resp.skip_token = None
    return resp


def _make_instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestQueryOsVersion:
    """Verify query_os_version — ARG calls, pagination, and error handling."""

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_success_status_on_empty_response(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rg_cls.return_value.resources.return_value = _make_empty_response()

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert result["query_status"] == "success"
        assert result["machines"] == []
        assert result["total_count"] == 0

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_vm_machines_with_resource_type_field(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        vm_row = {
            "id": "/sub/vm-1",
            "name": "vm1",
            "osName": "Ubuntu 22.04",
            "resourceType": "vm",
        }
        vm_resp = MagicMock()
        vm_resp.data = [vm_row]
        vm_resp.skip_token = None

        # VM query returns 1 row; Arc query returns empty
        mock_rg_cls.return_value.resources.side_effect = [vm_resp, _make_empty_response()]

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert len(result["machines"]) == 1
        assert result["machines"][0]["resourceType"] == "vm"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_arc_machines_with_resource_type_field(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        arc_row = {
            "id": "/sub/arc-1",
            "name": "arc1",
            "osType": "linux",
            "osSku": "22.04",
            "resourceType": "arc",
        }
        arc_resp = MagicMock()
        arc_resp.data = [arc_row]
        arc_resp.skip_token = None

        # VM query empty; Arc query returns 1 row
        mock_rg_cls.return_value.resources.side_effect = [_make_empty_response(), arc_resp]

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/arc-1"],
            subscription_ids=["sub-1"],
        )

        assert len(result["machines"]) == 1
        assert result["machines"][0]["osSku"] == "22.04"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_paginates_via_skip_token(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()

        row = {"id": "/sub/vm-1", "name": "vm1"}

        page1 = MagicMock()
        page1.data = [row]
        page1.skip_token = "tok1"

        page2 = MagicMock()
        page2.data = [row]
        page2.skip_token = None

        # VM query: page1 + page2; Arc query: empty
        mock_rg_cls.return_value.resources.side_effect = [page1, page2, _make_empty_response()]

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert result["total_count"] == 2
        assert result["query_status"] == "success"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_returns_error_status_on_exception(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rg_cls.return_value.resources.side_effect = Exception("ARG unavailable")

        from agents.compute.tools import query_os_version

        result = query_os_version(
            resource_ids=["/sub/vm-1"],
            subscription_ids=["sub-1"],
        )

        assert result["query_status"] == "error"
        assert "ARG unavailable" in result["error"]

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="test-entra-id")
    @patch("agents.compute.tools.QueryRequestOptions", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.QueryRequest", side_effect=lambda **kw: MagicMock(**kw))
    @patch("agents.compute.tools.ResourceGraphClient")
    @patch("agents.compute.tools.get_credential", return_value=MagicMock())
    def test_filters_by_resource_ids_in_kql(
        self, mock_cred, mock_rg_cls, mock_qr, mock_qro, mock_identity, mock_instrument
    ):
        mock_instrument.return_value = _make_instrument_mock()
        mock_rg_cls.return_value.resources.return_value = _make_empty_response()

        captured_requests = []
        mock_qr.side_effect = lambda **kw: (captured_requests.append(kw), MagicMock(**kw))[1]

        from agents.compute.tools import query_os_version

        query_os_version(
            resource_ids=["/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
            subscription_ids=["sub-1"],
        )

        # Verify the KQL passed to QueryRequest contains the in~ filter
        assert len(captured_requests) >= 1
        first_kql = captured_requests[0]["query"]
        assert "in~" in first_kql
        assert "vm1" in first_kql


# ---------------------------------------------------------------------------
# ComputeAgentWiring
# ---------------------------------------------------------------------------


def _make_agent_framework_mock():
    """Build a minimal agent_framework mock that records ChatAgent() call_args."""
    mock_af = MagicMock()
    mock_af.ChatAgent = MagicMock(return_value=MagicMock())
    mock_af.ai_function = lambda f: f  # passthrough decorator
    mock_af.tool = lambda f: f         # passthrough decorator
    return mock_af


def _make_azure_mocks():
    """Stubs for azure packages to avoid import errors in environments without them."""
    shared_auth_mock = MagicMock()
    shared_auth_mock.get_foundry_client = MagicMock(return_value=MagicMock())
    shared_auth_mock.get_agent_identity = MagicMock(return_value="test-entra-id")
    shared_auth_mock.get_credential = MagicMock(return_value=MagicMock())

    shared_otel_mock = MagicMock()
    shared_otel_mock.setup_telemetry = MagicMock(return_value=MagicMock())
    shared_otel_mock.instrument_tool_call = MagicMock()

    return {
        "azure.identity": MagicMock(),
        "azure.ai.projects": MagicMock(),
        "shared.auth": shared_auth_mock,
        "shared.otel": shared_otel_mock,
    }


class TestComputeAgentWiring:
    """Verify query_os_version is wired into the compute agent."""

    def test_query_os_version_in_agent_tools(self):
        """create_compute_agent must pass query_os_version in its tools list."""
        mock_af = _make_agent_framework_mock()
        azure_mocks = _make_azure_mocks()

        # Evict cached module so the mock takes effect on re-import
        for key in list(sys.modules.keys()):
            if "agents.compute.agent" in key or key == "compute.agent":
                del sys.modules[key]

        extra_mocks = {"agent_framework": mock_af, **azure_mocks}
        with patch.dict("sys.modules", extra_mocks):
            import agents.compute.agent as _mod
            _mod.create_compute_agent()

        call_kwargs = mock_af.ChatAgent.call_args[1]
        tools = call_kwargs.get("tools", [])
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]
        assert "query_os_version" in tool_names
