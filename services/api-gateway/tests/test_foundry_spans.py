"""Tests for incident-run span attributes in foundry.py dispatch (Phase 29)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("AZURE_PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/test")
os.environ.setdefault("ORCHESTRATOR_AGENT_NAME", "aap-orchestrator")
os.environ.setdefault("ORCHESTRATOR_AGENT_ID", "agent-test-id")


def _make_incident_payload():
    """Create a valid IncidentPayload for testing."""
    from services.api_gateway.models import AffectedResource, IncidentPayload

    return IncidentPayload(
        incident_id="inc-span-001",
        severity="Sev1",
        domain="compute",
        affected_resources=[
            AffectedResource(
                resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                subscription_id="sub",
                resource_type="Microsoft.Compute/virtualMachines",
            )
        ],
        detection_rule="HighCPUAlert",
        title="CPU High",
    )


class TestIncidentRunSpanAttributes:
    """Verify dispatch_to_orchestrator sets incident.* and agent.* span attributes.

    Uses a single TracerProvider setup because OTel only allows
    set_tracer_provider() once per process.
    """

    @patch("services.api_gateway.foundry._get_agents_client")
    @patch("services.api_gateway.foundry._get_foundry_project")
    @pytest.mark.asyncio
    async def test_dispatch_records_incident_and_agent_spans(self, mock_get_project, mock_get_agents):
        """Verify both foundry.agents_create_thread_and_run and agent.orchestrator spans
        carry the correct incident and agent attributes."""
        mock_agents = MagicMock()
        mock_run = MagicMock()
        mock_run.thread_id = "thread-span-test"
        mock_run.id = "run-span-test"
        mock_run.status = "completed"
        mock_agents.create_thread_and_run.return_value = mock_run
        mock_get_agents.return_value = mock_agents
        mock_get_project.return_value = MagicMock()

        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        original_provider = otel_trace.get_tracer_provider()
        otel_trace.set_tracer_provider(provider)

        try:
            from services.api_gateway.foundry import dispatch_to_orchestrator

            payload = _make_incident_payload()
            await dispatch_to_orchestrator(payload)

            provider.force_flush()

            spans = exporter.get_finished_spans()
            span_names = [s.name for s in spans]

            # --- foundry.agents_create_thread_and_run span ---
            assert any("agents_create_thread_and_run" in name for name in span_names), (
                f"Expected 'agents_create_thread_and_run' span, got: {span_names}"
            )

            for span in spans:
                if "agents_create_thread_and_run" in span.name:
                    attrs = dict(span.attributes or {})
                    assert attrs.get("incident.id") == "inc-span-001"
                    assert attrs.get("incident.domain") == "compute"
                    break

            # --- agent.orchestrator span ---
            agent_spans = [s for s in spans if "agent.orchestrator" in s.name]
            assert len(agent_spans) >= 1, (
                f"Expected agent.orchestrator span, got: {span_names}"
            )

            agent_attrs = dict(agent_spans[0].attributes or {})
            assert agent_attrs.get("agent.name") == "orchestrator"
            assert agent_attrs.get("agent.domain") == "compute"
            assert agent_attrs.get("agent.correlation_id") == "inc-span-001"
        finally:
            otel_trace.set_tracer_provider(original_provider)

    def test_foundry_module_has_dispatch_function(self):
        """Smoke test: dispatch_to_orchestrator is importable and callable."""
        from services.api_gateway.foundry import dispatch_to_orchestrator

        assert callable(dispatch_to_orchestrator)

    def test_foundry_module_has_build_incident_message(self):
        """Smoke test: build_incident_message is importable and callable."""
        from services.api_gateway.foundry import build_incident_message

        assert callable(build_incident_message)
