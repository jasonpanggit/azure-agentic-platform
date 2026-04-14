# Phase 49: Messaging Agent (Service Bus + Event Hub) - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure pattern — follows domain agent conventions)

<domain>
## Phase Boundary

Build a new `messaging` domain agent that covers Azure Service Bus and Azure Event Hubs.
Deploy as a new `ca-messaging-prod` Container App. Wire into orchestrator routing for
`microsoft.servicebus` and `microsoft.eventhub` resource types and `messaging` domain.

Tools to deliver:
- `get_servicebus_namespace_health` — namespace tier, status, geo-redundancy, messaging units
- `list_servicebus_queues` — queue count, message depth, DLQ count, active listeners, lock duration
- `get_servicebus_metrics` — incoming/outgoing messages, dead-letter count, server errors, throttled requests
- `propose_servicebus_dlq_purge` — HITL proposal to clear DLQ after operator confirmation
- `get_eventhub_namespace_health` — tier, throughput units, partition count, capture status
- `list_eventhub_consumer_groups` — lag per partition, last enqueued time, connected consumers
- `get_eventhub_metrics` — incoming events, bytes, outgoing events, throttled requests, user errors

Detection plane: extend KQL `classify_domain()` with `microsoft.servicebus` and `microsoft.eventhub` → `messaging`

</domain>

<decisions>
## Implementation Decisions

### Agent Structure
- Follow exact same pattern as `agents/appservice/`, `agents/containerapps/`, `agents/database/`
- Package: `agents/messaging/` with `__init__.py`, `tools.py`, `agent.py`, `requirements.txt`, `Dockerfile`
- Tests: `agents/tests/messaging/` with `test_messaging_tools.py`
- Lazy SDK imports with fallback `None` (same as every other agent)
- Tool functions: never-raise, `duration_ms` in both try/except, `start_time = time.monotonic()`

### SDK Choices
- Service Bus: `azure-mgmt-servicebus` (management plane for health/config) + `azure-monitor-query` (metrics)
- Event Hubs: `azure-mgmt-eventhub` (management plane) + `azure-monitor-query` (metrics/consumer lag)
- Credentials: `get_credential()` from `agents.shared.auth`
- Resource IDs: `_extract_subscription_id()` helper

### HITL Pattern
- `propose_servicebus_dlq_purge` follows HITL pattern: returns `approval_required=True`, `risk_level="low"`, `reversibility` message
- Other tools are read-only (no HITL)

### Orchestrator Wiring
- Add `"messaging"` → `"messaging_agent"` to `DOMAIN_AGENT_MAP`
- Add `"microsoft.servicebus"`, `"microsoft.eventhub"` to `RESOURCE_TYPE_TO_DOMAIN`
- Add natural-language messaging keywords to system prompt routing section
- Add `"messaging"` to `_A2A_DOMAINS`

### Test Coverage
- 35+ unit tests (success, SDK-missing, error paths for each tool)
- HITL proposal tests: approval_required, risk_level, proposed_action, reason, reversibility

### Terraform / Container App
- New Container App `ca-messaging-prod` following same Terraform pattern as other agents
- Dockerfile extends `Dockerfile.base` with messaging SDK packages

### Claude's Discretion
- Exact method names and parameter signatures
- Internal helper structure within tools.py
- Specific metric names for Azure Monitor queries (use standard Azure metric namespaces)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/shared/auth.py` — `get_credential()`, `get_agent_identity()`
- `agents/shared/telemetry.py` — `instrument_tool_call()`
- `agents/appservice/tools.py` — template for identical lazy-import + never-raise pattern
- `agents/containerapps/tools.py` — most recent domain agent implementation
- `agents/database/tools.py` — multi-service domain agent reference (Cosmos DB + PostgreSQL + SQL)
- `agents/orchestrator/agent.py` — wiring target: `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, `_A2A_DOMAINS`

### Established Patterns
- Every `tools.py` starts with try/except SDK import blocks (XxxClient = None fallback)
- `_log_sdk_availability()` called at module level
- `_extract_subscription_id(resource_id: str) -> str` local helper
- System prompt in `agent.py` follows established domain agent template
- `requirements.txt` lists specific pinned SDK versions

### Integration Points
- `agents/orchestrator/agent.py` — domain routing
- `agents/detection_plane/classify_domain.kql` — KQL domain classification (need to check location)
- `infra/container_apps.tf` or equivalent Terraform file for new Container App

</code_context>

<specifics>
## Specific Ideas

- Detection plane integration: extend KQL `classify_domain()` in the Fabric pipeline to classify `microsoft.servicebus.*` and `microsoft.eventhub.*` resource types as domain `messaging`
- Consumer lag calculation: for Event Hubs, lag = `last_enqueued_sequence_number - last_sequence_number_processed` per partition
- DLQ purge proposal: requires operator to confirm as DLQ data is permanently deleted after purge

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>
