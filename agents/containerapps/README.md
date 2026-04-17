# Container Apps Agent

Domain specialist for Azure Container Apps workloads, including the platform's own internal agents. Surfaces health, performance, log analysis, and revision history, and proposes HITL-gated scale or traffic-split changes — never executing them directly.

## Responsibilities
- List and inspect Container Apps, environments, and revisions
- Query Azure Monitor metrics: CPU, memory, request count, replica count
- Retrieve application logs and system logs from Log Analytics
- Detect traffic-split misconfigurations and failed revisions
- Propose (but never execute) scale rules, min/max replica changes, or revision rollbacks; gated by HITL approval (REMEDI-001)
- Produce diagnoses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist, and Foundry registration
- `tools.py` — `@ai_function` tools: Container App list/get, revision list/get, metrics query, log query, scale proposal
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-appcontainers`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
