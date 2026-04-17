from __future__ import annotations
"""Tests for foundry.py — AIProjectClient.agents dispatch (migrated from Responses API)."""
import os

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("AZURE_PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/test")
os.environ.setdefault("ORCHESTRATOR_AGENT_ID", "asst_test123")


def _make_incident_payload():
    """Create a valid IncidentPayload for testing."""
    from services.api_gateway.models import AffectedResource, IncidentPayload

    return IncidentPayload(
        incident_id="inc-001",
        severity="Sev1",
        domain="compute",
        affected_resources=[
            AffectedResource(
                resource_id="/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
                subscription_id="sub1",
                resource_type="Microsoft.Compute/virtualMachines",
            )
        ],
        detection_rule="HighCPUAlert",
        title="High CPU on vm1",
    )


def _make_mock_agents():
    """Build a mock AgentsClient with create_thread_and_run."""
    agents = MagicMock()
    run = MagicMock()
    run.id = "run_123"
    run.thread_id = "thread_456"
    run.status = "completed"
    agents.create_thread_and_run.return_value = run
    return agents, run


class TestDispatchToOrchestrator:
    """Verify dispatch_to_orchestrator uses azure-ai-agents AgentsClient (not Responses API)."""

    @patch("services.api_gateway.foundry._get_agents_client")
    @pytest.mark.asyncio
    async def test_calls_create_thread_and_run(self, mock_get_agents):
        agents, run = _make_mock_agents()
        mock_get_agents.return_value = agents

        from services.api_gateway.foundry import dispatch_to_orchestrator

        payload = _make_incident_payload()
        result = await dispatch_to_orchestrator(payload)

        agents.create_thread_and_run.assert_called_once()
        call_kwargs = agents.create_thread_and_run.call_args
        assert call_kwargs.kwargs["agent_id"] == "asst_test123"

    @patch("services.api_gateway.foundry._get_agents_client")
    @pytest.mark.asyncio
    async def test_returns_thread_and_run_ids(self, mock_get_agents):
        agents, run = _make_mock_agents()
        mock_get_agents.return_value = agents

        from services.api_gateway.foundry import dispatch_to_orchestrator

        payload = _make_incident_payload()
        result = await dispatch_to_orchestrator(payload)

        assert result["thread_id"] == "thread_456"
        assert result["run_id"] == "run_123"
        assert result["status"] == "completed"

    @patch("services.api_gateway.foundry._get_agents_client")
    @pytest.mark.asyncio
    async def test_agent_id_uses_env_var(self, mock_get_agents):
        agents, run = _make_mock_agents()
        mock_get_agents.return_value = agents

        with patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "asst_custom999"}):
            from services.api_gateway.foundry import dispatch_to_orchestrator
            payload = _make_incident_payload()
            await dispatch_to_orchestrator(payload)

        call_kwargs = agents.create_thread_and_run.call_args
        assert call_kwargs.kwargs["agent_id"] == "asst_custom999"


class TestBuildIncidentMessage:
    """Verify build_incident_message produces a valid envelope."""

    def test_builds_json_envelope_with_correlation_id(self):
        import json

        from services.api_gateway.foundry import build_incident_message

        payload = _make_incident_payload()
        msg = build_incident_message(payload)
        envelope = json.loads(msg)

        assert envelope["correlation_id"] == "inc-001"
        assert envelope["source_agent"] == "api-gateway"
        assert envelope["target_agent"] == "orchestrator"
        assert envelope["message_type"] == "incident_handoff"
        assert "timestamp" in envelope


class TestBackwardCompatAlias:
    """Verify create_foundry_thread backward-compat alias."""

    @patch("services.api_gateway.foundry._get_agents_client")
    @pytest.mark.asyncio
    async def test_create_foundry_thread_returns_thread_and_run(self, mock_get_agents):
        agents, run = _make_mock_agents()
        run.id = "run_compat"
        run.thread_id = "thread_compat"
        mock_get_agents.return_value = agents

        from services.api_gateway.foundry import create_foundry_thread

        payload = _make_incident_payload()
        result = await create_foundry_thread(payload)

        assert result["thread_id"] == "thread_compat"
        assert result["run_id"] == "run_compat"
