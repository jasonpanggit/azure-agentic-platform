"""Phase 29 smoke tests — agent registration roundtrip and Responses API dispatch.

These tests verify the Phase 29 wiring but do NOT call real Azure endpoints.
All external calls are mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestPhase29Smoke:
    """Verify the complete Phase 29 registration and dispatch chain."""

    def test_all_create_version_functions_importable(self):
        """All 9 create_*_agent_version functions must be importable."""
        from agents.arc.agent import create_arc_agent_version
        from agents.compute.agent import create_compute_agent_version
        from agents.eol.agent import create_eol_agent_version
        from agents.network.agent import create_network_agent_version
        from agents.orchestrator.agent import create_orchestrator_agent_version
        from agents.patch.agent import create_patch_agent_version
        from agents.security.agent import create_security_agent_version
        from agents.sre.agent import create_sre_agent_version
        from agents.storage.agent import create_storage_agent_version

        assert all([
            create_compute_agent_version,
            create_arc_agent_version,
            create_eol_agent_version,
            create_network_agent_version,
            create_orchestrator_agent_version,
            create_patch_agent_version,
            create_security_agent_version,
            create_sre_agent_version,
            create_storage_agent_version,
        ])

    def test_telemetry_module_importable(self):
        """Shared telemetry module must be importable."""
        from agents.shared.telemetry import get_tracer, setup_foundry_tracing

        assert setup_foundry_tracing
        assert get_tracer

    def test_register_agents_script_importable(self):
        """Registration script must be importable."""
        from scripts.register_agents import register_all_agents

        assert register_all_agents

    def test_dispatch_to_orchestrator_importable(self):
        """Responses API dispatch function must be importable."""
        from services.api_gateway.foundry import dispatch_to_orchestrator

        assert dispatch_to_orchestrator

    def test_build_incident_message_importable(self):
        """Incident message builder must be importable."""
        from services.api_gateway.foundry import build_incident_message

        assert build_incident_message

    def test_backward_compat_create_foundry_thread_importable(self):
        """Backward-compat alias must be importable."""
        from services.api_gateway.foundry import create_foundry_thread

        assert create_foundry_thread

    def test_backward_compat_get_foundry_client_importable(self):
        """Backward-compat AgentsClient factory must be importable."""
        from services.api_gateway.foundry import _get_foundry_client

        assert _get_foundry_client

    def test_all_domain_agents_have_consistent_registration_pattern(self):
        """Each domain agent create_version calls project.agents.create_version
        with the expected agent_name pattern 'aap-{domain}-agent'."""
        agent_imports = {
            "aap-compute-agent": "agents.compute.agent",
            "aap-arc-agent": "agents.arc.agent",
            "aap-eol-agent": "agents.eol.agent",
            "aap-network-agent": "agents.network.agent",
            "aap-patch-agent": "agents.patch.agent",
            "aap-security-agent": "agents.security.agent",
            "aap-sre-agent": "agents.sre.agent",
            "aap-storage-agent": "agents.storage.agent",
        }

        import importlib

        for expected_name, module_path in agent_imports.items():
            mod = importlib.import_module(module_path)
            domain = expected_name.replace("aap-", "").replace("-agent", "")
            fn_name = f"create_{domain}_agent_version"
            fn = getattr(mod, fn_name)

            mock_project = MagicMock()
            mock_project.agents.create_version.return_value = MagicMock()

            fn(mock_project)

            call_kwargs = mock_project.agents.create_version.call_args
            actual_name = call_kwargs.kwargs.get("agent_name") or call_kwargs[0][0]
            assert actual_name == expected_name, (
                f"{fn_name} registered as '{actual_name}', expected '{expected_name}'"
            )

    def test_orchestrator_registers_8_a2a_connections(self):
        """Orchestrator create_version must fetch 8 A2A connections."""
        from agents.orchestrator.agent import create_orchestrator_agent_version

        mock_project = MagicMock()
        mock_project.agents.create_version.return_value = MagicMock()
        mock_project.connections.get.return_value = MagicMock(id="conn-test")

        create_orchestrator_agent_version(mock_project)

        assert mock_project.connections.get.call_count == 8

        # Verify all expected connection names
        connection_names = [
            call.args[0] for call in mock_project.connections.get.call_args_list
        ]
        for domain in ["compute", "patch", "network", "security", "arc", "sre", "eol", "storage"]:
            assert f"aap-{domain}-agent-connection" in connection_names
