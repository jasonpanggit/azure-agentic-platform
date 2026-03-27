# 04-03 SUMMARY: Detection Service — Dedup, Alert State, Payload Mapping, Gateway Integration

**Plan:** 04-03
**Phase:** 04 — Detection Plane
**Date:** 2026-03-26
**Requirements:** DETECT-003, DETECT-005, DETECT-006

---

## What Was Built

### Task 4-03-01: Detection Plane Models (`services/detection-plane/models.py`)
- `AlertStatus` enum: `new`, `acknowledged`, `closed`
- `IncidentRecord` Pydantic model — full Cosmos DB document schema with D-13 fields
- `StatusHistoryEntry` — per-transition actor + timestamp record
- `CorrelatedAlert` — D-12 correlated alert schema
- `VALID_TRANSITIONS` state machine: `new→{acknowledged,closed}`, `acknowledged→{closed}`, `closed→{}` (terminal)

### Task 4-03-02: Two-Layer Deduplication (`services/detection-plane/dedup.py`)
- **Layer 1 (`dedup_layer1`):** Time-window collapse — same `resource_id + detection_rule` within 5-minute window collapses into existing record
- **Layer 2 (`dedup_layer2`):** Open-incident correlation — new distinct alert for resource with open incident appended to `correlated_alerts`
- `collapse_duplicate` — increments `duplicate_count` with ETag optimistic concurrency (`match_condition="IfMatch"`)
- `correlate_alert` — appends to `correlated_alerts` array with ETag optimistic concurrency
- `create_incident_record` — creates new Cosmos DB document with `status=new` and initial `status_history` entry
- `DedupResult` dataclass — structured dedup result with `is_duplicate`, `existing_record`, `layer` fields
- Execution order: Layer 1 → Layer 2 → create new; ETag retry logic with `MAX_DEDUP_RETRIES=3`

### Task 4-03-03: Alert State Lifecycle (`services/detection-plane/alert_state.py`)
- `transition_alert_state` — validates transition against `VALID_TRANSITIONS`, appends to `status_history`, ETag concurrency
- `InvalidTransitionError` — raised for invalid transitions (e.g., `closed → new`)
- `sync_alert_state_to_azure_monitor` — fire-and-forget Azure Monitor state sync; failures logged but never raised
- `_AZURE_MONITOR_STATE_MAP` — maps `acknowledged→"Acknowledged"`, `closed→"Closed"`; `new` has no Azure Monitor mapping (skip)

### Task 4-03-04: Payload Mapper (`services/detection-plane/payload_mapper.py`)
- `map_detection_result_to_incident_payload` — transforms DetectionResults row to IncidentPayload dict
- `det-` prefix on `incident_id` for traceability (`det-{alert_id}`)
- `_extract_subscription_id` — extracts subscription ID from ARM resource ID path
- Raises `ValueError` for missing `alert_id` or `resource_id`
- Builds human-readable `title` from `alert_rule` + `resource_name`

### Task 4-03-05: Fabric User Data Function (`fabric/user-data-function/`)
- `__init__.py` — empty module marker
- `main.py` — Fabric Activator trigger handler:
  - `handle_activator_trigger` — entry point; maps payload, acquires token, POSTs to gateway
  - `get_access_token` — MSAL `ConfidentialClientApplication` client credentials flow using `FABRIC_SP_CLIENT_ID`, `FABRIC_SP_CLIENT_SECRET`, `FABRIC_SP_TENANT_ID`, `GATEWAY_APP_SCOPE`
  - `map_detection_result_to_payload` — self-contained mapping copy (no detection-plane import dependency in Fabric runtime)
  - Posts to `{API_GATEWAY_URL}/api/v1/incidents` with `Authorization: Bearer` header
- `requirements.txt` — `msal>=1.28.0`, `requests>=2.31.0`

### Task 4-03-06: API Gateway Dedup Integration
- `services/api-gateway/dedup_integration.py` — thin integration layer:
  - `check_dedup` — calls Layer 1 then Layer 2 then creates new record; returns `None` for no-duplicate path
  - Returns `{"status": "deduplicated"}` for Layer 1 hits, `{"status": "correlated"}` for Layer 2 hits
  - Non-blocking: import failures and exceptions caught and logged, returns `None`
  - Adds detection-plane to `sys.path` for Cosmos imports
- `services/api-gateway/main.py` — modified `ingest_incident`:
  - Dedup check runs before Foundry dispatch
  - Returns early with `IncidentResponse` when `dedup_result is not None`
  - Existing 202/503/500 response paths unchanged

### Task 4-03-07: Unit Tests (37 tests, all passing)
- `test_dedup.py` (16 tests) — `TestDedupLayer1` (5), `TestDedupLayer2` (3), `TestCollapseDuplicate` (3), `TestCorrelateAlert` (2), `TestCreateIncidentRecord` (3)
- `test_alert_state.py` (11 tests) — `TestTransitionAlertState` (8), `TestSyncAlertStateToAzureMonitor` (3)
- `test_payload_mapper.py` (10 tests) — all 4 severity levels, all 6 domains, `det-` prefix, subscription extraction, optional field handling

---

## Verification Results

```
cd services/detection-plane && python3 -m pytest tests/unit/ -v
======================== 37 passed, 1 warning in 0.51s =========================
```

### Must-Haves Checklist

- [x] IncidentRecord Pydantic model with D-13 schema (DETECT-005, DETECT-006)
- [x] VALID_TRANSITIONS state machine: `new→{acknowledged,closed}`, `acknowledged→{closed}`, `closed→{}` (DETECT-006)
- [x] Layer 1 dedup: same resource_id + detection_rule within 5-min window collapses (DETECT-005)
- [x] Layer 2 dedup: new alert for resource_id with open incident is correlated (DETECT-005)
- [x] ETag optimistic concurrency on all Cosmos DB writes (DETECT-005)
- [x] InvalidTransitionError raised for invalid state transitions (DETECT-006)
- [x] Bidirectional sync to Azure Monitor (fire-and-forget, non-blocking) (DETECT-006)
- [x] DetectionResults → IncidentPayload mapping with `det-` prefix (DETECT-003)
- [x] Fabric User Data Function with MSAL client credentials flow (DETECT-003)
- [x] API gateway dedup check runs before Foundry dispatch (DETECT-005)
- [x] Unit tests: dedup (16 tests), alert state (11 tests), payload mapper (10 tests) — 37 total

---

## Files Created/Modified

| File | Status |
|---|---|
| `services/detection-plane/models.py` | NEW |
| `services/detection-plane/dedup.py` | NEW |
| `services/detection-plane/alert_state.py` | NEW |
| `services/detection-plane/payload_mapper.py` | NEW |
| `fabric/user-data-function/__init__.py` | NEW |
| `fabric/user-data-function/main.py` | NEW |
| `fabric/user-data-function/requirements.txt` | NEW |
| `services/api-gateway/dedup_integration.py` | NEW |
| `services/api-gateway/main.py` | MODIFIED |
| `services/detection-plane/tests/unit/test_dedup.py` | NEW |
| `services/detection-plane/tests/unit/test_alert_state.py` | NEW |
| `services/detection-plane/tests/unit/test_payload_mapper.py` | NEW |

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Dedup check is non-blocking in gateway | COSMOS_ENDPOINT absent → skip dedup silently; ImportError → skip silently; prevents dedup bugs from taking down incident ingestion |
| Fire-and-forget Azure Monitor sync | Platform state transition must never block on external sync; logged but not raised |
| Self-contained UDF mapping copy | Fabric runtime cannot import services/detection-plane; duplicate kept intentionally small and clearly commented |
| `det-` prefix on incident_id | Provides traceability: any incident ID starting with `det-` was created via the detection plane (vs. manual/API ingestion) |
| Immutable dict patterns throughout | `{**record, "key": new_value}` — no in-place mutation of Cosmos records; consistent with existing `budget.py` pattern |
