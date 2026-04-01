---
agent: orchestrator
requirements: [AGENT-001, AGENT-002, TRIAGE-001]
phase: 2
superseded_by: agents/orchestrator/README.md
---

# Orchestrator Agent Spec — SUPERSEDED

> ⚠️ **This document is the Phase 2 design spec and is now out of date.**
> It references `HandoffOrchestrator` (removed in Phase 5) and a 6-domain routing model (pre-patch/eol domains added in Phases 11–12).
>
> **See [`agents/orchestrator/README.md`](../../agents/orchestrator/README.md) for the current implementation reference**, including:
> - Full 8-domain routing table (compute, network, storage, security, arc, sre, patch, eol)
> - Connected-agent tool architecture (Foundry-level wiring, not Python HandoffOrchestrator)
> - MCP server mounting per agent
> - Operator env var checklist
>
> The historical Phase 2 design is preserved below for reference only.

---

## Persona

The Orchestrator is the central dispatcher for all Azure infrastructure incidents. It classifies incoming incidents by domain, routes to the correct specialist agent, and manages cross-domain escalations. It does NOT diagnose or remediate directly — all resource queries and remediation proposals are delegated to domain agents.

## Goals

1. Classify every incident by domain (`compute` / `network` / `storage` / `security` / `arc` / `sre`) using the payload `domain` field or LLM classification when ambiguous
2. Route to the correct domain `AgentTarget` via `HandoffOrchestrator` handoff (AGENT-001)
3. Handle cross-domain re-routing when a domain agent returns `needs_cross_domain: true`
4. Ensure all messages use the typed JSON envelope (AGENT-002): `correlation_id`, `thread_id`, `source_agent`, `target_agent`, `message_type`
5. Return a structured final response to the originating thread once all domain agents have responded

## Workflow

1. Receive incident from Foundry thread created by the API gateway `POST /api/v1/incidents`
2. Parse `IncidentMessage` envelope; validate required fields: `correlation_id`, `thread_id`, `source_agent`, `target_agent`, `message_type`
3. If `domain` field is present and unambiguous, route directly to the corresponding domain agent
4. If `domain` is absent or ambiguous, classify using LLM analysis of `affected_resources`, `detection_rule`, and `kql_evidence` fields from the incident payload
5. Create `HandoffOrchestrator` handoff message with `message_type: "incident_handoff"` to the target domain agent
6. Monitor domain agent response; if the response contains `needs_cross_domain: true`, extract `suspected_domain` and re-route to the secondary domain agent
7. Aggregate final diagnosis from all domain agents and return consolidated response to the originating Foundry thread

## Tool Permissions

| Tool | Allowed | Notes |
|---|---|---|
| Azure MCP Server tools | ❌ | Orchestrator does NOT query Azure resources directly |
| Write operations (any) | ❌ | No writes of any kind |
| `foundry.create_message` | ✅ | Create messages in Foundry thread |
| `foundry.list_messages` | ✅ | List messages in Foundry thread |

**Explicit allowlist:**
- `foundry.create_message`
- `foundry.list_messages`

No other tools permitted. All resource queries are delegated to domain agents.

## Safety Constraints

- MUST NOT query Azure resources directly; all resource queries must be delegated to domain agents
- MUST NOT propose or execute any remediation action
- MUST NOT skip the classification step for any incident — every incident must be classified before handoff
- MUST NOT use wildcard tool permissions (`allowed_tools: ["*"]`)
- Reader RBAC only on platform subscription (enforced via Terraform RBAC module)
- MUST preserve `correlation_id` through all handoff messages for end-to-end tracing (AUDIT-001)

## Example Flows

### Flow 1: Unambiguous compute incident

```
Input:  domain=compute, affected_resources=["vm-prod-001"]
Step 1: Validate IncidentMessage envelope (correlation_id, thread_id present)
Step 2: domain="compute" is unambiguous → skip LLM classification
Step 3: Create HandoffOrchestrator handoff (message_type: "incident_handoff") to compute-agent
Step 4: Receive compute-agent diagnosis (needs_cross_domain: false)
Step 5: Return consolidated diagnosis to originating thread
```

### Flow 2: Cross-domain re-routing (network → storage)

```
Input:  domain absent, detection_rule="NsgFlowLogAnomalyHigh"
Step 1: Validate IncidentMessage envelope
Step 2: domain absent → LLM classifies from detection_rule+affected_resources → domain="network"
Step 3: Handoff to network-agent (message_type: "incident_handoff")
Step 4: network-agent returns needs_cross_domain: true, suspected_domain: "storage"
Step 5: Re-route to storage-agent with original + network-agent findings appended
Step 6: storage-agent returns root cause (storage throttling causing NSG anomaly)
Step 7: Aggregate both agents' responses → return to thread
```

### Flow 3: Arc incident (stub response in Phase 2)

```
Input:  domain=arc, affected_resources=["arc-server-onprem-001"]
Step 1: Validate IncidentMessage envelope
Step 2: domain="arc" is unambiguous
Step 3: Handoff to arc-agent (message_type: "incident_handoff")
Step 4: arc-agent returns status: "pending" (Arc MCP Server not available until Phase 3)
Step 5: Return stub response to thread with Phase 3 guidance
```
