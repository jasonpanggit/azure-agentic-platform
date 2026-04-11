"""Tests for scripts/register_agents.py — Phase 29 agent version registration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRegisterAllAgents:
    """Verify register_all_agents calls create_version for all 9 agents."""

    @patch("scripts.register_agents.create_orchestrator_agent_version")
    @patch("scripts.register_agents.create_storage_agent_version")
    @patch("scripts.register_agents.create_sre_agent_version")
    @patch("scripts.register_agents.create_security_agent_version")
    @patch("scripts.register_agents.create_patch_agent_version")
    @patch("scripts.register_agents.create_network_agent_version")
    @patch("scripts.register_agents.create_eol_agent_version")
    @patch("scripts.register_agents.create_arc_agent_version")
    @patch("scripts.register_agents.create_compute_agent_version")
    def test_registers_all_9_agents(
        self,
        mock_compute, mock_arc, mock_eol, mock_network,
        mock_patch, mock_security, mock_sre, mock_storage, mock_orchestrator,
    ):
        mock_project = MagicMock()
        for m in [mock_compute, mock_arc, mock_eol, mock_network,
                  mock_patch, mock_security, mock_sre, mock_storage, mock_orchestrator]:
            m.return_value = MagicMock(id="ver_123")

        from scripts.register_agents import register_all_agents

        results = register_all_agents(mock_project)

        mock_compute.assert_called_once_with(mock_project)
        mock_arc.assert_called_once_with(mock_project)
        mock_orchestrator.assert_called_once_with(mock_project)
        assert len(results) == 9

    @patch("scripts.register_agents.create_orchestrator_agent_version")
    @patch("scripts.register_agents.create_storage_agent_version")
    @patch("scripts.register_agents.create_sre_agent_version")
    @patch("scripts.register_agents.create_security_agent_version")
    @patch("scripts.register_agents.create_patch_agent_version")
    @patch("scripts.register_agents.create_network_agent_version")
    @patch("scripts.register_agents.create_eol_agent_version")
    @patch("scripts.register_agents.create_arc_agent_version")
    @patch("scripts.register_agents.create_compute_agent_version")
    def test_returns_dict_with_agent_names(
        self,
        mock_compute, mock_arc, mock_eol, mock_network,
        mock_patch, mock_security, mock_sre, mock_storage, mock_orchestrator,
    ):
        mock_project = MagicMock()
        for m in [mock_compute, mock_arc, mock_eol, mock_network,
                  mock_patch, mock_security, mock_sre, mock_storage, mock_orchestrator]:
            m.return_value = MagicMock(id="ver_abc")

        from scripts.register_agents import register_all_agents

        results = register_all_agents(mock_project)

        assert "aap-compute-agent" in results
        assert "aap-orchestrator" in results
        assert "aap-arc-agent" in results

    @patch("scripts.register_agents.create_orchestrator_agent_version")
    @patch("scripts.register_agents.create_storage_agent_version")
    @patch("scripts.register_agents.create_sre_agent_version")
    @patch("scripts.register_agents.create_security_agent_version")
    @patch("scripts.register_agents.create_patch_agent_version")
    @patch("scripts.register_agents.create_network_agent_version")
    @patch("scripts.register_agents.create_eol_agent_version")
    @patch("scripts.register_agents.create_arc_agent_version")
    @patch("scripts.register_agents.create_compute_agent_version")
    def test_orchestrator_registered_last(
        self,
        mock_compute, mock_arc, mock_eol, mock_network,
        mock_patch, mock_security, mock_sre, mock_storage, mock_orchestrator,
    ):
        """Orchestrator must be registered after all domain agents (A2A connections need to exist)."""
        mock_project = MagicMock()
        call_order = []

        for name, m in [
            ("compute", mock_compute), ("arc", mock_arc), ("eol", mock_eol),
            ("network", mock_network), ("patch", mock_patch),
            ("security", mock_security), ("sre", mock_sre),
            ("storage", mock_storage), ("orchestrator", mock_orchestrator),
        ]:
            m.side_effect = lambda proj, n=name: (call_order.append(n), MagicMock(id=f"ver_{n}"))[1]

        from scripts.register_agents import register_all_agents

        register_all_agents(mock_project)

        assert call_order[-1] == "orchestrator", f"Orchestrator should be last, got order: {call_order}"
