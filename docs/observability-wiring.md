# Observability Wiring Audit

> Generated: 2026-04-02 | Quick task 260402-fvo

This document tracks the OpenTelemetry (OTel) auto-instrumentation status for every deployable container in the Azure Agentic Platform.

## Container Wiring Status

| # | Container | Runtime | OTel SDK | Init Call | Terraform Env Var | Status |
|---|-----------|---------|----------|-----------|-------------------|--------|
| 1 | orchestrator | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-orchestrator-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 2 | compute | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-compute-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 3 | network | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-network-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 4 | storage | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-storage-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 5 | security | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-security-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 6 | arc | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-arc-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 7 | sre | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-sre-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 8 | patch | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-patch-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 9 | eol | Python | `agents/shared/otel.py` | `setup_telemetry("aiops-eol-agent")` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 10 | api-gateway | Python | `azure-monitor-opentelemetry` | `configure_azure_monitor()` in `main.py` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module) | Wired |
| 11 | teams-bot | TypeScript | `@azure/monitor-opentelemetry` | `useAzureMonitor()` in `src/instrumentation.ts` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (agent-apps module, teams_bot resource) | Wired |
| 12 | arc-mcp-server | Python | `azure-monitor-opentelemetry` | `configure_azure_monitor()` in `__main__.py` | `APPLICATIONINSIGHTS_CONNECTION_STRING` (arc-mcp-server module) | Wired |

## Excluded

| Component | Reason |
|-----------|--------|
| web-ui (Next.js) | Client-side rendering; structured logging added (260401-o1l) but OTel browser SDK is a different pattern. Receives env var from Terraform but does not initialize server-side OTel. |
| Detection Plane (Fabric UDF) | Serverless Fabric execution; no container, no OTel SDK support. |

## Patterns

### Python Agents (1-9): Shared `setup_telemetry()`

All 9 domain agents use the same shared module (`agents/shared/otel.py`):

```python
from shared.otel import setup_telemetry
tracer = setup_telemetry("aiops-{agent}-agent")
```

This calls `configure_azure_monitor()` when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set and returns a `Tracer` for custom spans.

### Python Services (10, 12): Direct `configure_azure_monitor()`

The API Gateway and Arc MCP Server call `configure_azure_monitor()` directly at module level before their ASGI server starts. Both guard with an `if` check on the env var to allow graceful degradation in local dev.

### TypeScript Service (11): `useAzureMonitor()`

The Teams Bot uses `@azure/monitor-opentelemetry` and calls `useAzureMonitor()` as the first import in `index.ts` (via `src/instrumentation.ts`).

## Terraform Source

| Terraform Module | Containers | Env Var Delivery |
|------------------|------------|------------------|
| `terraform/modules/agent-apps/main.tf` (agents resource, line 78) | orchestrator, compute, network, storage, security, arc, sre, patch, eol, api-gateway, web-ui | Secret reference: `appinsights-connection-string` |
| `terraform/modules/agent-apps/main.tf` (teams_bot resource, line 339) | teams-bot | Secret reference: `appinsights-connection-string` |
| `terraform/modules/arc-mcp-server/main.tf` (line 65) | arc-mcp-server | Secret reference: `appinsights-connection-string` |
