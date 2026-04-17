# Compute Agent

Domain specialist for Azure compute resources. Receives handoffs from the Orchestrator and diagnoses issues across VMs, VMSS, AKS node pools, App Service, and Azure Functions using Activity Log, Log Analytics, Resource Health, Azure Monitor metrics, and Azure Resource Graph OS inventory. Never executes remediation without explicit human approval.

## Responsibilities
- Query Activity Log (prior 2h) as the first RCA step (TRIAGE-003)
- Correlate Log Analytics workspace data and Resource Health events (TRIAGE-002)
- Retrieve Azure Monitor metrics (CPU, disk I/O, network) for VMs and VMSS
- Inventory OS versions across subscriptions via Azure Resource Graph
- Produce root-cause hypotheses with confidence scores (0.0–1.0) (TRIAGE-004)
- Propose (but never execute) remediations; all actions gated by HITL approval (REMEDI-001)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist, and Foundry registration
- `tools.py` — `@ai_function` tools: Activity Log query, Log Analytics query, Resource Health check, Monitor metrics, ARG OS inventory
- `requirements.txt` — agent-specific Python dependencies (`azure-mgmt-compute`, `azure-mgmt-monitor`, `azure-monitor-query`, `azure-mgmt-resourcegraph`)
- `Dockerfile` — container image built from `Dockerfile.base`
