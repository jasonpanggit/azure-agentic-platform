"""Tests for foundry.py — Responses API dispatch (Phase 29 migration from threads/runs)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("AZURE_PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/test")
os.environ.setdefault("ORCHESTRATOR_AGENT_NAME", "aap-orchestrator")


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


class TestDispatchToOrchestrator:
    """Verify dispatch_to_orchestrator uses Responses API (not threads/runs)."""

    @patch("services.api_gateway.foundry._get_openai_client")
    @pytest.mark.asyncio
    async def test_calls_responses_create(self, mock_get_client):
        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_123"
        mock_response.status = "completed"
        mock_openai.responses.create.return_value = mock_response
        mock_get_client.return_value = mock_openai

        from services.api_gateway.foundry import dispatch_to_orchestrator

        payload = _make_incident_payload()
        result = await dispatch_to_orchestrator(payload)

        mock_openai.responses.create.assert_called_once()
        call_kwargs = mock_openai.responses.create.call_args
        # Should pass agent_reference in extra_body
        extra_body = call_kwargs.kwargs.get("extra_body", {})
        assert "agent_reference" in extra_body

    @patch("services.api_gateway.foundry._get_openai_client")
    @pytest.mark.asyncio
    async def test_returns_response_id(self, mock_get_client):
        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_456"
        mock_response.status = "completed"
        mock_openai.responses.create.return_value = mock_response
        mock_get_client.return_value = mock_openai

        from services.api_gateway.foundry import dispatch_to_orchestrator

        payload = _make_incident_payload()
        result = await dispatch_to_orchestrator(payload)
        assert "response_id" in result
        assert result["response_id"] == "resp_456"

    @patch("services.api_gateway.foundry._get_openai_client")
    @pytest.mark.asyncio
    async def test_agent_reference_uses_env_var_name(self, mock_get_client):
        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_789"
        mock_response.status = "completed"
        mock_openai.responses.create.return_value = mock_response
        mock_get_client.return_value = mock_openai

        from services.api_gateway.foundry import dispatch_to_orchestrator

        payload = _make_incident_payload()
        await dispatch_to_orchestrator(payload)

        call_kwargs = mock_openai.responses.create.call_args
        extra_body = call_kwargs.kwargs.get("extra_body", {})
        agent_ref = extra_body["agent_reference"]
        assert agent_ref["name"] == "aap-orchestrator"
        assert agent_ref["type"] == "agent_reference"


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

    @patch("services.api_gateway.foundry._get_openai_client")
    @pytest.mark.asyncio
    async def test_create_foundry_thread_maps_to_response_id(self, mock_get_client):
        mock_openai = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_compat"
        mock_response.status = "completed"
        mock_openai.responses.create.return_value = mock_response
        mock_get_client.return_value = mock_openai

        from services.api_gateway.foundry import create_foundry_thread

        payload = _make_incident_payload()
        result = await create_foundry_thread(payload)

        assert result["thread_id"] == "resp_compat"
        assert result["response_id"] == "resp_compat"
