# SRE Agent

Cross-domain site reliability generalist and catch-all fallback agent. Handles availability monitoring, SLA/SLO tracking, perf baseline analysis, change analysis, and Azure Advisor recommendations. Receives incidents when domain classification is ambiguous or when cross-domain correlation is needed across multiple specialist domains.

## Responsibilities
- Query Application Insights for availability and performance baselines
- Retrieve Azure Service Health events and planned maintenance notifications
- Run Azure Change Analysis to surface infrastructure changes correlated with incidents
- Fetch Azure Advisor recommendations across reliability, performance, and cost pillars
- Correlate signals across domains when a single specialist is insufficient
- Produce root-cause hypotheses with confidence scores (0.0–1.0) (TRIAGE-004); act as catch-all when no other domain matches

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist (`monitor`, `applicationinsights`, `advisor`, `resourcehealth`, `containerapps`), and Foundry registration
- `tools.py` — `@ai_function` tools: Log Analytics query, availability metrics, service health, Advisor recommendations, change analysis, cross-domain correlation helper, HITL remediation proposal
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-monitor`, `azure-monitor-query`, `azure-mgmt-resourcehealth`, `azure-mgmt-advisor`, `azure-mgmt-changeanalysis`)
- `Dockerfile` — container image built from `Dockerfile.base`
