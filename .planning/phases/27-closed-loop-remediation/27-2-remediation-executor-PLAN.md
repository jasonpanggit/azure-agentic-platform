# Plan 27-2: Remediation Executor Service

**Phase:** 27 — Closed-Loop Remediation
**Wave:** 2 (depends on Plan 27-1 — `remediation_audit` container must exist)
**Requirements:** REMEDI-009, REMEDI-010, REMEDI-011, REMEDI-012
**Autonomous:** true

---

## Objective

Create `services/api-gateway/remediation_executor.py` — the core orchestration module that closes the remediation loop: pre-flight → WAL write → ARM execution → WAL update → verification scheduling → auto-rollback. Add `RemediationAuditRecord` and `RemediationResult` Pydantic models to `models.py`. Write 15+ unit tests.

---

## Context

### Existing code touchpoints

**`approvals.py`**
- `_get_approvals_container(cosmos_client)` → pattern to replicate for `_get_remediation_audit_container`
- Approval record fields available at execution time: `proposed_action`, `thread_id`, `incident_id`, `decided_by`, `proposal` (dict with `target_resources`, `tool_parameters`)

**`models.py`**
- All models extend `pydantic.BaseModel`; use `Field(...)` for required, `Optional[str] = None` for optional
- File is 429 lines — new models should be appended after `ForecastResult`

**`remediation_logger.py`**
- `log_remediation_event(event)` — fire-and-forget OneLake write; keep calling this from executor for REMEDI-007 continuity
- `build_remediation_event(approval_record, outcome, duration_ms, correlation_id)` — reuse to build OneLake event

**`diagnostic_pipeline.py`** (reference only)
- Already imports `from azure.mgmt.compute import ComputeManagementClient`
- Already imports `from azure.mgmt.resourcehealth import MicrosoftResourceHealth`
- Executor must import these same packages — no new dependencies required

**`topology_client`**
- `topology_client.get_blast_radius(resource_id, max_depth=3)` → `{"total_affected": int, "affected_resources": [...], "hop_counts": {...}}`
- Used in pre-flight blast-radius check (REMEDI-010)

### Environment variables
```
REMEDIATION_EXECUTION_ENABLED   default: "true"   — master safety switch
VERIFICATION_DELAY_MINUTES      default: "10"      — delay before verification fires
WAL_STALE_ALERT_MINUTES         default: "10"      — age threshold for stale WAL alert
COSMOS_DATABASE_NAME            default: "aap"     — shared with approvals.py
COSMOS_REMEDIATION_AUDIT_CONTAINER  default: "remediation_audit"
```

### ARM resource ID parsing
Resource IDs follow the pattern:
```
/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}
```
Parse: `parts = resource_id.split("/")`  → `sub=parts[2]`, `rg=parts[4]`, `vm_name=parts[-1]`

---

## Files to Modify / Create

### 1. `services/api-gateway/models.py` — Add two models

Append after the `ForecastResult` class (end of file, line 429):

```python
class RemediationAuditRecord(BaseModel):
    """WAL and immutable audit record written to Cosmos remediation_audit (REMEDI-011, REMEDI-013)."""

    id: str                                       # execution_id (UUID)
    incident_id: str
    approval_id: str
    thread_id: str
    action_type: str                              # "execute" | "rollback"
    proposed_action: str                          # "restart_vm" | "deallocate_vm" | "start_vm" | "resize_vm"
    resource_id: str
    executed_by: str                              # UPN from approval record (decided_by)
    executed_at: str                              # ISO 8601 UTC
    status: str                                   # "pending" | "complete" | "failed"
    verification_result: Optional[str] = None    # "RESOLVED" | "IMPROVED" | "DEGRADED" | "TIMEOUT"
    verified_at: Optional[str] = None
    rolled_back: bool = False
    rollback_execution_id: Optional[str] = None
    preflight_blast_radius_size: int
    wal_written_at: str                           # ISO 8601 UTC — written BEFORE ARM call


class RemediationResult(BaseModel):
    """Result returned by execute_remediation to the API endpoint (REMEDI-009, REMEDI-010)."""

    execution_id: str
    status: str                                   # "complete" | "failed" | "aborted"
    verification_scheduled: bool
    preflight_passed: bool
    blast_radius_size: int
    abort_reason: Optional[str] = None           # populated when status="aborted"
```

---

### 2. `services/api-gateway/remediation_executor.py` — New file

**Full module structure:**

```python
"""Remediation executor — closed-loop ARM execution with WAL, verification, and auto-rollback.

Flow per execution:
  1. Pre-flight: blast-radius check + new active incident scan (REMEDI-010)
  2. Write WAL record status=pending BEFORE ARM call (REMEDI-011)
  3. Execute ARM action via ComputeManagementClient
  4. Update WAL record status=complete|failed
  5. Schedule verification BackgroundTask (fires after VERIFICATION_DELAY_MINUTES, REMEDI-009)
  6. Verification: classify RESOLVED/IMPROVED/DEGRADED/TIMEOUT via Azure Resource Health
  7. Auto-rollback on DEGRADED (REMEDI-012)

Background task:
  run_wal_stale_monitor — every 5 min, alerts on pending WAL records > WAL_STALE_ALERT_MINUTES old
"""
```

#### Module-level constants

```python
SAFE_ARM_ACTIONS: dict[str, dict[str, Optional[str]]] = {
    "restart_vm":    {"arm_op": "restart",           "rollback_op": None},
    "deallocate_vm": {"arm_op": "deallocate",         "rollback_op": "start"},
    "start_vm":      {"arm_op": "start",              "rollback_op": "deallocate"},
    "resize_vm":     {"arm_op": "resize",             "rollback_op": "resize_to_original"},
}
```

#### `_get_remediation_audit_container(cosmos_client)`

Mirror `_get_approvals_container` from `approvals.py`:
- Falls back to creating a `CosmosClient` from `COSMOS_ENDPOINT` env var if `cosmos_client` is None
- Returns `database.get_container_client(COSMOS_REMEDIATION_AUDIT_CONTAINER)` where the container name defaults to `"remediation_audit"`

#### `_write_wal(execution_id, incident_id, approval_id, thread_id, action_type, proposed_action, resource_id, executed_by, executed_at, preflight_blast_radius_size, cosmos_client, status="pending", **kwargs) -> RemediationAuditRecord`

- Builds a `RemediationAuditRecord` dict
- Sets `wal_written_at = datetime.now(timezone.utc).isoformat()`
- Calls `container.create_item(body=record_dict)` for initial `status=pending` write
- For updates (status → complete/failed/verification result): calls `container.replace_item(item=execution_id, body=updated_dict)`
- Returns the `RemediationAuditRecord`
- **Never raises** — logs errors and returns partial record; WAL failure must not abort execution

```python
async def _write_wal(
    execution_id: str,
    cosmos_client: Optional[CosmosClient],
    *,
    status: str = "pending",
    update_fields: Optional[dict] = None,
    base_record: Optional[dict] = None,
) -> None:
    """Write or update a WAL record in the remediation_audit container.

    - Initial write: pass base_record (full RemediationAuditRecord dict), status="pending"
    - Update: pass execution_id + update_fields dict, omit base_record
    Always uses replace_item for updates (preserves immutability — no delete).
    """
```

#### `_run_preflight(resource_id, topology_client, cosmos_client) -> tuple[bool, int, str]`

Returns `(passed: bool, blast_radius_size: int, reason: str)`

Logic:
1. Call `topology_client.get_blast_radius(resource_id, 3)` → get `total_affected`
2. If `topology_client` is None: skip blast-radius, `blast_radius_size = 0`
3. Query `cosmos_client` incidents container for active (non-resolved, non-suppressed) incidents on the same `resource_id` that were **created after the approval was issued** — if any new ones exist, return `(False, blast_radius_size, "new_active_incidents_detected")`
4. If blast_radius_size > 50: return `(False, blast_radius_size, "blast_radius_exceeds_limit")`
5. Otherwise: return `(True, blast_radius_size, "ok")`

```python
async def _run_preflight(
    resource_id: str,
    approval_issued_at: str,
    topology_client: Optional[Any],
    cosmos_client: Optional[CosmosClient],
) -> tuple[bool, int, str]:
```

#### `_execute_arm_action(action_type, resource_id, credential, params) -> dict`

Parses subscription_id, resource_group, vm_name from resource_id ARM path.
Uses `ComputeManagementClient(credential, subscription_id)`.

Action dispatch:
```python
match arm_op:
    case "restart":
        poller = compute_client.virtual_machines.begin_restart(rg, vm_name)
        poller.result(timeout=120)
    case "deallocate":
        poller = compute_client.virtual_machines.begin_deallocate(rg, vm_name)
        poller.result(timeout=180)
    case "start":
        poller = compute_client.virtual_machines.begin_start(rg, vm_name)
        poller.result(timeout=180)
    case "resize":
        new_size = params.get("vm_size")
        vm = compute_client.virtual_machines.get(rg, vm_name)
        vm.hardware_profile.vm_size = new_size
        poller = compute_client.virtual_machines.begin_create_or_update(rg, vm_name, vm)
        poller.result(timeout=300)
    case "resize_to_original":
        original_size = params.get("original_vm_size")
        vm = compute_client.virtual_machines.get(rg, vm_name)
        vm.hardware_profile.vm_size = original_size
        poller = compute_client.virtual_machines.begin_create_or_update(rg, vm_name, vm)
        poller.result(timeout=300)
```

All ARM calls run in a thread executor via `asyncio.get_running_loop().run_in_executor(None, _sync_arm_call)` to avoid blocking the event loop.

Returns `{"success": bool, "arm_op": str, "resource_id": str, "error": Optional[str]}`.

#### `_classify_verification(resource_health_status, pre_execution_status) -> str`

Pure function mapping resource health response to verification classification:
```
"Available" + was previously "Unavailable" or "Degraded" → "RESOLVED"
"Available" + was already "Available"                     → "IMPROVED"  (minor improvement)
"Unavailable" or "Degraded"                              → "DEGRADED"
still "Unknown" after delay                              → "TIMEOUT"
```

#### `_verify_remediation(execution_id, resource_id, incident_id, credential, cosmos_client) -> str`

Runs after `VERIFICATION_DELAY_MINUTES` delay:
1. Query Azure Resource Health: `MicrosoftResourceHealth(credential, subscription_id).availability_statuses.get_by_resource(resource_uri, api_version="2023-07-01")`
2. Read original WAL record from `remediation_audit` to get `pre_execution_health` (if stored) or default to "Unknown"
3. Call `_classify_verification(current_status, pre_execution_status)` → get classification string
4. Call `_write_wal(execution_id, cosmos_client, update_fields={"verification_result": classification, "verified_at": now})`
5. Log the classification
6. If classification == "DEGRADED": trigger `_rollback(execution_id, resource_id, ...)`
7. Return classification string

Run in executor thread for the Resource Health SDK call (sync SDK).

```python
async def _verify_remediation(
    execution_id: str,
    resource_id: str,
    incident_id: str,
    proposed_action: str,
    credential: Any,
    cosmos_client: Optional[CosmosClient],
) -> str:
```

#### `_rollback(execution_id, resource_id, proposed_action, credential, cosmos_client) -> Optional[str]`

REMEDI-012: triggered when `verification_result = DEGRADED`.

1. Look up `rollback_op` from `SAFE_ARM_ACTIONS[proposed_action]`
2. If `rollback_op` is None (e.g. `restart_vm` is idempotent — no rollback): log and return None
3. Generate `rollback_execution_id = str(uuid.uuid4())`
4. Write rollback WAL record: `action_type="rollback"`, `status="pending"`
5. Call `_execute_arm_action(rollback_op, resource_id, credential, params={})`
6. Update rollback WAL record: `status="complete"` or `"failed"`
7. Update original execution WAL record: `rolled_back=True, rollback_execution_id=rollback_execution_id`
8. Return `rollback_execution_id`

```python
async def _rollback(
    execution_id: str,
    resource_id: str,
    incident_id: str,
    approval_id: str,
    thread_id: str,
    executed_by: str,
    proposed_action: str,
    credential: Any,
    cosmos_client: Optional[CosmosClient],
) -> Optional[str]:
```

#### `execute_remediation(approval_id, credential, cosmos_client, topology_client, approval_record) -> RemediationResult`

Main orchestration function called by the API endpoint:

```python
async def execute_remediation(
    approval_id: str,
    credential: Any,
    cosmos_client: Optional[CosmosClient],
    topology_client: Optional[Any],
    approval_record: dict,
) -> RemediationResult:
```

Full flow:
```
1. Check REMEDIATION_EXECUTION_ENABLED env var — return aborted result if "false"
2. Extract fields from approval_record:
   - incident_id = approval_record.get("incident_id", "")
   - thread_id = approval_record["thread_id"]
   - proposed_action = approval_record.get("proposed_action") or approval_record["proposal"].get("action")
   - resource_id = approval_record["proposal"]["target_resources"][0]
   - executed_by = approval_record["decided_by"]
   - approval_issued_at = approval_record.get("decided_at", "")
3. Validate proposed_action is in SAFE_ARM_ACTIONS — return aborted if not
4. Run _run_preflight(resource_id, approval_issued_at, topology_client, cosmos_client)
   - If not passed: return RemediationResult(status="aborted", preflight_passed=False, ...)
5. execution_id = str(uuid.uuid4())
6. executed_at = datetime.now(timezone.utc).isoformat()
7. _write_wal(execution_id, cosmos_client, status="pending", base_record={...full record...})
8. arm_result = await _execute_arm_action(proposed_action, resource_id, credential, params)
9. wal_status = "complete" if arm_result["success"] else "failed"
10. await _write_wal(execution_id, cosmos_client, update_fields={"status": wal_status})
11. Fire-and-forget: log_remediation_event(build_remediation_event(...)) for OneLake (REMEDI-007)
12. Schedule verification as asyncio background task:
    asyncio.create_task(_delayed_verify(execution_id, resource_id, ...))
13. Return RemediationResult(
        execution_id=execution_id,
        status=wal_status,
        verification_scheduled=True,
        preflight_passed=True,
        blast_radius_size=blast_radius_size,
    )
```

Where `_delayed_verify` is:
```python
async def _delayed_verify(execution_id, resource_id, incident_id, proposed_action, credential, cosmos_client):
    delay = int(os.environ.get("VERIFICATION_DELAY_MINUTES", "10")) * 60
    await asyncio.sleep(delay)
    await _verify_remediation(execution_id, resource_id, incident_id, proposed_action, credential, cosmos_client)
```

#### `run_wal_stale_monitor(cosmos_client, interval_seconds=300)`

REMEDI-011 background task started in lifespan:

```python
async def run_wal_stale_monitor(
    cosmos_client: Optional[CosmosClient],
    interval_seconds: int = 300,
) -> None:
    """Background loop: every 5 min, find pending WAL records older than WAL_STALE_ALERT_MINUTES.

    For each stale record found, emit a REMEDI_WAL_ALERT incident via the
    incident ingestion path to trigger operator notification.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        if cosmos_client is None:
            continue
        try:
            stale_minutes = int(os.environ.get("WAL_STALE_ALERT_MINUTES", "10"))
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
            container = _get_remediation_audit_container(cosmos_client)
            query = (
                "SELECT c.id, c.incident_id, c.approval_id, c.wal_written_at "
                "FROM c WHERE c.status = 'pending' AND c.wal_written_at < @cutoff"
            )
            stale_records = list(container.query_items(
                query=query,
                parameters=[{"name": "@cutoff", "value": cutoff}],
                enable_cross_partition_query=True,
            ))
            for record in stale_records:
                logger.error(
                    "REMEDI_WAL_ALERT: stale pending WAL record | "
                    "execution_id=%s incident_id=%s wal_written_at=%s",
                    record["id"], record.get("incident_id"), record.get("wal_written_at"),
                )
                # Emit alert incident (best-effort, non-blocking)
                await _emit_wal_alert(record, cosmos_client)
        except Exception as exc:
            logger.error("run_wal_stale_monitor: error | %s", exc)
```

`_emit_wal_alert` writes a minimal incident record to the Cosmos `incidents` container with:
- `incident_id = f"REMEDI_WAL_ALERT_{execution_id[:8]}"`
- `severity = "Sev1"`
- `domain = "sre"`
- `status = "new"`
- `title = f"Stale remediation WAL record detected: {execution_id}"`

---

## Unit Tests

**File:** `tests/api_gateway/test_remediation_executor.py`

### Test groupings and minimum 15 test cases

#### WAL write tests (3)
```
test_write_wal_creates_pending_record
  - Mock CosmosClient; call _write_wal with status="pending"
  - Assert create_item called once with status="pending" and wal_written_at set

test_write_wal_updates_existing_record
  - Mock CosmosClient; call _write_wal with update_fields={"status": "complete"}
  - Assert replace_item called (not create_item)

test_write_wal_never_raises_on_cosmos_error
  - Mock CosmosClient.create_item to raise CosmosHttpResponseError
  - Assert _write_wal returns without raising
```

#### Pre-flight tests (4)
```
test_preflight_passes_when_no_new_incidents_and_small_blast_radius
  - topology_client returns total_affected=5; cosmos query returns []
  - Assert (True, 5, "ok")

test_preflight_fails_on_new_active_incident
  - cosmos query returns [{"incident_id": "abc", "status": "new"}]
  - Assert (False, _, "new_active_incidents_detected")

test_preflight_fails_on_large_blast_radius
  - topology_client returns total_affected=51
  - Assert (False, 51, "blast_radius_exceeds_limit")

test_preflight_passes_when_topology_unavailable
  - topology_client=None
  - Assert passed=True, blast_radius_size=0
```

#### Verification classification tests (4)
```
test_classify_verification_resolved
  - _classify_verification("Available", "Unavailable") == "RESOLVED"

test_classify_verification_improved
  - _classify_verification("Available", "Available") == "IMPROVED"

test_classify_verification_degraded
  - _classify_verification("Unavailable", "Available") == "DEGRADED"

test_classify_verification_timeout
  - _classify_verification("Unknown", "Unknown") == "TIMEOUT"
```

#### Rollback trigger tests (2)
```
test_rollback_triggered_on_degraded
  - Mock _execute_arm_action to succeed; mock _write_wal
  - Call _rollback with proposed_action="deallocate_vm"
  - Assert _execute_arm_action called with "start" (the rollback_op)
  - Assert returned rollback_execution_id is a UUID string

test_rollback_skipped_for_idempotent_action
  - Call _rollback with proposed_action="restart_vm" (rollback_op=None)
  - Assert _execute_arm_action NOT called
  - Assert return value is None
```

#### execute_remediation orchestration tests (3)
```
test_execute_remediation_returns_aborted_when_disabled
  - Set REMEDIATION_EXECUTION_ENABLED="false"
  - Assert result.status == "aborted"
  - Assert _write_wal NOT called

test_execute_remediation_returns_aborted_on_preflight_failure
  - Mock _run_preflight to return (False, 5, "new_active_incidents_detected")
  - Assert result.status == "aborted", result.preflight_passed == False
  - Assert _execute_arm_action NOT called

test_execute_remediation_full_happy_path
  - Mock _run_preflight → (True, 3, "ok")
  - Mock _execute_arm_action → {"success": True, ...}
  - Mock _write_wal (no-op)
  - Call execute_remediation with a minimal approval_record dict
  - Assert result.status == "complete"
  - Assert result.execution_id is a UUID
  - Assert result.verification_scheduled == True
  - Assert result.preflight_passed == True
  - Assert result.blast_radius_size == 3
```

#### WAL stale monitor test (1)
```
test_wal_stale_monitor_emits_alert_for_stale_records
  - Mock cosmos container to return one pending record with wal_written_at 15 min ago
  - Mock _emit_wal_alert
  - Run one iteration of the monitor loop (patch asyncio.sleep to no-op)
  - Assert _emit_wal_alert called once with the stale record
```

---

## Dependency Notes

All Azure SDK packages are already in the project's requirements:
- `azure-mgmt-compute` — `ComputeManagementClient` (already used in `diagnostic_pipeline.py`)
- `azure-mgmt-resourcehealth` — `MicrosoftResourceHealth` (already used in project)
- `azure-cosmos` — `CosmosClient`, `ContainerProxy` (already used across gateway)
- `azure-identity` — `DefaultAzureCredential` (already used)

No new `pip install` needed.

---

## Code Quality Checklist

- [ ] All functions have type annotations
- [ ] `logger = logging.getLogger(__name__)` at module level
- [ ] No function exceeds 50 lines
- [ ] `_execute_arm_action` offloads sync ARM calls to thread executor
- [ ] `_write_wal` never raises (logs and returns on error)
- [ ] `run_wal_stale_monitor` catches all exceptions to prevent loop death
- [ ] Env vars read once at call time (not module load) for testability
- [ ] `from __future__ import annotations` at top of file
- [ ] No hardcoded container names — use `COSMOS_REMEDIATION_AUDIT_CONTAINER` constant with default

---

## Handoff to Plan 27-3

Plan 27-3 imports from this module:
```python
from services.api_gateway.remediation_executor import (
    execute_remediation,
    run_wal_stale_monitor,
)
from services.api_gateway.models import RemediationAuditRecord, RemediationResult
```
