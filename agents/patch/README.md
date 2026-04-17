# Patch Agent

Domain specialist for Azure patch management. Queries Azure Update Manager (AUM) patch assessment and installation history across Azure VMs and Arc-enabled servers via Azure Resource Graph (`PatchAssessmentResources`, `PatchInstallationResources`), maps KB articles to CVEs via the MSRC CVRF API, and proposes remediation — never executes it — with HITL approval.

## Responsibilities
- Assess patch compliance: missing critical/security patches by VM or subscription
- Retrieve patch installation history and reboot-pending state
- Map KB article IDs to CVE identifiers via the MSRC CVRF API
- Query `ConfigurationData` in Log Analytics for software inventory
- Check Activity Log (prior 2h) and Resource Health as pre-triage steps (TRIAGE-002, TRIAGE-003)
- Cite top-3 relevant runbooks via `search_runbooks(domain="patch")` (TRIAGE-005)
- Produce diagnoses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, `MCPTool` mount for Azure MCP Server (`AZURE_MCP_SERVER_URL`), and Foundry registration
- `tools.py` — `@ai_function` tools: ARG patch assessment, installation history, KB-to-CVE mapping, ConfigurationData query, Activity Log wrapper, Resource Health check, runbook search wrapper
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-resourcegraph`, `azure-mgmt-monitor`, `azure-monitor-query`, `httpx`)
- `Dockerfile` — container image built from `Dockerfile.base`
