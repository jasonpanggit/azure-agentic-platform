# Arc Agent

Domain specialist for Azure Arc-enabled resources. Fills the Azure MCP Server's Arc coverage gap by mounting the custom Arc MCP Server (`ca-arc-mcp-prod`) to access Arc-enabled servers (`HybridCompute`), Arc Kubernetes (`ConnectedClusters`), and Arc data services (SQL Managed Instance, PostgreSQL). Never executes remediation without explicit human approval.

## Responsibilities
- List and inspect Arc-enabled servers, connectivity status, and extension health
- Enumerate Arc Kubernetes clusters, GitOps configurations, and applied policies
- Check Arc data services: SQL Managed Instance and PostgreSQL instances
- Query Activity Log (prior 2h) and Resource Health as mandatory pre-triage steps (TRIAGE-002, TRIAGE-003)
- Assess guest configuration / Azure Policy compliance for Arc servers
- Produce root-cause hypotheses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, `MCPTool` mount for Arc MCP Server (`ARC_MCP_SERVER_URL`), and Foundry registration
- `tools.py` — `@ai_function` tools: Activity Log wrapper, Log Analytics query, Resource Health check, guest configuration compliance; Arc-specific tools (server/K8s/extension/GitOps) are provided by the Arc MCP Server
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-hybridcompute`, `azure-mgmt-guestconfiguration`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
