# Storage Agent

Domain specialist for Azure storage resources. Diagnoses issues across Blob Storage, Azure Files, Tables, Queues, ADLS Gen2, and managed disks by correlating Azure Monitor metrics (throttle events, error codes, latency), Activity Log, and Resource Health. Never executes remediation without explicit human approval.

## Responsibilities
- Query storage account metrics: transactions, availability, end-to-end latency, throttled requests, capacity
- Inspect Activity Log (prior 2h) as the first RCA step (TRIAGE-003)
- Check Resource Health status before producing a diagnosis (TRIAGE-002)
- Correlate access-tier transition events and soft-delete/versioning configuration
- Produce root-cause hypotheses with confidence scores (0.0–1.0) (TRIAGE-004)
- Propose (but never execute) storage-tier or configuration changes; gated by HITL approval (REMEDI-001)

## Key Files
- `agent.py` — `ChatAgent` definition, system prompt, MCP tool allowlist (`storage`, `fileshares`, `monitor`, `resourcehealth`), and Foundry registration
- `tools.py` — `@ai_function` tools: storage metrics query, Activity Log wrapper, Resource Health check, file share enumeration
- `requirements.txt` — agent-specific dependencies (`azure-mgmt-storage`, `azure-mgmt-monitor`, `azure-monitor-query`)
- `Dockerfile` — container image built from `Dockerfile.base`
