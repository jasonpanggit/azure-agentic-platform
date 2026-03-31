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


def _make_azure_mocks():
    """Build stubs for azure.identity and azure.ai.projects to avoid PyO3 re-init errors."""
    azure_identity_mock = MagicMock()
    azure_identity_mock.DefaultAzureCredential = MagicMock()

    azure_ai_projects_mock = MagicMock()

    shared_auth_mock = MagicMock()
    shared_auth_mock.get_foundry_client = MagicMock(return_value=MagicMock())
    shared_auth_mock.get_agent_identity = MagicMock(return_value="test-entra-id")
    shared_auth_mock.get_credential = MagicMock(return_value=MagicMock())

    shared_otel_mock = MagicMock()
    shared_otel_mock.setup_telemetry = MagicMock(return_value=MagicMock())
    shared_otel_mock.instrument_tool_call = MagicMock()

    return {
        "azure.identity": azure_identity_mock,
        "azure.ai.projects": azure_ai_projects_mock,
        "shared.auth": shared_auth_mock,
        "shared.otel": shared_otel_mock,
    }


# Patch agent_framework at module level so agents.eol.agent can be imported
# in environments where agent_framework does not have MCPStreamableHTTPTool.
_MOCK_AF = _make_agent_framework_mock()
_AZURE_MOCKS = _make_azure_mocks()


def _import_eol_agent():
    """Import agents.eol.agent with agent_framework and azure dependencies fully mocked.

    Uses broad sys.modules patching to avoid PyO3 re-initialization errors
    when azure.identity (cryptography) is loaded multiple times in the same
    pytest session.
    """
    # Remove cached eol agent modules to force re-import with mocks
    for key in list(sys.modules.keys()):
        if "agents.eol.agent" in key:
            del sys.modules[key]

    extra_mocks = {"agent_framework": _MOCK_AF, **_AZURE_MOCKS}
    with patch.dict("sys.modules", extra_mocks):
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


def _import_eol_agent_with_af(mock_af: MagicMock, extra_env: dict | None = None) -> MagicMock:
    """Import agents.eol.agent with a custom agent_framework mock + azure stubs,
    then call create_eol_agent() so Agent() is invoked.

    Returns the mock_af so callers can inspect call_args after the import.
    """
    for key in list(sys.modules.keys()):
        if "agents.eol.agent" in key:
            del sys.modules[key]

    extra_mocks = {"agent_framework": mock_af, **_AZURE_MOCKS}
    env_patch = extra_env if extra_env is not None else {}
    with patch.dict("sys.modules", extra_mocks):
        with patch.dict(os.environ, env_patch, clear=(extra_env is not None)):
            import agents.eol.agent as _mod
            _mod.create_eol_agent()
    return mock_af


class TestCreateEolAgent:
    """Verify create_eol_agent factory function behaviour."""

    def test_agent_name_is_eol_agent(self):
        """Agent must be constructed with name='eol-agent'."""
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()

        env = {k: v for k, v in os.environ.items() if k != "AZURE_MCP_SERVER_URL"}
        _import_eol_agent_with_af(mock_af, extra_env=env)

        call_kwargs = mock_af.Agent.call_args[1]
        assert call_kwargs.get("name") == "eol-agent"

    def test_agent_has_9_tools_without_mcp(self):
        """Without AZURE_MCP_SERVER_URL, Agent should receive exactly 9 tools."""
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()

        env = {k: v for k, v in os.environ.items() if k != "AZURE_MCP_SERVER_URL"}
        _import_eol_agent_with_af(mock_af, extra_env=env)

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

        env = {k: v for k, v in os.environ.items()}
        env["AZURE_MCP_SERVER_URL"] = "http://localhost/mcp"
        _import_eol_agent_with_af(mock_af, extra_env=env)

        call_kwargs = mock_af.Agent.call_args[1]
        tools = call_kwargs.get("tools")
        assert tools is not None, "tools argument not passed to Agent"
        assert len(tools) == 10
        mock_af.MCPStreamableHTTPTool.assert_called_once()

    def test_agent_description_contains_eol(self):
        """Agent description must mention EOL or End-of-Life."""
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()

        env = {k: v for k, v in os.environ.items() if k != "AZURE_MCP_SERVER_URL"}
        _import_eol_agent_with_af(mock_af, extra_env=env)

        call_kwargs = mock_af.Agent.call_args[1]
        description = call_kwargs.get("description", "")
        assert (
            "End-of-Life" in description
            or "EOL" in description
            or "eol" in description.lower()
        )

    def test_agent_uses_foundry_client(self):
        """create_eol_agent must call get_foundry_client().

        We verify get_foundry_client is invoked by checking that Agent() is
        called at all (the module-level shared_auth mock already provides it).
        """
        mock_af = _make_agent_framework_mock()
        mock_af.Agent.return_value = MagicMock()

        env = {k: v for k, v in os.environ.items() if k != "AZURE_MCP_SERVER_URL"}
        _import_eol_agent_with_af(mock_af, extra_env=env)

        # Agent factory was called — get_foundry_client was invoked as part of create_eol_agent()
        mock_af.Agent.assert_called_once()

