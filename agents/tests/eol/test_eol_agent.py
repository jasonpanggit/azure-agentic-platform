"""Unit tests for EOL Agent factory and system prompt (Phase 12)."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_agent_framework_mock():
    """Build a minimal agent_framework mock with MCPStreamableHTTPTool."""
    mock_af = MagicMock()
    mock_af.Agent = MagicMock()
    mock_af.ChatAgent = MagicMock()
    mock_af.MCPStreamableHTTPTool = MagicMock()
    mock_af.ai_function = lambda f: f  # passthrough decorator
    mock_af.tool = lambda f: f  # passthrough decorator
    return mock_af


# Patch agent_framework at module level so agents.eol.agent can be imported
# in environments where agent_framework does not have MCPStreamableHTTPTool.
_MOCK_AF = _make_agent_framework_mock()


def _import_eol_agent():
    """Import agents.eol.agent with agent_framework fully mocked."""
    # Remove cached module to force re-import with mock
    for key in list(sys.modules.keys()):
        if "agents.eol.agent" in key:
            del sys.modules[key]

    with patch.dict("sys.modules", {"agent_framework": _MOCK_AF}):
        import agents.eol.agent as eol_agent_mod

        return eol_agent_mod


# ---------------------------------------------------------------------------
# EOL_AGENT_SYSTEM_PROMPT
# ---------------------------------------------------------------------------


class TestEolAgentSystemPrompt:
    """Verify EOL_AGENT_SYSTEM_PROMPT content and requirement traceability."""

    def _get_prompt(self):
        mod = _import_eol_agent()
        return mod.EOL_AGENT_SYSTEM_PROMPT

    def test_prompt_contains_eol_agent_identity(self):
        assert "AAP EOL Agent" in self._get_prompt()

    def test_prompt_contains_scope_section(self):
        assert "## Scope" in self._get_prompt()

    def test_prompt_contains_mandatory_workflow(self):
        assert "Mandatory Triage Workflow" in self._get_prompt()

    def test_prompt_contains_safety_constraints(self):
        assert "Safety Constraints" in self._get_prompt()

    def test_prompt_contains_triage_003(self):
        assert "TRIAGE-003" in self._get_prompt()

    def test_prompt_contains_remedi_001(self):
        assert "REMEDI-001" in self._get_prompt()

    def test_prompt_contains_source_routing_rules(self):
        assert "Source Routing" in self._get_prompt()

    def test_prompt_contains_allowed_tools_list(self):
        prompt = self._get_prompt()
        expected_tools = [
            "query_activity_log",
            "query_os_inventory",
            "query_software_inventory",
            "query_k8s_versions",
            "query_endoflife_date",
            "query_ms_lifecycle",
            "query_resource_health",
            "search_runbooks",
            "scan_estate_eol",
        ]
        for tool_name in expected_tools:
            assert tool_name in prompt, (
                f"Expected tool '{tool_name}' not found in system prompt"
            )

    def test_prompt_mentions_endoflife_date(self):
        assert "endoflife.date" in self._get_prompt()

    def test_prompt_mentions_ms_lifecycle(self):
        prompt = self._get_prompt()
        assert (
            "Microsoft Product Lifecycle" in prompt
            or "MS Lifecycle" in prompt
            or "ms-lifecycle" in prompt
        )


# ---------------------------------------------------------------------------
# create_eol_agent
# ---------------------------------------------------------------------------


class TestCreateEolAgent:
    """Verify create_eol_agent factory function behaviour."""

    def test_agent_name_is_eol_agent(self):
        """Agent must be constructed with name='eol-agent'."""
        mock_af = _make_agent_framework_mock()
        mock_agent_instance = MagicMock()
        mock_af.Agent.return_value = mock_agent_instance

        with patch.dict("sys.modules", {"agent_framework": mock_af}):
            # Remove cached module
            for key in list(sys.modules.keys()):
                if "agents.eol.agent" in key:
                    del sys.modules[key]

            with patch("agents.eol.agent.get_foundry_client", return_value=MagicMock()):
                with patch.dict(os.environ, {}, clear=False):
                    if "AZURE_MCP_SERVER_URL" in os.environ:
                        del os.environ["AZURE_MCP_SERVER_URL"]
                    from agents.eol.agent import create_eol_agent

                    create_eol_agent()

        call_kwargs = mock_af.Agent.call_args[1]
        assert call_kwargs.get("name") == "eol-agent"

    def test_agent_has_9_tools_without_mcp(self):
        """Without AZURE_MCP_SERVER_URL, Agent should receive exactly 9 tools."""
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()

        with patch.dict("sys.modules", {"agent_framework": mock_af}):
            for key in list(sys.modules.keys()):
                if "agents.eol.agent" in key:
                    del sys.modules[key]

            env = {k: v for k, v in os.environ.items() if k != "AZURE_MCP_SERVER_URL"}
            with patch.dict(os.environ, env, clear=True):
                with patch("agents.eol.agent.get_foundry_client", return_value=MagicMock()):
                    from agents.eol.agent import create_eol_agent

                    create_eol_agent()

        call_kwargs = mock_af.Agent.call_args[1]
        tools = call_kwargs.get("tools")
        assert tools is not None, "tools argument not passed to Agent"
        assert len(tools) == 9

    def test_agent_has_10_tools_with_mcp(self):
        """With AZURE_MCP_SERVER_URL set, Agent should receive 10 tools."""
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()
        mock_mcp_instance = MagicMock()
        mock_af.MCPStreamableHTTPTool.return_value = mock_mcp_instance

        with patch.dict("sys.modules", {"agent_framework": mock_af}):
            for key in list(sys.modules.keys()):
                if "agents.eol.agent" in key:
                    del sys.modules[key]

            with patch.dict(os.environ, {"AZURE_MCP_SERVER_URL": "http://localhost/mcp"}):
                with patch("agents.eol.agent.get_foundry_client", return_value=MagicMock()):
                    from agents.eol.agent import create_eol_agent

                    create_eol_agent()

        call_kwargs = mock_af.Agent.call_args[1]
        tools = call_kwargs.get("tools")
        assert tools is not None, "tools argument not passed to Agent"
        assert len(tools) == 10
        mock_af.MCPStreamableHTTPTool.assert_called_once()

    def test_agent_description_contains_eol(self):
        """Agent description must mention EOL or End-of-Life."""
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()

        with patch.dict("sys.modules", {"agent_framework": mock_af}):
            for key in list(sys.modules.keys()):
                if "agents.eol.agent" in key:
                    del sys.modules[key]

            env = {k: v for k, v in os.environ.items() if k != "AZURE_MCP_SERVER_URL"}
            with patch.dict(os.environ, env, clear=True):
                with patch("agents.eol.agent.get_foundry_client", return_value=MagicMock()):
                    from agents.eol.agent import create_eol_agent

                    create_eol_agent()

        call_kwargs = mock_af.Agent.call_args[1]
        description = call_kwargs.get("description", "")
        assert (
            "End-of-Life" in description
            or "EOL" in description
            or "eol" in description.lower()
        )

    def test_agent_uses_foundry_client(self):
        """create_eol_agent must call get_foundry_client()."""
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()

        with patch.dict("sys.modules", {"agent_framework": mock_af}):
            for key in list(sys.modules.keys()):
                if "agents.eol.agent" in key:
                    del sys.modules[key]

            env = {k: v for k, v in os.environ.items() if k != "AZURE_MCP_SERVER_URL"}
            with patch.dict(os.environ, env, clear=True):
                with patch(
                    "agents.eol.agent.get_foundry_client", return_value=MagicMock()
                ) as mock_get_client:
                    from agents.eol.agent import create_eol_agent

                    create_eol_agent()

                mock_get_client.assert_called_once()
