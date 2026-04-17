from __future__ import annotations
"""Manual OTel span helpers for AAP API Gateway (D-13, D-14).

Provides three context managers for domain-specific instrumentation
on top of the auto-instrumentation from azure-monitor-opentelemetry.

Span types:
  - foundry_span: Foundry API calls (create_thread, post_message, create_run, poll_response)
  - mcp_span: MCP tool call approvals
  - agent_span: Domain agent invocations

Span name pattern: `{type}.{name}` where type is foundry/mcp/agent and name
is the operation or agent name. For agent spans this produces `agent.{agent_name}`
(e.g. `agent.orchestrator`, `agent.compute`, `agent.network`) — NOT a fixed
`agent.invoke` string.

All spans are exported to Application Insights via the existing
configure_azure_monitor() setup in main.py. No new exporters needed.
"""

from contextlib import contextmanager
from time import time
from typing import Any, Generator

from opentelemetry import trace

tracer = trace.get_tracer("aap.api-gateway")


@contextmanager
def foundry_span(
    operation: str, **attributes: Any
) -> Generator[trace.Span, None, None]:
    """Context manager for Foundry API call spans.

    Usage:
        with foundry_span("create_thread", thread_id="t123") as span:
            thread = client.threads.create()
            span.set_attribute("foundry.thread_id", thread.id)

    Attributes automatically set:
        foundry.duration_ms — computed from span start/end
        foundry.{key} — for each kwarg in attributes
    """
    with tracer.start_as_current_span(f"foundry.{operation}") as span:
        start = time()
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f"foundry.{key}", str(value))
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise
        finally:
            span.set_attribute("foundry.duration_ms", int((time() - start) * 1000))


@contextmanager
def mcp_span(
    tool_name: str, server: str = "azure_mcp", **attributes: Any
) -> Generator[trace.Span, None, None]:
    """Context manager for MCP tool call spans.

    Usage:
        with mcp_span("compute.list_vms", server="azure_mcp") as span:
            client.runs.submit_tool_approval(...)
            span.set_attribute("mcp.outcome", "success")

    Attributes automatically set:
        mcp.tool_name, mcp.server, mcp.duration_ms, mcp.outcome
    """
    with tracer.start_as_current_span(f"mcp.{tool_name}") as span:
        start = time()
        span.set_attribute("mcp.tool_name", tool_name)
        span.set_attribute("mcp.server", server)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f"mcp.{key}", str(value))
        try:
            yield span
            span.set_attribute("mcp.outcome", "success")
        except Exception as exc:
            span.set_attribute("mcp.outcome", "error")
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise
        finally:
            span.set_attribute("mcp.duration_ms", int((time() - start) * 1000))


@contextmanager
def agent_span(
    agent_name: str, domain: str = "", correlation_id: str = ""
) -> Generator[trace.Span, None, None]:
    """Context manager for agent invocation spans.

    Span name is `agent.{agent_name}` (e.g. `agent.orchestrator`,
    `agent.compute`, `agent.network`). This pattern is intentional —
    each agent gets a distinct span name for filtering in App Insights.

    Usage:
        with agent_span("orchestrator", domain="compute", correlation_id="inc-123") as span:
            run = client.runs.create(thread_id=tid, agent_id=aid)
            span.set_attribute("agent.run_id", run.id)

    Attributes automatically set:
        agent.name, agent.domain, agent.correlation_id, agent.duration_ms
    """
    with tracer.start_as_current_span(f"agent.{agent_name}") as span:
        start = time()
        span.set_attribute("agent.name", agent_name)
        span.set_attribute("agent.domain", domain)
        span.set_attribute("agent.correlation_id", correlation_id)
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise
        finally:
            span.set_attribute("agent.duration_ms", int((time() - start) * 1000))
