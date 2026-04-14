"""Unit tests for Patch Agent factory (Phase 11)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------


class TestPatchAgentSystemPrompt:
    """Verify PATCH_AGENT_SYSTEM_PROMPT contains all mandatory references."""

    def _get_prompt(self):
        from agents.patch.agent import PATCH_AGENT_SYSTEM_PROMPT

        return PATCH_AGENT_SYSTEM_PROMPT

    def test_system_prompt_contains_triage_003(self):
        assert "TRIAGE-003" in self._get_prompt()

    def test_system_prompt_contains_triage_002(self):
        assert "TRIAGE-002" in self._get_prompt()

    def test_system_prompt_contains_triage_004(self):
        assert "TRIAGE-004" in self._get_prompt()

    def test_system_prompt_contains_triage_005(self):
        assert "TRIAGE-005" in self._get_prompt()

    def test_system_prompt_contains_remedi_001(self):
        assert "REMEDI-001" in self._get_prompt()

    def test_system_prompt_contains_activity_log_first(self):
        assert "Activity Log first" in self._get_prompt()

    def test_system_prompt_contains_confidence_score(self):
        assert "confidence_score" in self._get_prompt()

    def test_system_prompt_contains_query_patch_assessment(self):
        prompt = self._get_prompt()
        assert "query_patch_assessment" in prompt

    def test_system_prompt_contains_search_runbooks(self):
        assert "search_runbooks" in self._get_prompt()

    def test_system_prompt_contains_schedule_aum_assessment(self):
        assert "schedule_aum_assessment" in self._get_prompt()

    def test_system_prompt_contains_schedule_aum_patch_installation(self):
        assert "schedule_aum_patch_installation" in self._get_prompt()


class TestPatchAgentSystemPromptSafetyConstraints:
    """Verify system prompt safety constraints."""

    def _get_prompt(self):
        from agents.patch.agent import PATCH_AGENT_SYSTEM_PROMPT

        return PATCH_AGENT_SYSTEM_PROMPT

    def test_system_prompt_contains_must_not_execute(self):
        assert "MUST NOT execute" in self._get_prompt()

    def test_system_prompt_contains_human_approval(self):
        assert "human approval" in self._get_prompt()

    def test_system_prompt_contains_wildcard_constraint(self):
        assert "wildcard" in self._get_prompt()


class TestPatchAgentSystemPromptAllowedTools:
    """Verify all tool names appear in the Allowed Tools section."""

    def _get_prompt(self):
        from agents.patch.agent import PATCH_AGENT_SYSTEM_PROMPT

        return PATCH_AGENT_SYSTEM_PROMPT

    def test_prompt_lists_query_activity_log(self):
        assert "query_activity_log" in self._get_prompt()

    def test_prompt_lists_query_patch_assessment(self):
        assert "query_patch_assessment" in self._get_prompt()

    def test_prompt_lists_query_patch_installations(self):
        assert "query_patch_installations" in self._get_prompt()

    def test_prompt_lists_query_configuration_data(self):
        assert "query_configuration_data" in self._get_prompt()

    def test_prompt_lists_lookup_kb_cves(self):
        assert "lookup_kb_cves" in self._get_prompt()

    def test_prompt_lists_query_resource_health(self):
        assert "query_resource_health" in self._get_prompt()

    def test_prompt_lists_search_runbooks(self):
        assert "search_runbooks" in self._get_prompt()

    def test_prompt_lists_monitor(self):
        assert "monitor" in self._get_prompt()

    def test_prompt_lists_resourcehealth(self):
        assert "resourcehealth" in self._get_prompt()


# ---------------------------------------------------------------------------
# Agent factory tests
# ---------------------------------------------------------------------------


class TestCreatePatchAgent:
    """Verify create_patch_agent factory function."""

    @patch.dict("os.environ", {"AZURE_MCP_SERVER_URL": ""}, clear=False)
    @patch("agents.patch.agent.ChatAgent")
    @patch("agents.patch.agent.get_foundry_client", return_value=MagicMock())
    def test_create_patch_agent_returns_chat_agent(self, mock_client, mock_chat_agent):
        from agents.patch.agent import create_patch_agent

        agent = create_patch_agent()

        # ChatAgent was called with name="patch-agent"
        mock_chat_agent.assert_called_once()
        call_kwargs = mock_chat_agent.call_args[1]
        assert call_kwargs["name"] == "patch-agent"

    @patch.dict("os.environ", {"AZURE_MCP_SERVER_URL": ""}, clear=False)
    @patch("agents.patch.agent.ChatAgent")
    @patch("agents.patch.agent.get_foundry_client", return_value=MagicMock())
    def test_create_patch_agent_registers_search_runbooks_in_tools(
        self, mock_client, mock_chat_agent
    ):
        """Verify search_runbooks (the sync wrapper) is in the agent's tools list (TRIAGE-005)."""
        from agents.patch.agent import create_patch_agent
        from agents.patch.tools import search_runbooks

        create_patch_agent()

        call_kwargs = mock_chat_agent.call_args[1]
        assert any(f.__name__ == "search_runbooks" for f in call_kwargs["tools"])

    @patch.dict("os.environ", {"AZURE_MCP_SERVER_URL": ""}, clear=False)
    @patch("agents.patch.agent.ChatAgent")
    @patch("agents.patch.agent.get_foundry_client", return_value=MagicMock())
    def test_create_patch_agent_registers_all_eight_tools(
        self, mock_client, mock_chat_agent
    ):
        from agents.patch.agent import create_patch_agent

        create_patch_agent()

        call_kwargs = mock_chat_agent.call_args[1]
        assert len(call_kwargs["tools"]) == 8

    @patch.dict(
        "os.environ",
        {"AZURE_MCP_SERVER_URL": "http://azure-mcp.internal:8080/mcp"},
        clear=False,
    )
    @patch("agents.patch.agent.MCPTool")
    @patch("agents.patch.agent.ChatAgent")
    @patch("agents.patch.agent.get_foundry_client", return_value=MagicMock())
    def test_create_patch_agent_mounts_mcp_tool_when_url_set(
        self, mock_client, mock_chat_agent, mock_mcp_tool
    ):
        from agents.patch.agent import create_patch_agent

        create_patch_agent()

        # MCPTool should have been created
        mock_mcp_tool.assert_called_once()
        # ChatAgent should receive non-empty tool_resources
        call_kwargs = mock_chat_agent.call_args[1]
        assert len(call_kwargs["tools"]) >= 1

    @patch.dict("os.environ", {"AZURE_MCP_SERVER_URL": ""}, clear=False)
    @patch("agents.patch.agent.ChatAgent")
    @patch("agents.patch.agent.get_foundry_client", return_value=MagicMock())
    def test_create_patch_agent_works_without_mcp_url(
        self, mock_client, mock_chat_agent
    ):
        from agents.patch.agent import create_patch_agent

        create_patch_agent()

        call_kwargs = mock_chat_agent.call_args[1]
        assert isinstance(call_kwargs["tools"], list)

    @patch.dict("os.environ", {"AZURE_MCP_SERVER_URL": ""}, clear=False)
    @patch("agents.patch.agent.get_foundry_client", return_value=MagicMock())
    def test_create_patch_agent_does_not_import_retrieve_runbooks_directly(
        self, mock_client
    ):
        """Verify agent.py does NOT directly import retrieve_runbooks from shared."""
        import agents.patch.agent as agent_module
        import inspect

        source = inspect.getsource(agent_module)
        assert "from agents.shared.runbook_tool import retrieve_runbooks" not in source
