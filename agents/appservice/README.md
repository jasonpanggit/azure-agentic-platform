# App Service Agent

Domain specialist for Azure App Service and Azure Functions workloads. Surfaces health, performance, and execution diagnostics for Web Apps and App Service Plans, correlating Azure Monitor metrics with diagnostic logs before proposing any HITL-gated restart or scale actions.

## Responsibilities
- List and inspect Web Apps, App Service Plans, and Function Apps
- Query Azure Monitor metrics: HTTP requests, response times, CPU/memory, connection counts
- Retrieve diagnostic logs (application, HTTP access, deployment) from Log Analytics
- Detect unhealthy instances within an App Service Plan and correlate with deployment events
- Propose (but never execute) restarts, slot swaps, or scale-out changes; gated by HITL approval (REMEDI-001)
- Produce diagnoses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist, and Foundry registration
- `tools.py` — `@ai_function` tools: site list/get, App Service Plan list/get, metrics query, log query, restart proposal
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-web`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
