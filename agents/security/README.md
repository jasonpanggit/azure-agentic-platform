# Security Agent

Domain specialist for Azure security posture. Surfaces Microsoft Defender for Cloud alerts, Key Vault access anomalies, RBAC drift, identity threats, and policy compliance posture. Always escalates credential-exposure findings immediately and never executes any remediation without explicit human approval.

## Responsibilities
- Retrieve and triage Defender for Cloud alerts by severity and resource
- Detect RBAC drift: new owner/contributor assignments in the Activity Log (prior 2h)
- Diagnose Key Vault access denial patterns and certificate expiry
- Query secure score trends and policy compliance states
- Scan for publicly exposed endpoints and storage accounts
- Produce root-cause hypotheses with confidence scores (0.0–1.0) (TRIAGE-004)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist (`keyvault`, `role`, `monitor`, `resourcehealth`, `advisor`), and Foundry registration
- `tools.py` — `@ai_function` tools: Defender alert list, Key Vault diagnostics, IAM change query, secure score, RBAC assignments, policy compliance, public-endpoint scan
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-security`, `azure-mgmt-monitor`, `azure-monitor-query`, `azure-mgmt-authorization`, `azure-mgmt-keyvault`)
- `Dockerfile` — container image built from `Dockerfile.base`
