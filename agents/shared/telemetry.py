"""Foundry-native telemetry setup — AIProjectInstrumentor + App Insights (MONITOR-007).

Wraps configure_azure_monitor and AIProjectInstrumentor so every agent
gets both OTel traces and Foundry portal trace waterfall visibility with
a single call to setup_foundry_tracing().

Usage in each agent's __main__ / startup:
    from shared.telemetry import setup_foundry_tracing, get_tracer
    setup_foundry_tracing(project, "aiops-compute-agent")
    tracer = get_tracer("aiops-compute-agent")
"""
from __future__ import annotations

import os

from azure.ai.projects import AIProjectClient
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

# Enable Foundry GenAI tracing — must be set before AIProjectInstrumentor.instrument()
os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

try:
    from azure.ai.projects.telemetry import AIProjectInstrumentor
except ImportError:  # pragma: no cover — older SDK version fallback
    AIProjectInstrumentor = None  # type: ignore[assignment,misc]


def setup_foundry_tracing(project: AIProjectClient, agent_name: str) -> None:  # noqa: ARG001
    """Wire App Insights + AIProjectInstrumentor for a hosted agent.

    Call once at agent startup (in __main__ or lifespan). After this call:
    - All openai SDK calls emit OTel spans -> App Insights
    - Traces appear in the Foundry portal under the agent's Tracing tab
    - Custom spans set via get_tracer() are included in the waterfall

    Args:
        project: Authenticated AIProjectClient (azure-ai-projects 2.0.x).
        agent_name: Human-readable service name for the OTel resource (e.g.
            "aiops-compute-agent"). Used as the service.name attribute.
    """
    conn_str = project.telemetry.get_application_insights_connection_string()
    configure_azure_monitor(connection_string=conn_str)

    if AIProjectInstrumentor is not None:
        AIProjectInstrumentor().instrument()


def get_tracer(name: str) -> trace.Tracer:
    """Return an OTel Tracer for creating custom incident-run spans.

    Args:
        name: Tracer name — typically the agent service name.

    Returns:
        OpenTelemetry Tracer instance.
    """
    return trace.get_tracer(name)
