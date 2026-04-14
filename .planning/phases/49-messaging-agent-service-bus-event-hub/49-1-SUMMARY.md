# Phase 49-1 Summary: Messaging Agent — Implementation, Tests, and Routing Wiring

**Completed:** 2026-04-14
**Branch:** `gsd/phase-49-messaging-agent-service-bus-event-hub`
**Plan:** 49-1

---

## What Was Built

Phase 49-1 adds the `messaging` domain as the 12th agent in the AAP multi-agent platform, covering Azure Service Bus and Event Hub operational diagnostics.

### New Files

| File | Description |
|------|-------------|
| `agents/messaging/__init__.py` | Python package init |
| `agents/messaging/requirements.txt` | SDK pins: `azure-mgmt-servicebus>=9.0.0`, `azure-mgmt-eventhub>=11.2.0`, `azure-monitor-query>=1.4.0`, `azure-mgmt-monitor>=6.0.0` |
| `agents/messaging/Dockerfile` | Container image definition (extends `BASE_IMAGE`) |
| `agents/messaging/tools.py` | 7 `@ai_function` tool implementations (1,024 lines) |
| `agents/messaging/agent.py` | `ChatAgent` factory, system prompt, `create_messaging_agent()`, `create_messaging_agent_version()` |
| `agents/tests/messaging/__init__.py` | Test package init |
| `agents/tests/messaging/test_messaging_tools.py` | 37 unit tests across 9 test classes |

### Modified Files

| File | Change |
|------|--------|
| `agents/orchestrator/agent.py` | Added `"messaging": "messaging_agent"` to `DOMAIN_AGENT_MAP`; added `"microsoft.servicebus"` and `"microsoft.eventhub"` to `RESOURCE_TYPE_TO_DOMAIN`; added messaging routing keywords to system prompt; added `messaging_agent` to tool allowlist; added `"messaging"` to `_A2A_DOMAINS` |
| `fabric/kql/functions/classify_domain.kql` | Added `messaging` case before `sre` fallback with Service Bus and Event Hub resource types |
| `services/detection-plane/classify_domain.py` | Added 6 `DOMAIN_MAPPINGS` entries for Service Bus/Event Hub; added `"messaging"` to `VALID_DOMAINS` frozenset |
| `services/api-gateway/models.py` | Added `messaging` to `IncidentPayload.domain` regex pattern |

---

## Tools Implemented

| Tool | SDK | Purpose |
|------|-----|---------|
| `get_servicebus_namespace_health` | `azure-mgmt-servicebus` | Namespace SKU, status, zone redundancy, geo-replication |
| `list_servicebus_queues` | `azure-mgmt-servicebus` | Queue depths, DLQ counts, lock duration, delivery settings |
| `get_servicebus_metrics` | `azure-mgmt-monitor` | Incoming/outgoing messages, throttling, errors, DLQ avg |
| `propose_servicebus_dlq_purge` | (HITL — no SDK) | REMEDI-001 proposal for DLQ purge, `approval_required: True` |
| `get_eventhub_namespace_health` | `azure-mgmt-eventhub` | Namespace SKU, throughput units, Kafka, auto-inflate |
| `list_eventhub_consumer_groups` | `azure-mgmt-eventhub` | Event Hubs + consumer group enumeration per namespace |
| `get_eventhub_metrics` | `azure-mgmt-monitor` | Incoming/outgoing, bytes, throttling, estimated lag count |

---

## Test Results

```
37 passed, 0 failed
```

### Test Classes

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestAllowedMcpTools` | 4 | Count, content, no-wildcards, is-list |
| `TestGetServicebusNamespaceHealth` | 4 | Success, SDK-missing, Azure error, no-SKU |
| `TestListServicebusQueues` | 5 | Success, empty, SDK-missing, Azure error, `count_details=None` |
| `TestGetServicebusMetrics` | 4 | Success, SDK-missing, Azure error, entity_name filter |
| `TestProposeServicebusDlqPurge` | 4 | `approval_required`, `risk_level`, proposed_action, reversibility |
| `TestGetEventhubNamespaceHealth` | 4 | Success, SDK-missing, Azure error, no-SKU |
| `TestListEventhubConsumerGroups` | 5 | Success, empty namespace, SDK-missing, Azure error, empty CGs |
| `TestGetEventhubMetrics` | 4 | Success (lag=100), SDK-missing, Azure error, eventhub_name filter |
| `TestExtractSubscriptionId` | 3 | Valid ID, missing segment, empty string |

---

## Key Implementation Decisions

- **`count_details` None guard**: `list_servicebus_queues` guards `cd = getattr(q, "count_details", None)` — returns `None` fields without crashing when namespace is throttled.
- **`lock_duration` timedelta**: Converted to `lock_duration_seconds` via `ld.total_seconds()`.
- **Consumer lag approximation**: `estimated_lag_count = int(incoming - outgoing)` — documented as approximation; exact per-partition lag requires data-plane SDK with connection string (unavailable in managed-identity agent).
- **HITL safety**: `propose_servicebus_dlq_purge` returns `approval_required: True`, `risk_level: "low"`, irreversibility warning. No SDK call at proposal time.
- **Never-raise pattern**: All tools catch all exceptions, record `duration_ms` in both `try` and `except`, return structured error dicts.
- **API gateway domain validation**: Extended `IncidentPayload.domain` regex to include `messaging` — incidents with this domain will now pass validation instead of being rejected with HTTP 422.

---

## Commits

1. `feat: add agents/messaging/__init__.py package init (Phase 49 Task 1)`
2. `feat: add agents/messaging/requirements.txt (Phase 49 Task 2)`
3. `feat: add agents/messaging/Dockerfile (Phase 49 Task 3)`
4. `feat: add agents/messaging/tools.py with 7 tools (Phase 49 Task 4)`
5. `feat: add agents/messaging/agent.py ChatAgent factory and system prompt (Phase 49 Task 5)`
6. `test: add 37 unit tests for messaging agent tools (Phase 49 Task 6)`
7. `feat: wire messaging domain into orchestrator routing map and A2A domains (Phase 49 Task 7)`
8. `feat: add messaging domain case to classify_domain KQL function (Phase 49 Task 8)`
9. `feat: add messaging domain to detection plane classify_domain and API gateway validation (Phase 49 Task 9)`

---

## Must-Haves Checklist

- [x] `agents/messaging/` package exists with `__init__.py`, `tools.py`, `agent.py`, `requirements.txt`, `Dockerfile`
- [x] `agents/tests/messaging/test_messaging_tools.py` exists with exactly 37 test functions
- [x] All 37 tests pass (`pytest agents/tests/messaging/ -v` exits 0)
- [x] `agents/orchestrator/agent.py` `DOMAIN_AGENT_MAP` contains `"messaging": "messaging_agent"`
- [x] `agents/orchestrator/agent.py` `RESOURCE_TYPE_TO_DOMAIN` contains `"microsoft.servicebus"` and `"microsoft.eventhub"` → `"messaging"`
- [x] `agents/orchestrator/agent.py` `_A2A_DOMAINS` contains `"messaging"`
- [x] `fabric/kql/functions/classify_domain.kql` `case()` contains a `"messaging"` case before the `"sre"` fallback
- [x] `services/detection-plane/classify_domain.py` `VALID_DOMAINS` frozenset contains `"messaging"`
- [x] `services/detection-plane/classify_domain.py` `DOMAIN_MAPPINGS` contains `"microsoft.servicebus"` and `"microsoft.eventhub"` entries
- [x] `propose_servicebus_dlq_purge` always returns `approval_required: True` (verified by test)
- [x] Every tool returns `duration_ms` in both success and error paths (verified by tests)
- [x] `count_details` None guard is present in `list_servicebus_queues` (verified by `test_count_details_none_returns_none_counts` test passing)
- [x] `services/api-gateway/models.py` domain pattern includes `messaging` (bonus — prevents HTTP 422 on messaging incidents)
