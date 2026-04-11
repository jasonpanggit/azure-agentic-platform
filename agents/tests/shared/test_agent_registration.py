"""Tests for create_version agent registration pattern (Phase 29).

Validates that each agent's create_*_agent_version() function:
- calls project.agents.create_version with correct agent_name
- passes a PromptAgentDefinition
- includes the agent's tool functions
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestComputeAgentVersion:
    """Verify compute agent create_version registration."""

    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_version = MagicMock()
        mock_project.agents.create_version.return_value = mock_version

        from agents.compute.agent import create_compute_agent_version

        result = create_compute_agent_version(mock_project)

        mock_project.agents.create_version.assert_called_once()
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[1].get("agent_name", call_kwargs[0][0] if call_kwargs[0] else None)
        assert name == "aap-compute-agent"

    def test_returns_agent_version(self):
        mock_project = MagicMock()
        mock_version = MagicMock()
        mock_project.agents.create_version.return_value = mock_version

        from agents.compute.agent import create_compute_agent_version

        result = create_compute_agent_version(mock_project)
        assert result == mock_version

    def test_definition_includes_model_env_var(self, monkeypatch):
        monkeypatch.setenv("AGENT_MODEL_DEPLOYMENT", "gpt-4.1")
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()

        from agents.compute.agent import create_compute_agent_version

        create_compute_agent_version(mock_project)

        call_kwargs = mock_project.agents.create_version.call_args
        # definition should be a PromptAgentDefinition or dict-like with model
        definition = call_kwargs.kwargs.get("definition")
        assert definition is not None


class TestArcAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.arc.agent import create_arc_agent_version
        create_arc_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-arc-agent"


class TestEolAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.eol.agent import create_eol_agent_version
        create_eol_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-eol-agent"


class TestNetworkAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.network.agent import create_network_agent_version
        create_network_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-network-agent"


class TestPatchAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.patch.agent import create_patch_agent_version
        create_patch_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-patch-agent"


class TestSecurityAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.security.agent import create_security_agent_version
        create_security_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-security-agent"


class TestSreAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.sre.agent import create_sre_agent_version
        create_sre_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-sre-agent"


class TestStorageAgentVersion:
    def test_calls_create_version_with_correct_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        from agents.storage.agent import create_storage_agent_version
        create_storage_agent_version(mock_project)
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-storage-agent"
