"""Tests for orchestrator A2A topology registration (Phase 29)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestOrchestratorAgentVersion:
    """Verify orchestrator registers A2A tools for all 8 domain agents."""

    def test_calls_create_version_with_orchestrator_name(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        # Mock connections for 8 domains
        mock_project.connections.get.return_value = MagicMock(id="conn-123")

        from agents.orchestrator.agent import create_orchestrator_agent_version

        create_orchestrator_agent_version(mock_project)

        mock_project.agents.create_version.assert_called_once()
        call_kwargs = mock_project.agents.create_version.call_args
        name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
        assert name == "aap-orchestrator"

    def test_fetches_connection_for_each_domain(self):
        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        mock_project.connections.get.return_value = MagicMock(id="conn-123")

        from agents.orchestrator.agent import create_orchestrator_agent_version

        create_orchestrator_agent_version(mock_project)

        # Phase 49: 12 A2A domains (added database, appservice, containerapps, messaging)
        assert mock_project.connections.get.call_count == 12

    def test_connection_get_failure_raises(self):
        mock_project = MagicMock()
        mock_project.connections.get.side_effect = Exception("Connection not found")

        from agents.orchestrator.agent import create_orchestrator_agent_version

        with pytest.raises(Exception, match="Connection not found"):
            create_orchestrator_agent_version(mock_project)
