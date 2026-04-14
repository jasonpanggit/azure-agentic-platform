---
wave: 1
depends_on: []
files_modified:
  - agents/messaging/__init__.py
  - agents/messaging/tools.py
  - agents/messaging/agent.py
  - agents/messaging/requirements.txt
  - agents/messaging/Dockerfile
  - agents/tests/messaging/__init__.py
  - agents/tests/messaging/test_messaging_tools.py
  - agents/orchestrator/agent.py
  - fabric/kql/functions/classify_domain.kql
  - services/detection-plane/classify_domain.py
autonomous: true
---

# Plan 49-1: Messaging Agent — Implementation, Tests, and Routing Wiring

## Goal

Create the `agents/messaging/` package (7 tools, agent factory, requirements, Dockerfile), 37 unit tests, and wire the `messaging` domain into the orchestrator routing map and detection plane classifiers.

## Context

Phase 49 adds Service Bus + Event Hub operational diagnostics as a new `messaging` domain. All patterns must be replicated exactly from `agents/containerapps/` (most recent domain agent, Phase 48). The orchestrator currently has 11 domain agents (`compute` through `containerapps`); this adds the 12th. The detection plane `classify_domain()` KQL and Python mirror currently classify 5 domains; both need `messaging` added before the `sre` fallback.

<threat_model>
## Security Threat Assessment

**1. SDK lazy-import fallback (None assignment)**: Tool functions guard `if ServiceBusManagementClient is None` and return structured error dicts — no secrets or stack traces leak to the LLM output. Pattern is identical to all other domain agents.

**2. Resource ID extraction**: `_extract_subscription_id()` performs a simple string split on `/subscriptions/` — no user-supplied regex execution, no path traversal. Raises `ValueError` on malformed IDs, which is caught in the outer `except Exception` and returned as a structured error.

**3. HITL proposal tool (`propose_servicebus_dlq_purge`)**: Returns a proposal dict with `approval_required: True` — does NOT execute any SDK call. Cannot perform any mutation. Consistent with REMEDI-001.

**4. Credential handling**: Uses `get_credential()` from `agents/shared/auth.py` which resolves `DefaultAzureCredential` — no secrets passed through tool parameters or stored in environment variables. Reader + Monitoring Reader RBAC scope (read-only).

**5. `VALID_DOMAINS` frozenset in classify_domain.py**: Adding `"messaging"` to this frozenset only expands the set of accepted incident domain values. The validation still rejects any value not in the frozenset. No security regression.

**6. KQL injection risk in classify_domain.kql**: The `has_any()` function in KQL receives string literals from our patch — no user input flows through this function. Not a vector.

**7. System prompt routing keywords**: The orchestrator system prompt addition adds natural-language routing cues. No code execution path from these strings — they are instructions to the LLM only.
</threat_model>

---

## Tasks

### Task 1: Create `agents/messaging/__init__.py`

<read_first>
- `agents/containerapps/__init__.py` — exact pattern (likely empty or minimal)
- `agents/messaging/` — confirm directory does not yet exist
</read_first>

<action>
Create `agents/messaging/__init__.py` as an empty file (same as `agents/containerapps/__init__.py`).

```python
```

(empty file — just creates the Python package)
</action>

<acceptance_criteria>
- File `agents/messaging/__init__.py` exists
- `grep -r "agents/messaging" agents/messaging/__init__.py` exits 0 (file is present)
- File is empty (0 bytes or contains only a newline)
</acceptance_criteria>

---

### Task 2: Create `agents/messaging/requirements.txt`

<read_first>
- `agents/containerapps/requirements.txt` — exact package list pattern to replicate
- `agents/appservice/requirements.txt` — verify `azure-mgmt-monitor` pin version
- `49-RESEARCH.md` Section 2 — confirmed SDK versions: `azure-mgmt-servicebus>=9.0.0`, `azure-mgmt-eventhub>=11.2.0`, `azure-monitor-query>=1.4.0`
</read_first>

<action>
Create `agents/messaging/requirements.txt` with these exact contents:

```
azure-mgmt-servicebus>=9.0.0
azure-mgmt-eventhub>=11.2.0
azure-monitor-query>=1.4.0
azure-mgmt-monitor>=6.0.0
azure-ai-agentserver-agentframework
agent-framework>=1.0.0rc5
```

Note: Include `azure-mgmt-monitor>=6.0.0` alongside `azure-monitor-query` because the metrics pattern uses `MonitorManagementClient.metrics.list()` (consistent with `agents/containerapps/tools.py`).
</action>

<acceptance_criteria>
- File `agents/messaging/requirements.txt` exists
- `grep "azure-mgmt-servicebus>=9.0.0" agents/messaging/requirements.txt` exits 0
- `grep "azure-mgmt-eventhub>=11.2.0" agents/messaging/requirements.txt` exits 0
- `grep "azure-monitor-query>=1.4.0" agents/messaging/requirements.txt` exits 0
- `grep "agent-framework>=1.0.0rc5" agents/messaging/requirements.txt` exits 0
</acceptance_criteria>

---

### Task 3: Create `agents/messaging/Dockerfile`

<read_first>
- `agents/containerapps/Dockerfile` — exact pattern to replicate (ARG BASE_IMAGE, COPY . ./containerapps/, CMD python -m containerapps.agent)
- `agents/appservice/Dockerfile` — second reference for confirmation
</read_first>

<action>
Create `agents/messaging/Dockerfile` with this exact content (mirror of `agents/containerapps/Dockerfile` with `containerapps` replaced by `messaging`):

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./messaging/

CMD ["python", "-m", "messaging.agent"]
```
</action>

<acceptance_criteria>
- File `agents/messaging/Dockerfile` exists
- `grep "ARG BASE_IMAGE" agents/messaging/Dockerfile` exits 0
- `grep "COPY . ./messaging/" agents/messaging/Dockerfile` exits 0
- `grep 'CMD \["python", "-m", "messaging.agent"\]' agents/messaging/Dockerfile` exits 0
</acceptance_criteria>

---

### Task 4: Create `agents/messaging/tools.py`

<read_first>
- `agents/containerapps/tools.py` — FULL FILE — exact structural pattern to replicate (lazy imports, `_log_sdk_availability`, `_extract_subscription_id`, `instrument_tool_call` usage, `MonitorManagementClient.metrics.list()` for metrics, HITL proposal pattern)
- `49-RESEARCH.md` Sections 2–4 — all tool signatures, return shapes, metric names, SDK field names, gotchas
- `49-CONTEXT.md` `<decisions>` block — tool function conventions (never-raise, duration_ms in both try/except, start_time = time.monotonic())
</read_first>

<action>
Create `agents/messaging/tools.py` implementing all 7 tools. Key implementation details:

**Header and imports:**
```python
"""Messaging Agent tool functions — Service Bus and Event Hub diagnostics.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_metrics, monitor.query_logs
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry
```

**Lazy SDK imports (3 blocks):**
```python
try:
    from azure.mgmt.servicebus import ServiceBusManagementClient
except ImportError:
    ServiceBusManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.eventhub import EventHubManagementClient
except ImportError:
    EventHubManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]
```

**Module setup:**
```python
tracer = setup_telemetry("aiops-messaging-agent")
logger = logging.getLogger(__name__)

ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_metrics",
    "monitor.query_logs",
]
```

**`_log_sdk_availability()`**: logs info for `azure-mgmt-servicebus`, `azure-mgmt-eventhub`, `azure-mgmt-monitor`; called at module level.

**`_extract_subscription_id(resource_id: str) -> str`**: exact copy from `containerapps/tools.py` — splits on `/subscriptions/`, raises `ValueError` if not found.

**Tool 1 — `get_servicebus_namespace_health`:**
```python
@ai_function
def get_servicebus_namespace_health(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```
- Uses `ServiceBusManagementClient(credential, subscription_id).namespaces.get(resource_group, namespace_name)`
- Returns: `namespace_name, resource_group, subscription_id, sku_tier, sku_capacity, status, provisioning_state, zone_redundant, geo_replication_enabled, location, query_status, duration_ms`
- Field extraction: `sku = getattr(ns, "sku", None); sku_tier = getattr(sku, "name", None) if sku else None; sku_capacity = getattr(sku, "capacity", None) if sku else None`
- `geo_replication_enabled`: `getattr(ns, "geo_data_replication", None) is not None`

**Tool 2 — `list_servicebus_queues`:**
```python
@ai_function
def list_servicebus_queues(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```
- Uses `client.queues.list_by_namespace(resource_group, namespace_name)` — iterates all queues
- `count_details` None guard (critical — see RESEARCH.md Section 10.1):
  ```python
  cd = getattr(q, "count_details", None)
  active = getattr(cd, "active_message_count", None) if cd else None
  dlq = getattr(cd, "dead_letter_message_count", None) if cd else None
  scheduled = getattr(cd, "scheduled_message_count", None) if cd else None
  ```
- `lock_duration` timedelta conversion (Section 10.2):
  ```python
  ld = getattr(q, "lock_duration", None)
  lock_duration_seconds = ld.total_seconds() if ld else None
  ```
- Returns: `namespace_name, resource_group, subscription_id, queue_count, queues: List[{queue_name, status, message_count, active_message_count, dead_letter_message_count, scheduled_message_count, max_delivery_count, lock_duration_seconds, dead_lettering_on_expiration, requires_session, size_in_bytes}], query_status, duration_ms`
- Docstring must note: Topics not included (deferred per CONTEXT.md)

**Tool 3 — `get_servicebus_metrics`:**
```python
@ai_function
def get_servicebus_metrics(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 4,
    entity_name: Optional[str] = None,
) -> Dict[str, Any]:
```
- Uses `MonitorManagementClient(credential, subscription_id).metrics.list()` (same pattern as `containerapps/tools.py` `get_container_app_metrics`)
- `resource_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.ServiceBus/namespaces/{namespace_name}"`
- Metric names: `"IncomingMessages,OutgoingMessages,ActiveMessages,DeadletteredMessages,ServerErrors,ThrottledRequests,UserErrors"`
- `timespan = f"PT{hours}H"`, `interval = "PT5M"`, `aggregation = "Total,Average"`
- When `entity_name` is not None: pass `filter=f"EntityName eq '{entity_name}'"` to `metrics.list()`
- Accumulate: `incoming_messages` (Total sum), `outgoing_messages` (Total sum), `active_messages_avg` (Average mean), `dead_lettered_messages_avg` (Average mean), `server_errors` (Total sum cast to int), `throttled_requests` (Total sum cast to int), `user_errors` (Total sum cast to int)
- Returns: `namespace_name, resource_group, subscription_id, timespan_hours, entity_name, incoming_messages, outgoing_messages, active_messages_avg, dead_lettered_messages_avg, server_errors, throttled_requests, user_errors, data_points, query_status, duration_ms`

**Tool 4 — `propose_servicebus_dlq_purge`:**
```python
@ai_function
def propose_servicebus_dlq_purge(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    queue_name: str,
    reason: str,
) -> Dict[str, Any]:
```
- Pure HITL proposal — no SDK call at all (same as `propose_container_app_scale` pattern)
- Uses `instrument_tool_call` context manager but returns immediately inside `with` block
- Returns:
  ```python
  {
      "proposal_type": "servicebus_dlq_purge",
      "namespace_name": namespace_name,
      "resource_group": resource_group,
      "subscription_id": subscription_id,
      "queue_name": queue_name,
      "reason": reason,
      "risk_level": "low",
      "proposed_action": f"Purge dead-letter queue '{queue_name}' on Service Bus namespace '{namespace_name}' in resource group '{resource_group}' (subscription: {subscription_id})",
      "reversibility": "NOT reversible — DLQ messages are permanently deleted after purge. Ensure all DLQ messages have been inspected or archived before approving.",
      "approval_required": True,
  }
  ```

**Tool 5 — `get_eventhub_namespace_health`:**
```python
@ai_function
def get_eventhub_namespace_health(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```
- Uses `EventHubManagementClient(credential, subscription_id).namespaces.get(resource_group, namespace_name)`
- Returns: `namespace_name, resource_group, subscription_id, sku_name, sku_capacity, status, provisioning_state, zone_redundant, kafka_enabled, is_auto_inflate_enabled, maximum_throughput_units, location, query_status, duration_ms`
- Field extraction: `sku = getattr(ns, "sku", None); sku_name = getattr(sku, "name", None) if sku else None; sku_capacity = getattr(sku, "capacity", None) if sku else None`

**Tool 6 — `list_eventhub_consumer_groups`:**
```python
@ai_function
def list_eventhub_consumer_groups(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```
- Step 1: `client.event_hubs.list_by_namespace(resource_group, namespace_name)` — iterate Event Hubs
- Step 2: For each Event Hub, call `client.consumer_groups.list_by_event_hub(resource_group, namespace_name, eh.name)` — iterate consumer groups
- Returns: `namespace_name, resource_group, subscription_id, eventhub_count, eventhubs: List[{eventhub_name, partition_count, status, message_retention_in_days, capture_enabled, consumer_group_count, consumer_groups: List[{consumer_group_name, created_at (ISO str), updated_at (ISO str), user_metadata}]}], query_status, duration_ms`
- For `created_at`/`updated_at`: `cg.created_at.isoformat() if hasattr(cg.created_at, "isoformat") else str(cg.created_at)` (guarded with `getattr`)
- Docstring must note: No per-partition lag available from management plane; use `get_eventhub_metrics` for aggregate lag estimation (see RESEARCH.md Section 3 note)

**Tool 7 — `get_eventhub_metrics`:**
```python
@ai_function
def get_eventhub_metrics(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 4,
    eventhub_name: Optional[str] = None,
) -> Dict[str, Any]:
```
- `resource_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.EventHub/namespaces/{namespace_name}"`
- Metric names: `"IncomingMessages,OutgoingMessages,IncomingBytes,OutgoingBytes,ThrottledRequests,ServerErrors,UserErrors"`
- `filter = f"EntityName eq '{eventhub_name}'"` when `eventhub_name is not None`
- `timespan = f"PT{hours}H"`, `interval = "PT5M"`, `aggregation = "Total"`
- `estimated_lag_count = int(incoming - outgoing) if incoming is not None and outgoing is not None else None`
- Returns: `namespace_name, resource_group, subscription_id, timespan_hours, eventhub_name, incoming_messages, outgoing_messages, incoming_bytes, outgoing_bytes, throttled_requests, server_errors, user_errors, estimated_lag_count, data_points, query_status, duration_ms`

**All tools must follow the never-raise pattern:**
```python
start_time = time.monotonic()
try:
    if SomeClient is None:
        raise ImportError("azure-mgmt-xxx is not installed")
    # ... implementation ...
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("tool_name: complete | ...")
    return {..., "query_status": "success", "duration_ms": duration_ms}
except Exception as e:
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.error("tool_name: failed | ...", exc_info=True)
    return {..., "query_status": "error", "error": str(e), "duration_ms": duration_ms}
```
</action>

<acceptance_criteria>
- File `agents/messaging/tools.py` exists
- `grep "from agent_framework import ai_function" agents/messaging/tools.py` exits 0
- `grep "ServiceBusManagementClient = None" agents/messaging/tools.py` exits 0
- `grep "EventHubManagementClient = None" agents/messaging/tools.py` exits 0
- `grep "MonitorManagementClient = None" agents/messaging/tools.py` exits 0
- `grep "_log_sdk_availability" agents/messaging/tools.py` exits 0
- `grep "_extract_subscription_id" agents/messaging/tools.py` exits 0
- `grep "def get_servicebus_namespace_health" agents/messaging/tools.py` exits 0
- `grep "def list_servicebus_queues" agents/messaging/tools.py` exits 0
- `grep "def get_servicebus_metrics" agents/messaging/tools.py` exits 0
- `grep "def propose_servicebus_dlq_purge" agents/messaging/tools.py` exits 0
- `grep "def get_eventhub_namespace_health" agents/messaging/tools.py` exits 0
- `grep "def list_eventhub_consumer_groups" agents/messaging/tools.py` exits 0
- `grep "def get_eventhub_metrics" agents/messaging/tools.py` exits 0
- `grep '"approval_required": True' agents/messaging/tools.py` exits 0
- `grep '"risk_level": "low"' agents/messaging/tools.py` exits 0
- `grep "ALLOWED_MCP_TOOLS" agents/messaging/tools.py` exits 0
- `grep '"NOT reversible' agents/messaging/tools.py` exits 0
- All 7 `@ai_function` decorators present: `grep -c "@ai_function" agents/messaging/tools.py` outputs `7`
</acceptance_criteria>

---

### Task 5: Create `agents/messaging/agent.py`

<read_first>
- `agents/containerapps/agent.py` — FULL FILE — exact factory pattern: `CONTAINERAPPS_AGENT_SYSTEM_PROMPT`, `create_containerapps_agent()`, `create_containerapps_agent_version()`, `if __name__ == "__main__":` block with `setup_logging` + `from_agent_framework`
- `agents/messaging/tools.py` (just written) — import names to use in factory
</read_first>

<action>
Create `agents/messaging/agent.py` following the exact `containerapps/agent.py` structure:

**Module docstring**: Document scope (Service Bus namespaces, queues, DLQ monitoring; Event Hub namespaces, consumer groups, metrics; HITL-gated DLQ purge proposals).

**System prompt `MESSAGING_AGENT_SYSTEM_PROMPT`**: Include:
- Scope: Azure Service Bus (namespaces, queues, DLQ) and Azure Event Hubs (namespaces, consumer groups, partition metrics)
- Mandatory triage workflow:
  1. For Service Bus incidents: `get_servicebus_namespace_health` → `list_servicebus_queues` (check DLQ depths) → `get_servicebus_metrics` → hypothesis with confidence score
  2. For Event Hub incidents: `get_eventhub_namespace_health` → `list_eventhub_consumer_groups` → `get_eventhub_metrics` (check estimated_lag_count) → hypothesis
  3. `propose_servicebus_dlq_purge` only when DLQ is confirmed elevated and operator wants to clear it — approval required
- Safety constraints: MUST NOT execute DLQ purge without approval; MUST include confidence_score (0.0–1.0); Reader + Monitoring Reader scope
- Consumer lag note: `get_eventhub_metrics` `estimated_lag_count = incoming - outgoing` is an approximation; exact per-partition lag requires data-plane SDK access which is not available in this agent (managed identity constraint)
- Allowed tools section formatted same as `containerapps/agent.py`

**Factory function `create_messaging_agent() -> ChatAgent`**:
```python
def create_messaging_agent() -> ChatAgent:
    client = get_foundry_client()
    agent = ChatAgent(
        name="messaging-agent",
        description=(
            "Messaging specialist — Service Bus and Event Hub diagnostics, DLQ monitoring, "
            "consumer lag estimation, and HITL-gated DLQ purge proposals."
        ),
        instructions=MESSAGING_AGENT_SYSTEM_PROMPT,
        chat_client=client,
        tools=[
            get_servicebus_namespace_health,
            list_servicebus_queues,
            get_servicebus_metrics,
            propose_servicebus_dlq_purge,
            get_eventhub_namespace_health,
            list_eventhub_consumer_groups,
            get_eventhub_metrics,
        ],
    )
    return agent
```

**`create_messaging_agent_version(project: "AIProjectClient") -> object`**: mirrors `create_containerapps_agent_version` exactly.

**`if __name__ == "__main__":` entry point**:
```python
if __name__ == "__main__":
    from shared.logging_config import setup_logging
    _logger = setup_logging("messaging")
    _logger.info("messaging: starting up")
    from azure.ai.agentserver.agentframework import from_agent_framework
    _logger.info("messaging: creating agent and binding to agentserver")
    from_agent_framework(create_messaging_agent()).run()
    _logger.info("messaging: agentserver exited")
```
</action>

<acceptance_criteria>
- File `agents/messaging/agent.py` exists
- `grep "from agent_framework import ChatAgent" agents/messaging/agent.py` exits 0
- `grep "MESSAGING_AGENT_SYSTEM_PROMPT" agents/messaging/agent.py` exits 0
- `grep "def create_messaging_agent" agents/messaging/agent.py` exits 0
- `grep "def create_messaging_agent_version" agents/messaging/agent.py` exits 0
- `grep 'name="messaging-agent"' agents/messaging/agent.py` exits 0
- `grep "from_agent_framework" agents/messaging/agent.py` exits 0
- `grep "setup_logging" agents/messaging/agent.py` exits 0
- `grep "get_servicebus_namespace_health" agents/messaging/agent.py` exits 0
- `grep "list_eventhub_consumer_groups" agents/messaging/agent.py` exits 0
- `grep "propose_servicebus_dlq_purge" agents/messaging/agent.py` exits 0
</acceptance_criteria>

---

### Task 6: Create `agents/tests/messaging/__init__.py` and `test_messaging_tools.py`

<read_first>
- `agents/tests/containerapps/test_containerapps_tools.py` — FULL FILE — exact test class structure, mock helpers, `@patch` decorator ordering, `_make_cm_mock()` pattern
- `agents/messaging/tools.py` (just written) — exact return shapes to assert against
- `49-RESEARCH.md` Section 9 — test class list and counts (37 total): `TestAllowedMcpTools` (4), `TestGetServicebusNamespaceHealth` (4), `TestListServicebusQueues` (5), `TestGetServicebusMetrics` (4), `TestProposeServicebusDlqPurge` (4), `TestGetEventhubNamespaceHealth` (4), `TestListEventhubConsumerGroups` (5), `TestGetEventhubMetrics` (4), `TestExtractSubscriptionId` (3)
- `49-RESEARCH.md` Section 10 — gotchas: `count_details` can be None, `lock_duration` is timedelta
</read_first>

<action>
Create `agents/tests/messaging/__init__.py` as empty file.

Create `agents/tests/messaging/test_messaging_tools.py` with the following 9 test classes (37 tests total):

**Helper:**
```python
def _make_cm_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m
```

**`TestAllowedMcpTools` (4 tests):**
- `test_allowed_mcp_tools_has_exactly_two_entries` — `assert len(ALLOWED_MCP_TOOLS) == 2`
- `test_allowed_mcp_tools_contains_expected_entries` — verify `"monitor.query_metrics"` and `"monitor.query_logs"` present
- `test_allowed_mcp_tools_no_wildcards` — assert `"*" not in tool` for each tool
- `test_allowed_mcp_tools_is_list` — `assert isinstance(ALLOWED_MCP_TOOLS, list)`

**`TestGetServicebusNamespaceHealth` (4 tests):**
Patch path: `agents.messaging.tools.ServiceBusManagementClient`, `agents.messaging.tools.get_credential`, `agents.messaging.tools.get_agent_identity`, `agents.messaging.tools.instrument_tool_call`
- `test_returns_success_with_namespace_data` — mock `client.namespaces.get()` returning namespace with sku.name="Standard", sku.capacity=None, status="Active", provisioning_state="Succeeded", zone_redundant=True, geo_data_replication=None, location="eastus"; assert `result["query_status"] == "success"`, `result["sku_tier"] == "Standard"`, `result["zone_redundant"] == True`, `result["geo_replication_enabled"] == False`, `result["duration_ms"] >= 0`
- `test_sdk_missing_returns_error` — patch `agents.messaging.tools.ServiceBusManagementClient = None`; assert `result["query_status"] == "error"`, `"not installed" in result["error"]`
- `test_azure_error_returns_error` — mock raises `Exception("ResourceNotFound")`; assert `result["query_status"] == "error"`, `"ResourceNotFound" in result["error"]`, `result["duration_ms"] >= 0`
- `test_no_sku_returns_none_tier` — mock returns namespace with `sku = None`; assert `result["sku_tier"] is None`, `result["sku_capacity"] is None`

**`TestListServicebusQueues` (5 tests):**
- `test_returns_success_with_queue_list` — mock returns 2 queues with count_details set; assert `result["queue_count"] == 2`, `result["queues"][0]["dead_letter_message_count"] == 5`
- `test_empty_namespace_returns_zero_queues` — mock returns empty iterator; assert `result["queue_count"] == 0`, `result["queues"] == []`
- `test_sdk_missing_returns_error` — patch client to None; assert error + "not installed"
- `test_azure_error_returns_error` — mock raises `Exception("NamespaceNotFound")`; assert error
- `test_count_details_none_returns_none_counts` — mock queue with `count_details = None`; assert `result["queues"][0]["active_message_count"] is None`, `result["queues"][0]["dead_letter_message_count"] is None`, `result["query_status"] == "success"` (no crash)

**`TestGetServicebusMetrics` (4 tests):**
- `test_returns_success_with_metrics` — mock `MonitorManagementClient.metrics.list()` returning metrics with data; assert `result["query_status"] == "success"`, `result["timespan_hours"] == 4`, `result["incoming_messages"]` is not None
- `test_sdk_missing_returns_error` — patch `MonitorManagementClient = None`; assert error
- `test_azure_error_returns_error` — mock raises `Exception("MetricsError")`; assert error
- `test_entity_name_filter_sets_field` — call with `entity_name="orders-queue"`; assert `result["entity_name"] == "orders-queue"`

**`TestProposeServicebusDlqPurge` (4 tests):**
Patch only `agents.messaging.tools.get_agent_identity` and `agents.messaging.tools.instrument_tool_call` (no SDK needed):
- `test_approval_required_is_true` — assert `result["approval_required"] == True`
- `test_risk_level_is_low` — assert `result["risk_level"] == "low"`
- `test_proposed_action_contains_queue_name` — call with `queue_name="orders-dlq"`; assert `"orders-dlq" in result["proposed_action"]`
- `test_reversibility_states_not_reversible` — assert `"NOT reversible" in result["reversibility"]`

**`TestGetEventhubNamespaceHealth` (4 tests):**
- `test_returns_success_with_namespace_data` — mock namespace with sku, kafka_enabled, is_auto_inflate_enabled, maximum_throughput_units, zone_redundant; assert success + correct field values
- `test_sdk_missing_returns_error` — patch `EventHubManagementClient = None`; assert error
- `test_azure_error_returns_error` — mock raises `Exception("NamespaceNotFound")`; assert error
- `test_no_sku_returns_none_fields` — mock namespace.sku = None; assert `result["sku_name"] is None`, `result["sku_capacity"] is None`

**`TestListEventhubConsumerGroups` (5 tests):**
- `test_returns_success_with_eventhubs_and_groups` — mock 1 Event Hub with 2 consumer groups; assert `result["eventhub_count"] == 1`, `result["eventhubs"][0]["consumer_group_count"] == 2`
- `test_empty_namespace_returns_zero_eventhubs` — mock empty event hub iterator; assert `result["eventhub_count"] == 0`
- `test_sdk_missing_returns_error` — patch `EventHubManagementClient = None`; assert error
- `test_azure_error_returns_error` — mock raises `Exception("NamespaceNotFound")`; assert error
- `test_empty_consumer_groups_returns_zero_count` — mock 1 Event Hub but empty consumer groups; assert `result["eventhubs"][0]["consumer_group_count"] == 0`

**`TestGetEventhubMetrics` (4 tests):**
- `test_returns_success_with_metrics` — mock metrics list returning IncomingMessages=1000 total, OutgoingMessages=900 total; assert `result["estimated_lag_count"] == 100`, `result["query_status"] == "success"`
- `test_sdk_missing_returns_error` — patch `MonitorManagementClient = None`; assert error
- `test_azure_error_returns_error` — mock raises `Exception("MetricsError")`; assert error
- `test_eventhub_name_filter_sets_field` — call with `eventhub_name="telemetry-hub"`; assert `result["eventhub_name"] == "telemetry-hub"`

**`TestExtractSubscriptionId` (3 tests):**
- `test_valid_resource_id` — input `/subscriptions/abc123/resourceGroups/rg1/providers/...`; assert `"abc123"` returned
- `test_missing_subscriptions_segment_raises` — input `/resourceGroups/rg1/...`; assert `ValueError` raised
- `test_empty_string_raises` — input `""`; assert `ValueError` raised
</action>

<acceptance_criteria>
- `agents/tests/messaging/__init__.py` exists (empty file)
- `agents/tests/messaging/test_messaging_tools.py` exists
- `grep -c "def test_" agents/tests/messaging/test_messaging_tools.py` outputs `37`
- `grep "class TestAllowedMcpTools" agents/tests/messaging/test_messaging_tools.py` exits 0
- `grep "class TestProposeServicebusDlqPurge" agents/tests/messaging/test_messaging_tools.py` exits 0
- `grep "class TestExtractSubscriptionId" agents/tests/messaging/test_messaging_tools.py` exits 0
- `grep "count_details_none" agents/tests/messaging/test_messaging_tools.py` exits 0
- `grep "estimated_lag_count" agents/tests/messaging/test_messaging_tools.py` exits 0
- `grep '"NOT reversible"' agents/tests/messaging/test_messaging_tools.py` exits 0
- Running `python -m pytest agents/tests/messaging/test_messaging_tools.py -v --tb=short` exits 0 with all 37 tests passing
</acceptance_criteria>

---

### Task 7: Update `agents/orchestrator/agent.py` — add `messaging` domain routing

<read_first>
- `agents/orchestrator/agent.py` — FULL FILE — current `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, `_A2A_DOMAINS`, system prompt routing section (lines 60–135)
- `49-RESEARCH.md` Section 5 — exact keys/values for each dict update
</read_first>

<action>
Make 4 targeted changes to `agents/orchestrator/agent.py`:

**Change 1 — `DOMAIN_AGENT_MAP` (line ~143):** Add one entry after `"container-apps": "containerapps_agent"`:
```python
"messaging": "messaging_agent",
```

**Change 2 — `RESOURCE_TYPE_TO_DOMAIN` (line ~160):** Add two entries after `"microsoft.app/managedenvironments": "container-apps"`:
```python
"microsoft.servicebus": "messaging",
"microsoft.eventhub": "messaging",
```

**Change 3 — System prompt routing keywords (line ~103):** Add one new bullet BEFORE the `"Topic is ambiguous..."` sre bullet:
```
- Mentions "service bus", "servicebus", "queue", "dead letter", "dlq", "topic",
    "subscription", "event hub", "eventhub", "consumer group", "consumer lag",
    "messaging namespace", "throughput units" → call `messaging_agent`
```

Also update the Tool allowlist line (~134) from:
```
    Tool allowlist: `compute_agent`, ..., `containerapps_agent`, `classify_incident_domain`.
```
to:
```
    Tool allowlist: `compute_agent`, `network_agent`, `storage_agent`, `security_agent`,
        `arc_agent`, `sre_agent`, `patch_agent`, `eol_agent`, `database_agent`,
        `appservice_agent`, `containerapps_agent`, `messaging_agent`, `classify_incident_domain`.
```

**Change 4 — `_A2A_DOMAINS` list (line ~305):** Add `"messaging"` to the end:
```python
_A2A_DOMAINS = [
    "compute", "patch", "network", "security",
    "arc", "sre", "eol", "storage", "database", "appservice", "containerapps",
    "messaging",  # Phase 49
]
```
</action>

<acceptance_criteria>
- `grep '"messaging": "messaging_agent"' agents/orchestrator/agent.py` exits 0
- `grep '"microsoft.servicebus": "messaging"' agents/orchestrator/agent.py` exits 0
- `grep '"microsoft.eventhub": "messaging"' agents/orchestrator/agent.py` exits 0
- `grep '"messaging"' agents/orchestrator/agent.py` — returns at least 3 lines
- `grep 'messaging_agent' agents/orchestrator/agent.py` exits 0
- `grep '"messaging".*# Phase 49' agents/orchestrator/agent.py` exits 0
- `grep '"dead letter"' agents/orchestrator/agent.py` exits 0 (keyword in routing section)
- `grep '"dlq"' agents/orchestrator/agent.py` exits 0
</acceptance_criteria>

---

### Task 8: Update `fabric/kql/functions/classify_domain.kql` — add messaging case

<read_first>
- `fabric/kql/functions/classify_domain.kql` — FULL FILE — current `case()` structure; `messaging` must be inserted before the final `"sre"` fallback
- `49-RESEARCH.md` Section 6 — exact KQL `has_any()` values and comment format
</read_first>

<action>
Add a new `messaging` case in the `case()` function body of `classify_domain.kql`, inserted immediately before the `// SRE fallback (D-06)` comment line:

```kql
        // Messaging domain (Phase 49) — Service Bus and Event Hub
        resource_type has_any (
            "Microsoft.ServiceBus/namespaces",
            "Microsoft.ServiceBus/namespaces/queues",
            "Microsoft.ServiceBus/namespaces/topics",
            "Microsoft.EventHub/namespaces",
            "Microsoft.EventHub/namespaces/eventhubs"
        ), "messaging",
```

The final file structure for the `case()` body will be:
```
compute case,
network case,
storage case,
security case,
arc case,
messaging case,   ← new
"sre" fallback    ← unchanged, still last
```
</action>

<acceptance_criteria>
- `grep "messaging" fabric/kql/functions/classify_domain.kql` exits 0
- `grep "Microsoft.ServiceBus/namespaces" fabric/kql/functions/classify_domain.kql` exits 0
- `grep "Microsoft.EventHub/namespaces" fabric/kql/functions/classify_domain.kql` exits 0
- `grep '"messaging"' fabric/kql/functions/classify_domain.kql` exits 0
- The `"sre"` fallback is still the last case: `grep '"sre"' fabric/kql/functions/classify_domain.kql` exits 0 and it appears AFTER the messaging block
- File still starts with `.create-or-alter function classify_domain`
</acceptance_criteria>

---

### Task 9: Update `services/detection-plane/classify_domain.py` — add messaging mappings and VALID_DOMAINS

<read_first>
- `services/detection-plane/classify_domain.py` — FULL FILE — current `DOMAIN_MAPPINGS` dict, `VALID_DOMAINS` frozenset, and docstring comment about the frozenset (RESEARCH.md Section 10.4 warns this is critical)
- `49-RESEARCH.md` Section 6 — exact Python dict entries to add
</read_first>

<action>
Make 2 changes to `services/detection-plane/classify_domain.py`:

**Change 1 — `DOMAIN_MAPPINGS` dict**: Add 4 entries after the `arc` domain block (before the closing `}`):
```python
    # Messaging domain (Phase 49) — Service Bus and Event Hub
    "microsoft.servicebus/namespaces": "messaging",
    "microsoft.servicebus/namespaces/queues": "messaging",
    "microsoft.servicebus": "messaging",
    "microsoft.eventhub/namespaces": "messaging",
    "microsoft.eventhub/namespaces/eventhubs": "messaging",
    "microsoft.eventhub": "messaging",
```

**Change 2 — `VALID_DOMAINS` frozenset**: Update from:
```python
VALID_DOMAINS = frozenset({"compute", "network", "storage", "security", "arc", "sre"})
```
to:
```python
VALID_DOMAINS = frozenset({"compute", "network", "storage", "security", "arc", "sre", "messaging"})
```

Also update the comment above `VALID_DOMAINS` from:
```python
# Valid domain values (matches IncidentPayload.domain regex: ^(compute|network|storage|security|arc|sre)$)
```
to:
```python
# Valid domain values (matches IncidentPayload.domain regex: ^(compute|network|storage|security|arc|sre|messaging)$)
```

**Important check**: Search `services/api-gateway/` for any `domain` field validation (Literal, Enum, regex) that also needs `"messaging"` added. Use `grep -r "compute.*network.*storage" services/api-gateway/` to find it. If found in a models.py or incident_ingestion.py, add `"messaging"` there too.
</action>

<acceptance_criteria>
- `grep '"microsoft.servicebus": "messaging"' services/detection-plane/classify_domain.py` exits 0
- `grep '"microsoft.eventhub": "messaging"' services/detection-plane/classify_domain.py` exits 0
- `grep '"messaging"' services/detection-plane/classify_domain.py` — returns at least 3 lines (frozenset + dict entries)
- `grep 'frozenset.*"messaging"' services/detection-plane/classify_domain.py` exits 0
- If a domain validation enum/literal was found in `services/api-gateway/`: `grep '"messaging"' services/api-gateway/models.py` (or wherever found) exits 0
</acceptance_criteria>

---

## Verification

After all tasks complete, run the full test suite to confirm 37 new tests pass and no regressions:

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/messaging/test_messaging_tools.py -v --tb=short
```

Expected: 37 passed, 0 failed.

Also verify module imports cleanly:
```bash
python -c "from agents.messaging.tools import ALLOWED_MCP_TOOLS, get_servicebus_namespace_health, propose_servicebus_dlq_purge, get_eventhub_metrics; print('OK')"
```

## must_haves

- [ ] `agents/messaging/` package exists with `__init__.py`, `tools.py`, `agent.py`, `requirements.txt`, `Dockerfile`
- [ ] `agents/tests/messaging/test_messaging_tools.py` exists with exactly 37 test functions
- [ ] All 37 tests pass (`pytest agents/tests/messaging/ -v` exits 0)
- [ ] `agents/orchestrator/agent.py` `DOMAIN_AGENT_MAP` contains `"messaging": "messaging_agent"`
- [ ] `agents/orchestrator/agent.py` `RESOURCE_TYPE_TO_DOMAIN` contains `"microsoft.servicebus"` and `"microsoft.eventhub"` → `"messaging"`
- [ ] `agents/orchestrator/agent.py` `_A2A_DOMAINS` contains `"messaging"`
- [ ] `fabric/kql/functions/classify_domain.kql` `case()` contains a `"messaging"` case before the `"sre"` fallback
- [ ] `services/detection-plane/classify_domain.py` `VALID_DOMAINS` frozenset contains `"messaging"`
- [ ] `services/detection-plane/classify_domain.py` `DOMAIN_MAPPINGS` contains `"microsoft.servicebus"` and `"microsoft.eventhub"` entries
- [ ] `propose_servicebus_dlq_purge` always returns `approval_required: True` (verified by test)
- [ ] Every tool returns `duration_ms` in both success and error paths (verified by tests)
- [ ] `count_details` None guard is present in `list_servicebus_queues` (verified by `test_count_details_none_returns_none_counts` test passing)
