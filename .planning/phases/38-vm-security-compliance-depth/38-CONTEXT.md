# Phase 38: VM Security & Compliance Depth - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning
**Mode:** Auto-generated (smart discuss — infrastructure/backend phase)

<domain>
## Phase Boundary

Phase 38 makes per-VM security posture a first-class diagnostic signal in the compute agent. Five new `@ai_function` tools + agent registration + unit tests.

Deliverables:
1. **`query_defender_tvm_cve_count`** — Defender Threat & Vulnerability Management: count of CVEs by severity for a VM, using Azure Resource Graph ARG (`SecurityResources` table, `microsoft.security/assessments`).
2. **`query_jit_access_status`** — JIT access policy status + active sessions for a VM. Uses `microsoft.security/locations/jitNetworkAccessPolicies` REST API via `azure-mgmt-security`.
3. **`query_effective_nsg_rules`** — Effective NSG rules at NIC level via `azure-mgmt-network` `effective_network_security_rules`. Returns allow/deny rules with priority, direction, port ranges.
4. **`query_backup_rpo`** — Azure Backup last backup time + RPO status for the VM. Uses `azure-mgmt-recoveryservices` and `azure-mgmt-recoveryservicesbackup`.
5. **`query_asr_replication_health`** — Azure Site Recovery replication health for the VM. Uses `azure-mgmt-recoveryservicessiterecovery`.
6. **Agent registration** — Register all 5 tools in `agents/compute/agent.py` (4 locations).
7. **Unit tests** — 20+ tests across 5 classes.

Out of scope: UI compliance score panel (Phase 41), actual remediation actions.

</domain>

<decisions>
## Implementation Decisions

### Defender TVM CVE Count
- Use Azure Resource Graph (`azure-mgmt-resourcegraph`, `ResourceGraphClient.resources()`)
- Query `SecurityResources` table where `type == "microsoft.security/assessments"` and filter by VM resource ID
- Count CVEs grouped by severity: Critical, High, Medium, Low
- Tool name: `query_defender_tvm_cve_count(resource_group, vm_name, subscription_id, thread_id)`
- Return: `{critical: N, high: N, medium: N, low: N, total: N, vm_risk_score: float}`

### JIT Access Status
- Use `azure-mgmt-security` `JitNetworkAccessPoliciesOperations`
- Check if JIT policy exists for VM's resource group; parse VM-specific rules
- Tool name: `query_jit_access_status(resource_group, vm_name, subscription_id, thread_id)`
- Return: `{jit_enabled: bool, active_sessions: list, allowed_ports: list}`

### Effective NSG Rules
- Use `azure-mgmt-network` `network_interfaces.list_effective_network_security_groups()`
- Get VM's NIC ID first via `compute_client.virtual_machines.get()`, then call NSG effective rules
- Tool name: `query_effective_nsg_rules(resource_group, vm_name, subscription_id, thread_id)`
- Return: `{effective_rules: list[{name, direction, access, priority, protocol, port_range}], inbound_deny_count: int, outbound_deny_count: int}`

### Backup RPO
- Use `azure-mgmt-recoveryservicesbackup` to list protected items for the VM
- Find vault by querying ARG for `microsoft.recoveryservices/vaults` in the subscription
- Tool name: `query_backup_rpo(resource_group, vm_name, subscription_id, thread_id)`
- Return: `{backup_enabled: bool, vault_name: str, last_backup_time: str, last_backup_status: str, rpo_minutes: int}`
- If no vault/backup configured: return `{backup_enabled: false, ...}`

### ASR Replication Health
- Use `azure-mgmt-recoveryservicessiterecovery` `ReplicationProtectedItemsOperations`
- Find ASR vault (separate from backup vault) via ARG
- Tool name: `query_asr_replication_health(resource_group, vm_name, subscription_id, thread_id)`
- Return: `{asr_enabled: bool, replication_health: str, failover_readiness: str, rpo_seconds: int}`
- If not configured: return `{asr_enabled: false, replication_health: "not_configured"}`

### Claude's Discretion
- Exact ARG KQL for CVE count (SecurityResources schema details)
- How to handle VMs not in any backup vault (graceful not-configured response)
- SDK package names for recoveryservices vs recoveryservicesbackup vs siterecovery

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/compute/tools.py` — 28 existing tools; established lazy-import pattern, instrument_tool_call, _extract_subscription_id helper
- `agents/security/tools.py` — has `query_defender_alerts` using `azure-mgmt-security`; can reference its SDK import patterns
- `agents/tests/compute/test_compute_guest_diagnostics.py` — test pattern to follow exactly

### Established Patterns
- Module-level lazy imports with `try/except ImportError: XxxClient = None`
- `start_time = time.monotonic()` → `instrument_tool_call` → `try/except` → never raise
- Return structured error dict on any failure

### Integration Points
- `agents/compute/agent.py` — 4 locations (import, system prompt, ChatAgent, PromptAgentDefinition)
- `agents/tests/compute/` — new test file `test_compute_security.py`

</code_context>

<specifics>
## Specific Ideas

- `query_defender_tvm_cve_count` should include `vm_risk_score` (weighted: critical×10 + high×5 + medium×2 + low×1) for easy LLM comparison
- `query_effective_nsg_rules` should highlight any rules with `priority < 200` as "high-priority rules" since those often indicate manual overrides
- All tools must handle VMs not configured for a feature (JIT, backup, ASR) gracefully — return structured "not configured" response, not error

</specifics>

<deferred>
## Deferred Ideas

- VM compliance score panel in UI (Phase 41)
- Actual JIT request/approve action (HITL workflow — future phase)
- Defender recommendation remediation actions
- ASR failover test trigger

</deferred>
