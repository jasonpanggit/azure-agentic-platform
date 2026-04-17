# FinOps Agent

Domain specialist for Azure cost management and cloud financial operations. Surfaces subscription cost breakdowns, per-resource cost analysis, idle resource detection, reserved instance utilisation, and budget forecasting. Proposes VM deallocations and right-sizing changes exclusively through the HITL approval flow — never executes them directly.

## Responsibilities
- Break down subscription costs by resource group, resource type, or service name (FINOPS-001)
- Detect idle VMs (low CPU + network) and generate HITL deallocation proposals with estimated monthly savings (FINOPS-002)
- Forecast current-month spend vs. budget and flag burn rates above 110% (FINOPS-003)
- Report reserved instance and savings plan utilisation
- Rank top cost drivers across a subscription
- Produce diagnoses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist (`monitor`, `advisor`), and Foundry registration
- `tools.py` — `@ai_function` tools: subscription cost breakdown, resource cost query, idle VM detection, RI utilisation, cost forecast, top cost drivers
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-costmanagement`, `azure-mgmt-monitor`, `azure-mgmt-compute`)
- `Dockerfile` — container image built from `Dockerfile.base`
