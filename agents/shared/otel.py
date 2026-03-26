"""OpenTelemetry instrumentation for AAP agents (MONITOR-007, AUDIT-001, AUDIT-005)."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any, Generator

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace


def setup_telemetry(service_name: str) -> trace.Tracer:
    """Configure OpenTelemetry for an agent container.

    Reads APPLICATIONINSIGHTS_CONNECTION_STRING from environment.
    Returns a Tracer instance for creating custom spans.

    Args:
        service_name: Agent service name (e.g., "aiops-compute-agent").

    Returns:
        An OpenTelemetry Tracer for the given service.
    """
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if connection_string:
        configure_azure_monitor(
            connection_string=connection_string,
        )

    return trace.get_tracer(service_name)


def record_tool_call_span(
    agent_id: str,
    agent_name: str,
    tool_name: str,
    tool_parameters: dict[str, Any],
    outcome: str,
    duration_ms: int,
    correlation_id: str,
    thread_id: str,
) -> None:
    """Record a completed tool call as an OpenTelemetry span with all AUDIT-001 fields.

    This function creates a span after the tool call has completed, recording
    all required audit fields as span attributes.

    Args:
        agent_id: Entra Agent ID object ID (AUDIT-005 — must NOT be "system").
        agent_name: Human-readable agent name (e.g., "compute-agent").
        tool_name: MCP tool or @ai_function name invoked.
        tool_parameters: Serialized tool input arguments.
        outcome: Result status — "success", "failure", or "timeout".
        duration_ms: Wall-clock duration of the tool call in milliseconds.
        correlation_id: Incident correlation ID from message envelope.
        thread_id: Foundry thread ID for this conversation.
    """
    tracer = trace.get_tracer("aiops.tool_calls")
    with tracer.start_as_current_span(
        name=f"{agent_name}.{tool_name}",
    ) as span:
        span.set_attribute("aiops.agent_id", agent_id)
        span.set_attribute("aiops.agent_name", agent_name)
        span.set_attribute("aiops.tool_name", tool_name)
        span.set_attribute("aiops.tool_parameters", str(tool_parameters))
        span.set_attribute("aiops.outcome", outcome)
        span.set_attribute("aiops.duration_ms", duration_ms)
        span.set_attribute("aiops.correlation_id", correlation_id)
        span.set_attribute("aiops.thread_id", thread_id)

        if outcome == "failure":
            span.set_status(trace.StatusCode.ERROR, "Tool call failed")
        elif outcome == "timeout":
            span.set_status(trace.StatusCode.ERROR, "Tool call timed out")


@contextmanager
def instrument_tool_call(
    tracer: trace.Tracer,
    agent_name: str,
    agent_id: str,
    tool_name: str,
    tool_parameters: dict[str, Any],
    correlation_id: str,
    thread_id: str,
) -> Generator[trace.Span, None, None]:
    """Context manager that wraps a tool call with an OpenTelemetry span.

    Automatically records duration, outcome (success/failure), and all
    AUDIT-001 required fields. Use this around tool call execution.

    Args:
        tracer: The OpenTelemetry Tracer from setup_telemetry().
        agent_name: Human-readable agent name.
        agent_id: Entra Agent ID object ID (AUDIT-005).
        tool_name: Tool being called.
        tool_parameters: Tool input arguments.
        correlation_id: Incident correlation ID.
        thread_id: Foundry thread ID.

    Yields:
        The active OpenTelemetry Span.
    """
    start_time = time.monotonic()
    with tracer.start_as_current_span(f"{agent_name}.{tool_name}") as span:
        span.set_attribute("aiops.agent_id", agent_id)
        span.set_attribute("aiops.agent_name", agent_name)
        span.set_attribute("aiops.tool_name", tool_name)
        span.set_attribute("aiops.tool_parameters", str(tool_parameters))
        span.set_attribute("aiops.correlation_id", correlation_id)
        span.set_attribute("aiops.thread_id", thread_id)
        try:
            yield span
            duration_ms = int((time.monotonic() - start_time) * 1000)
            span.set_attribute("aiops.outcome", "success")
            span.set_attribute("aiops.duration_ms", duration_ms)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            span.set_attribute("aiops.outcome", "failure")
            span.set_attribute("aiops.duration_ms", duration_ms)
            span.set_attribute("aiops.error", str(exc))
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise
