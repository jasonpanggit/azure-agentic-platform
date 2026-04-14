# Phase 49: Messaging Agent (Service Bus + Event Hub) — Research

**Gathered:** 2026-04-14
**Purpose:** Answer "What do I need to know to PLAN this phase well?"

---

## 1. Summary

Phase 49 adds a new `messaging` domain agent to the AAP platform. It follows the exact same structural pattern as every domain agent added since Phase 11. There are no novel architectural risks. The main implementation work is:

1. Wiring the correct Azure SDK calls for Service Bus and Event Hub management-plane data.
2. Getting the right Azure Monitor metric names for both services.
3. Replicating the DLQ purge HITL pattern from other proposal tools.
4. Adding `"messaging"` to the orchestrator, detection plane KQL, and Terraform.

All of these have exact templates in the existing codebase. This is a **medium-complexity, low-risk phase**.

---

## 2. SDK Choices Confirmed

### Service Bus — `azure-mgmt-servicebus`

| | |
|---|---|
| **Package** | `azure-mgmt-servicebus` |
| **Latest stable** | `9.0.0` (released 2025-04-22) |
| **Client class** | `ServiceBusManagementClient(credential, subscription_id)` |
| **Import path** | `from azure.mgmt.servicebus import ServiceBusManagementClient` |

**Key operations used in this phase:**

| Tool | SDK call |
|---|---|
| `get_servicebus_namespace_health` | `client.namespaces.get(rg, namespace_name)` → `SBNamespace` |
| `list_servicebus_queues` | `client.queues.list_by_namespace(rg, namespace_name)` → iterable of `SBQueue` |
| `get_servicebus_metrics` | `azure-monitor-query` `MetricsQueryClient` (not mgmt SDK) |
| `propose_servicebus_dlq_purge` | Pure HITL — no SDK call at proposal time |

**SBNamespace fields** (from `client.namespaces.get()`):
- `sku.name` — "Basic", "Standard", "Premium"
- `sku.tier` — Same values
- `sku.capacity` — Messaging units (Premium only)
- `status` — "Active", "Creating", "Deleting", "Disabled", etc.
- `provisioning_state` — "Succeeded", "Failed", "Canceled"
- `geo_data_replication` — Geo-replication config (if enabled)
- `zone_redundant` — bool
- `location`, `name`, `id`

**SBQueue fields** (from `client.queues.list_by_namespace()` or `client.queues.get()`):
- `name` — Queue name
- `message_count` — Total messages (all states) — server-populated
- `count_details` — `MessageCountDetails` object with sub-fields:
  - `count_details.active_message_count` — Active (ready to deliver) messages
  - `count_details.dead_letter_message_count` — DLQ depth ← **key metric**
  - `count_details.scheduled_message_count` — Scheduled
  - `count_details.transfer_message_count` — In transfer to another queue
  - `count_details.transfer_dead_letter_message_count` — DLQ in transfer
- `status` — Entity status ("Active", "Disabled", etc.)
- `lock_duration` — timedelta
- `max_delivery_count` — int (messages auto-DLQ'd after this many retries)
- `dead_lettering_on_message_expiration` — bool
- `requires_session` — bool
- `enable_partitioning` — bool
- `size_in_bytes` — int

> **Important:** `count_details` is a server-populated variable — it is only available after calling `.get()` or `.list_by_namespace()`. Message counts are **point-in-time** values and may lag when the namespace is throttled (returns 0 during throttle).

**Topics (for completeness):** `client.topics.list_by_namespace(rg, namespace_name)` returns `SBTopic` objects with same `count_details` structure. `client.subscriptions.list_by_topic()` gives per-subscription DLQ counts. Include topics summary in `list_servicebus_queues` (optionally) or keep as a follow-on.

---

### Event Hub — `azure-mgmt-eventhub`

| | |
|---|---|
| **Package** | `azure-mgmt-eventhub` |
| **Latest stable** | `11.2.0` (released 2025-01-20) |
| **Client class** | `EventHubManagementClient(credential, subscription_id)` |
| **Import path** | `from azure.mgmt.eventhub import EventHubManagementClient` |

**Key operations used in this phase:**

| Tool | SDK call |
|---|---|
| `get_eventhub_namespace_health` | `client.namespaces.get(rg, namespace_name)` → `EHNamespace` |
| `list_eventhub_consumer_groups` | `client.event_hubs.list_by_namespace(rg, ns)` + `client.consumer_groups.list_by_event_hub(rg, ns, eh_name)` |
| `get_eventhub_metrics` | `azure-monitor-query` `MetricsQueryClient` |

**EHNamespace fields** (from `client.namespaces.get()`):
- `sku.name` — "Basic", "Standard", "Premium"
- `sku.capacity` — Throughput units (Standard) or Processing units (Premium)
- `status` — "Active", "Creating", etc.
- `provisioning_state` — "Succeeded" etc.
- `is_auto_inflate_enabled` — bool (auto-inflate throughput units)
- `maximum_throughput_units` — int
- `zone_redundant` — bool
- `kafka_enabled` — bool

**Consumer lag calculation:**
The management SDK does **not** expose consumer group offset/lag directly. The `consumer_groups` resource in the management SDK only has `name`, `created_at`, `updated_at`, `user_metadata`.

For actual **consumer lag per partition**, two approaches:
1. **Azure Monitor metrics** (preferred for read-only agent): Compare `IncomingMessages` vs `OutgoingMessages` over a window as a proxy for aggregate lag.
2. **`azure-eventhub` data-plane SDK** (`EventHubConsumerClient.get_partition_properties()`): Returns `last_enqueued_sequence_number` — but this requires connection string or SAS token, which violates the "managed identity, no secrets" constraint.

**Decision for Phase 49:** Use Azure Monitor metrics for lag proxy. Report `incoming_messages_per_window`, `outgoing_messages_per_window`, and derive `estimated_lag_count = incoming - outgoing` as the operational signal. Also report partition count from `client.event_hubs.get(rg, ns, eh_name).partition_count`. The `list_eventhub_consumer_groups` tool lists consumer groups with metadata and reports the partition count per Event Hub — this is what the management SDK can provide.

---

### Metrics — `azure-monitor-query`

Both Service Bus and Event Hub metrics go through `azure-monitor-query` `MetricsQueryClient`. This package is already in several agent `requirements.txt` files. Reuse the pattern from `agents/appservice/tools.py`.

**Service Bus metric names (REST API names for `metricnames` parameter):**

| Metric REST Name | Description | Aggregation |
|---|---|---|
| `ActiveMessages` | Active messages in queue/topic | Average |
| `DeadletteredMessages` | DLQ depth | Average |
| `IncomingMessages` | Messages sent to Service Bus | Total |
| `OutgoingMessages` | Messages received from Service Bus | Total |
| `ServerErrors` | Server-side errors | Total |
| `ThrottledRequests` | Throttled requests | Total |
| `UserErrors` | Client/user errors | Total |
| `Messages` | Total message count (all states) | Average |
| `Size` | Entity size in bytes | Average |

Dimension `EntityName` filters to a specific queue/topic. Omit the dimension for namespace-level aggregates.

**Event Hub metric names (REST API names):**

| Metric REST Name | Description | Aggregation |
|---|---|---|
| `IncomingMessages` | Events sent to Event Hub | Total |
| `OutgoingMessages` | Events read from Event Hub | Total |
| `IncomingBytes` | Bytes sent | Total |
| `OutgoingBytes` | Bytes read | Total |
| `ThrottledRequests` | Throttled requests | Total |
| `ServerErrors` | Server errors | Total |
| `UserErrors` | User errors | Total |
| `ActiveConnections` | Active connections | Total |
| `CaptureBacklog` | Capture backlog | Total |
| `CapturedMessages` | Messages captured | Total |

**Resource URI format for metric queries:**

```
Service Bus:  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ServiceBus/namespaces/{ns}
Event Hub:    /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.EventHub/namespaces/{ns}
```

---

## 3. Agent Structure (exact pattern)

### Directory layout — follows every other domain agent exactly:

```
agents/messaging/
├── __init__.py
├── tools.py          # All @ai_function tool implementations
├── agent.py          # ChatAgent factory + system prompt
├── requirements.txt  # SDK pin versions
└── Dockerfile        # FROM ${BASE_IMAGE}, copies messaging/ dir

agents/tests/messaging/
└── test_messaging_tools.py   # 35+ unit tests
```

### `requirements.txt` contents:

```
azure-mgmt-servicebus>=9.0.0
azure-mgmt-eventhub>=11.2.0
azure-monitor-query>=1.4.0
azure-ai-agentserver-agentframework
agent-framework>=1.0.0rc5
```

### `Dockerfile` (verbatim copy of appservice pattern):

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./messaging/

CMD ["python", "-m", "messaging.agent"]
```

### `tools.py` structure:

```python
# Lazy imports
try:
    from azure.mgmt.servicebus import ServiceBusManagementClient
except ImportError:
    ServiceBusManagementClient = None

try:
    from azure.mgmt.eventhub import EventHubManagementClient
except ImportError:
    EventHubManagementClient = None

try:
    from azure.monitor.query import MetricsQueryClient, MetricAggregationType
except ImportError:
    MetricsQueryClient = None
    MetricAggregationType = None

def _log_sdk_availability() -> None: ...
_log_sdk_availability()

def _extract_subscription_id(resource_id: str) -> str: ...

# ALLOWED_MCP_TOOLS list (monitor.query_metrics, monitor.query_logs)

@ai_function def get_servicebus_namespace_health(...): ...
@ai_function def list_servicebus_queues(...): ...
@ai_function def get_servicebus_metrics(...): ...
@ai_function def propose_servicebus_dlq_purge(...): ...
@ai_function def get_eventhub_namespace_health(...): ...
@ai_function def list_eventhub_consumer_groups(...): ...
@ai_function def get_eventhub_metrics(...): ...
```

### `agent.py` structure (follows `containerapps/agent.py` exactly):

```python
from messaging.tools import (
    ALLOWED_MCP_TOOLS,
    get_servicebus_namespace_health,
    list_servicebus_queues,
    get_servicebus_metrics,
    propose_servicebus_dlq_purge,
    get_eventhub_namespace_health,
    list_eventhub_consumer_groups,
    get_eventhub_metrics,
)

MESSAGING_AGENT_SYSTEM_PROMPT = """..."""

def create_messaging_agent() -> ChatAgent: ...
def create_messaging_agent_version(project: "AIProjectClient") -> object: ...

if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_messaging_agent()).run()
```

---

## 4. Tool Signatures and Return Shapes

### `get_servicebus_namespace_health`

```python
def get_servicebus_namespace_health(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```

Returns:
```
namespace_name, resource_group, subscription_id,
sku_tier (str | None), sku_capacity (int | None),
status (str | None), provisioning_state (str | None),
zone_redundant (bool | None), geo_replication_enabled (bool | None),
location (str | None), query_status, duration_ms
```

### `list_servicebus_queues`

```python
def list_servicebus_queues(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```

Returns:
```
namespace_name, resource_group, subscription_id,
queue_count (int),
queues: List[{
    queue_name, status, message_count, active_message_count,
    dead_letter_message_count, scheduled_message_count,
    max_delivery_count, lock_duration_seconds,
    dead_lettering_on_expiration, requires_session,
    size_in_bytes
}],
query_status, duration_ms
```

### `get_servicebus_metrics`

```python
def get_servicebus_metrics(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 4,
    entity_name: Optional[str] = None,  # filter to specific queue/topic
) -> Dict[str, Any]:
```

Returns:
```
namespace_name, resource_group, subscription_id,
timespan_hours, entity_name (applied filter),
incoming_messages (float | None),
outgoing_messages (float | None),
active_messages_avg (float | None),
dead_lettered_messages_avg (float | None),
server_errors (int | None),
throttled_requests (int | None),
user_errors (int | None),
data_points (list),
query_status, duration_ms
```

### `propose_servicebus_dlq_purge`

```python
def propose_servicebus_dlq_purge(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    queue_name: str,
    reason: str,
) -> Dict[str, Any]:
```

Returns HITL proposal (no SDK call):
```
proposal_type: "servicebus_dlq_purge",
namespace_name, resource_group, subscription_id, queue_name, reason,
risk_level: "low",
proposed_action: "Purge dead-letter queue '{queue_name}' ...",
reversibility: "NOT reversible — DLQ messages are permanently deleted after purge. ...",
approval_required: True
```

### `get_eventhub_namespace_health`

```python
def get_eventhub_namespace_health(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```

Returns:
```
namespace_name, resource_group, subscription_id,
sku_name (str | None), sku_capacity (int | None),
status (str | None), provisioning_state (str | None),
zone_redundant (bool | None), kafka_enabled (bool | None),
is_auto_inflate_enabled (bool | None),
maximum_throughput_units (int | None),
location (str | None), query_status, duration_ms
```

### `list_eventhub_consumer_groups`

```python
def list_eventhub_consumer_groups(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
) -> Dict[str, Any]:
```

Lists all Event Hubs in the namespace, then for each, lists consumer groups. Returns:
```
namespace_name, resource_group, subscription_id,
eventhub_count (int),
eventhubs: List[{
    eventhub_name, partition_count, status,
    message_retention_in_days, capture_enabled,
    consumer_group_count,
    consumer_groups: List[{
        consumer_group_name, created_at, updated_at, user_metadata
    }]
}],
query_status, duration_ms
```

> **Note:** No per-partition lag available from management plane. Report aggregate via metrics in `get_eventhub_metrics`. The tool description should explain this and direct operators to `get_eventhub_metrics` for incoming vs outgoing trend analysis.

### `get_eventhub_metrics`

```python
def get_eventhub_metrics(
    namespace_name: str,
    resource_group: str,
    subscription_id: str,
    hours: int = 4,
    eventhub_name: Optional[str] = None,
) -> Dict[str, Any]:
```

Returns:
```
namespace_name, resource_group, subscription_id,
timespan_hours, eventhub_name (applied filter),
incoming_messages (float | None),
outgoing_messages (float | None),
incoming_bytes (float | None),
outgoing_bytes (float | None),
throttled_requests (int | None),
server_errors (int | None),
user_errors (int | None),
estimated_lag_count (int | None),  # incoming - outgoing over window
data_points (list),
query_status, duration_ms
```

---

## 5. Orchestrator Wiring

### `DOMAIN_AGENT_MAP` — add one entry:

```python
"messaging": "messaging_agent",
```

### `RESOURCE_TYPE_TO_DOMAIN` — add two entries:

```python
"microsoft.servicebus": "messaging",
"microsoft.eventhub": "messaging",
```

### System prompt routing section — add bullet:

```
- Mentions "service bus", "servicebus", "queue", "dead letter", "dlq", "topic", "subscription",
    "event hub", "eventhub", "consumer group", "consumer lag", "messaging namespace",
    "throughput units" → call `messaging_agent`
```

### `_A2A_DOMAINS` list — add `"messaging"`:

```python
_A2A_DOMAINS = [
    "compute", "patch", "network", "security",
    "arc", "sre", "eol", "storage", "database", "appservice", "containerapps",
    "messaging",  # Phase 49
]
```

### Tool allowlist in system prompt — add `messaging_agent`.

---

## 6. Detection Plane Updates

### KQL function `fabric/kql/functions/classify_domain.kql`

Add a new `messaging` case before the `"sre"` fallback:

```kql
// Messaging domain (Phase 49)
resource_type has_any (
    "Microsoft.ServiceBus/namespaces",
    "Microsoft.EventHub/namespaces",
    "Microsoft.ServiceBus/namespaces/queues",
    "Microsoft.ServiceBus/namespaces/topics",
    "Microsoft.EventHub/namespaces/eventhubs"
), "messaging",
```

### Python mirror `services/detection-plane/classify_domain.py`

Add to `DOMAIN_MAPPINGS`:

```python
# Messaging domain (Phase 49)
"microsoft.servicebus/namespaces": "messaging",
"microsoft.servicebus": "messaging",
"microsoft.eventhub/namespaces": "messaging",
"microsoft.eventhub": "messaging",
```

Also update `VALID_DOMAINS` frozenset to include `"messaging"`.

> **Careful:** The existing `VALID_DOMAINS` frozenset is used by the deduplication logic in the API gateway (validates incoming incident `domain` field). It must include `"messaging"` or incidents routed to the messaging domain will be rejected. Check `services/api-gateway/` for any regex/enum validation on `domain`.

---

## 7. Terraform Changes

### `terraform/modules/agent-apps/main.tf`

Add `messaging` to the `locals.agents` map:

```hcl
messaging = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
```

### A2A connections

`messaging` needs to be added to `local.a2a_domains_all`:

```hcl
messaging = var.messaging_agent_endpoint
```

### Variables

Add to `variables.tf`:

```hcl
variable "messaging_agent_endpoint" {
  description = "Internal FQDN of the messaging domain agent Container App"
  type        = string
  default     = ""
}

variable "messaging_agent_id" {
  description = "Foundry agent ID for the messaging domain agent"
  type        = string
  default     = ""
}
```

### Agent ID injection (orchestrator/api-gateway)

Add dynamic env block for `MESSAGING_AGENT_ID` (same pattern as other domain agents):

```hcl
dynamic "env" {
  for_each = contains(["orchestrator", "api-gateway"], each.key) && var.messaging_agent_id != "" ? [1] : []
  content {
    name  = "MESSAGING_AGENT_ID"
    value = var.messaging_agent_id
  }
}
```

### RBAC

The messaging agent needs `Reader` and `Monitoring Reader` roles across all in-scope subscriptions. Follow the same pattern as other agents in the RBAC module. The managed identity (SystemAssigned on `ca-messaging-prod`) automatically becomes the Entra Agent ID.

---

## 8. CI/CD

### GitHub Actions build workflow

Add a `build-messaging` job in the CI pipeline following the identical pattern as `build-appservice` and `build-containerapps`. The job builds `agents/messaging/` with `Dockerfile` + `BASE_IMAGE` ARG and pushes to ACR path `agents/messaging`.

---

## 9. Test Plan (35+ tests)

Follow `agents/tests/containerapps/test_containerapps_tools.py` pattern exactly.

### Test classes and counts:

| Class | Tests |
|---|---|
| `TestAllowedMcpTools` | 4 (count, content, no-wildcards, is-list) |
| `TestGetServicebusNamespaceHealth` | 4 (success, SDK missing, Azure error, no-sku) |
| `TestListServicebusQueues` | 5 (success, empty namespace, SDK missing, Azure error, count_details None) |
| `TestGetServicebusMetrics` | 4 (success, SDK missing, Azure error, entity_name filter) |
| `TestProposeServicebusDlqPurge` | 4 (approval_required=True, risk_level, proposed_action, reversibility) |
| `TestGetEventhubNamespaceHealth` | 4 (success, SDK missing, Azure error, no-sku) |
| `TestListEventhubConsumerGroups` | 5 (success, empty namespace, SDK missing, Azure error, empty consumer groups) |
| `TestGetEventhubMetrics` | 4 (success, SDK missing, Azure error, estimated_lag_count) |
| `TestExtractSubscriptionId` | 3 (valid resource ID, missing subscriptions, empty string) |
| **Total** | **37** |

### Test invariants to verify (from CONTEXT.md):

- Every tool returns `query_status: "success"` on success, `"error"` on exception.
- Every tool returns `duration_ms` in **both** try and except blocks.
- `propose_servicebus_dlq_purge` always returns `approval_required: True`, `risk_level: "low"`.
- SDK-missing tests: patch the module-level client var to `None`, verify `error` key contains "not installed".
- `count_details` None handling: when `q.count_details is None`, fields should be `None` not raise.

---

## 10. Key Implementation Gotchas

### 1. `count_details` can be `None`

Azure returns `count_details = None` when the namespace is throttled or the Service Bus tier does not support it. Always guard:

```python
cd = getattr(queue, "count_details", None)
active = getattr(cd, "active_message_count", None) if cd else None
dlq = getattr(cd, "dead_letter_message_count", None) if cd else None
```

### 2. `lock_duration` is a `timedelta`, not a string

When returning `lock_duration` convert to seconds:

```python
ld = getattr(queue, "lock_duration", None)
lock_duration_seconds = ld.total_seconds() if ld else None
```

### 3. Consumer lag is not natively available from management plane

The `azure-mgmt-eventhub` management SDK consumer group object has: `name`, `created_at`, `updated_at`, `user_metadata`. No offset, no sequence number, no lag. The system prompt must explain this and point operators to `get_eventhub_metrics` for aggregate lag estimation.

### 4. `VALID_DOMAINS` frozenset in classify_domain.py

Currently: `frozenset({"compute", "network", "storage", "security", "arc", "sre"})`. Needs `"messaging"` added. Check if this frozenset is used for validation elsewhere (API gateway incident ingestion). If the IncidentPayload model uses a `Literal[...]` or `Enum`, that also needs updating.

### 5. Detection plane `domain` validation in API gateway

Search for the domain validation in `services/api-gateway/` — likely in `models.py` or `incident_ingestion.py`. Add `"messaging"` to the allowed domain list/enum.

### 6. Metric query uses `MetricsQueryClient` not `MonitorManagementClient`

The project uses `azure-monitor-query` (the modern query SDK), not `azure-mgmt-monitor`. The appservice agent uses `MonitorManagementClient` for metrics, but newer agents should prefer `MetricsQueryClient`. Check what the database and containerapps agents use to be consistent. The appservice agent uses `MonitorManagementClient.metrics.list()` — use the same approach for consistency.

### 7. Topics are not in scope (deferred per CONTEXT.md)

`list_servicebus_queues` returns queues only. If topics with subscriptions need DLQ monitoring, that is a follow-on. The tool should note this in its docstring.

---

## 11. Files to Create or Modify

### New files:

```
agents/messaging/__init__.py
agents/messaging/tools.py
agents/messaging/agent.py
agents/messaging/requirements.txt
agents/messaging/Dockerfile
agents/tests/messaging/__init__.py
agents/tests/messaging/test_messaging_tools.py
```

### Modified files:

```
agents/orchestrator/agent.py               # DOMAIN_AGENT_MAP, RESOURCE_TYPE_TO_DOMAIN, system prompt, _A2A_DOMAINS
fabric/kql/functions/classify_domain.kql  # Add messaging case
services/detection-plane/classify_domain.py  # Add mappings + VALID_DOMAINS
terraform/modules/agent-apps/main.tf      # Add messaging to agents map + A2A + env vars
terraform/modules/agent-apps/variables.tf  # messaging_agent_id, messaging_agent_endpoint
terraform/envs/prod/main.tf               # Pass new vars (or add to module call)
terraform/envs/prod/terraform.tfvars      # messaging_agent_id = "" placeholder
.github/workflows/build-all-images.yml    # Add build-messaging job
```

> Also check `services/api-gateway/` for any `domain` validation enum/literal that needs `"messaging"` added.

---

## 12. Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| `count_details` is `None` on throttled namespaces | Medium | Guard with `if cd else None` pattern |
| Consumer lag not available from management SDK | **Confirmed** | Use metrics-based estimation; document clearly |
| `VALID_DOMAINS` frozenset not updated → incidents rejected | High impact | Search for all domain validation points before submitting |
| `azure-mgmt-servicebus 9.0.0` API changes from 8.x | Low | SDK uses same client name and operation names |
| Terraform `for_each` instability from adding messaging | Low | Adding to `locals.agents` map is safe (key-based, no index) |

---

## 13. Phase Plan Recommendation (2 plans)

**Plan 49-1: Agent implementation + orchestrator wiring**
- `agents/messaging/` package (tools + agent + requirements + Dockerfile)
- `agents/tests/messaging/` (37 unit tests)
- Orchestrator routing (`DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, system prompt, `_A2A_DOMAINS`)
- Detection plane updates (KQL + Python mirror + `VALID_DOMAINS`)
- API gateway domain validation update (if needed)

**Plan 49-2: Terraform + CI**
- `terraform/modules/agent-apps/main.tf` — add messaging to agents map + A2A connections
- `terraform/modules/agent-apps/variables.tf` — add messaging variables
- `terraform/envs/prod/` — pass messaging vars
- `.github/workflows/` — add build-messaging CI job

---

## Sources

- [azure-mgmt-servicebus PyPI](https://pypi.org/project/azure-mgmt-servicebus/) — v9.0.0 latest stable
- [azure-mgmt-eventhub PyPI](https://pypi.org/project/azure-mgmt-eventhub/) — v11.2.0 latest stable
- [SBQueue model docs](https://learn.microsoft.com/en-us/python/api/azure-mgmt-servicebus/azure.mgmt.servicebus.models.sbqueue)
- [QueuesOperations docs](https://learn.microsoft.com/en-us/python/api/azure-mgmt-servicebus/azure.mgmt.servicebus.operations.queuesoperations)
- [Service Bus Azure Monitor metrics reference](https://learn.microsoft.com/en-us/azure/service-bus-messaging/monitor-service-bus-reference)
- Event Hub metrics reference (from web search knowledge)
- Existing codebase patterns: `agents/appservice/tools.py`, `agents/containerapps/agent.py`, `terraform/modules/agent-apps/main.tf`
