# Plan 27-3: Execute Endpoint + Wiring

**Phase:** 27 — Closed-Loop Remediation
**Wave:** 3 (depends on Plan 27-2 — `remediation_executor.py` and new models must exist)
**Requirements:** REMEDI-009, REMEDI-010, REMEDI-011, REMEDI-012, REMEDI-013
**Autonomous:** true

---

## Objective

Wire the remediation executor into `main.py`: add `POST /api/v1/approvals/{id}/execute`, `GET /api/v1/approvals/{id}/verification`, start `run_wal_stale_monitor` in the lifespan context, and extend `GET /api/v1/audit/remediation-export` (mapped to existing `export_audit_report`) to include Cosmos `remediation_audit` records. Add 10+ unit tests.

---

## Context

### Existing endpoint patterns in `main.py`

**Approval endpoints** (lines 1198–1299) are the closest structural neighbors — the execute endpoint sits logically after them:

```python
# Existing pattern to mirror:
@app.post("/api/v1/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_proposal(
    approval_id: str,
    payload: ApprovalAction,
    thread_id: Optional[str] = None,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> ApprovalResponse:
```

**Lifespan pattern** — existing background tasks follow this structure (lines 283–344):
```python
_topology_sync_task = asyncio.create_task(run_topology_sync_loop(...))
# ... at shutdown:
if _topology_sync_task is not None and not _topology_sync_task.done():
    _topology_sync_task.cancel()
    try:
        await _topology_sync_task
    except asyncio.CancelledError:
        pass
```

**Audit export** — existing route (lines 1380–1398):
```python
@app.get("/api/v1/audit/export", response_model=AuditExportResponse)
async def export_audit_report(from_time: str, to_time: str, ...) -> AuditExportResponse:
    report = await generate_remediation_report(from_time=from_time, to_time=to_time)
    return AuditExportResponse(**report)
```

The context specifies a NEW route `/api/v1/audit/remediation-export` for REMEDI-013.
Decision: **add a new route alias** at `/api/v1/audit/remediation-export` that calls an extended version of the report generator (also including Cosmos `remediation_audit` records). The existing `/api/v1/audit/export` route is **not modified** — backward compat preserved.

### `audit_export.py` modification

The existing `generate_remediation_report` reads from OneLake + Cosmos approvals. REMEDI-013 requires a Cosmos-based queryable record. Add a new function `generate_remediation_audit_export` in `audit_export.py` that:
1. Calls existing `_read_onelake_events` (Source 1)
2. Calls existing `_read_approval_records` (Source 2)
3. **New**: reads `remediation_audit` Cosmos container for the time range (Source 3)
4. Merges all three, deduplicating by `execution_id` / `approvalId`

### Dependency injection
- `execute` endpoint needs `cosmos_client` + `credential` from `Depends(get_cosmos_client)` / `Depends(get_credential)`
- `topology_client` comes from `request.app.state.topology_client` (same pattern as `ingest_incident`)
- Both `get_cosmos_client` and `get_credential` are already in `dependencies.py` and used throughout `main.py`

### Models needed
```python
from services.api_gateway.models import RemediationAuditRecord, RemediationResult
```

### Execute endpoint guard logic
Before calling `execute_remediation`:
1. Read approval record from Cosmos — 404 if not found
2. Check `approval_record["status"] == "approved"` — 409 Conflict if not
3. Check approval not expired (`_is_expired` from `approvals.py`) — 410 Gone if expired
4. Delegate to `execute_remediation(...)` — let it handle pre-flight

---

## Files to Modify

### 1. `services/api-gateway/main.py`

#### A. New imports to add (in the imports section, around lines 44–95)

```python
from services.api_gateway.remediation_executor import (
    execute_remediation,
    run_wal_stale_monitor,
)
from services.api_gateway.models import (
    # ... existing imports ...
    RemediationAuditRecord,
    RemediationResult,
)
from services.api_gateway.audit_export import (
    generate_remediation_report,
    generate_remediation_audit_export,   # NEW
)
```

Also add to models import block: `RemediationAuditRecord`, `RemediationResult`.

#### B. Lifespan: start `run_wal_stale_monitor`

Inside `lifespan(app)`, after the forecast sweep task block (around line 322, before `await _run_startup_migrations()`):

```python
# Start WAL stale-monitor background task (REMEDI-011)
_wal_monitor_task = None
if app.state.cosmos_client is not None:
    _wal_monitor_task = asyncio.create_task(
        run_wal_stale_monitor(app.state.cosmos_client)
    )
    logger.info("startup: WAL stale monitor started | interval=300s")
else:
    logger.warning("startup: WAL stale monitor not started (COSMOS_ENDPOINT not set)")
```

In the teardown section (after `await _run_startup_migrations()` → yield → teardown, around line 325):

```python
# Cancel WAL stale monitor on shutdown
if _wal_monitor_task is not None and not _wal_monitor_task.done():
    _wal_monitor_task.cancel()
    try:
        await _wal_monitor_task
    except asyncio.CancelledError:
        pass
    logger.info("shutdown: WAL stale monitor cancelled")
```

#### C. New endpoint: `POST /api/v1/approvals/{approval_id}/execute`

Add after the existing `reject_proposal` endpoint (around line 1267):

```python
@app.post(
    "/api/v1/approvals/{approval_id}/execute",
    response_model=RemediationResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_approval(
    approval_id: str,
    request: Request,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
    credential: Any = Depends(get_credential),
) -> RemediationResult:
    """Execute an approved remediation proposal (REMEDI-009, REMEDI-010, REMEDI-011, REMEDI-012).

    Pre-conditions:
      - approval_id must exist in the approvals container (404 if not)
      - approval status must be 'approved' (409 if pending/rejected/expired/executed)
      - approval must not be expired (410 if expired)

    Runs pre-flight blast-radius check, writes WAL, executes ARM action,
    schedules verification BackgroundTask (fires in VERIFICATION_DELAY_MINUTES).

    Returns RemediationResult with execution_id and verification_scheduled=True.

    Authentication: Entra ID Bearer token required.
    """
    from services.api_gateway.approvals import _get_approvals_container, _is_expired
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    # Read approval record
    approvals_container = _get_approvals_container(cosmos_client=cosmos_client)
    try:
        # approval records are partitioned by thread_id; need thread_id from query param
        # For execute, we cross-partition query since we only have approval_id
        records = list(approvals_container.query_items(
            query="SELECT * FROM c WHERE c.id = @approval_id",
            parameters=[{"name": "@approval_id", "value": approval_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        logger.error("execute_approval: cosmos read failed | approval_id=%s error=%s", approval_id, exc)
        raise HTTPException(status_code=500, detail="Failed to read approval record")

    if not records:
        raise HTTPException(status_code=404, detail="Approval not found")

    approval_record = records[0]

    # Status guard
    if _is_expired(approval_record):
        raise HTTPException(status_code=410, detail="Approval has expired")

    if approval_record["status"] != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot execute approval in status: {approval_record['status']}. Must be 'approved'.",
        )

    # Resolve topology client from app state
    topology_client = getattr(request.app.state, "topology_client", None)

    try:
        result = await execute_remediation(
            approval_id=approval_id,
            credential=credential,
            cosmos_client=cosmos_client,
            topology_client=topology_client,
            approval_record=approval_record,
        )
    except Exception as exc:
        logger.error(
            "execute_approval: execution failed | approval_id=%s error=%s",
            approval_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Remediation execution failed")

    # Update approval status to "executed" (best-effort, non-blocking)
    try:
        approvals_container.patch_item(
            item=approval_id,
            partition_key=approval_record["thread_id"],
            patch_operations=[
                {"op": "add", "path": "/status", "value": "executed"},
                {"op": "add", "path": "/executed_at", "value": result.execution_id},
            ],
        )
    except Exception as exc:
        logger.warning(
            "execute_approval: approval status update failed (non-fatal) | approval_id=%s error=%s",
            approval_id, exc,
        )

    return result
```

#### D. New endpoint: `GET /api/v1/approvals/{approval_id}/verification`

Add immediately after `execute_approval`:

```python
@app.get(
    "/api/v1/approvals/{approval_id}/verification",
    response_model=RemediationAuditRecord,
)
async def get_verification_result(
    approval_id: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> RemediationAuditRecord:
    """Get the verification result for an executed remediation (REMEDI-009).

    Reads from the remediation_audit Cosmos container.
    Returns 202 with retry_after=60 if verification has not yet completed
    (verification_result is still None after WAL record is written).
    Returns 404 if no execution record exists for this approval_id.

    Authentication: Entra ID Bearer token required.
    """
    from services.api_gateway.remediation_executor import _get_remediation_audit_container

    container = _get_remediation_audit_container(cosmos_client)
    try:
        records = list(container.query_items(
            query="SELECT * FROM c WHERE c.approval_id = @approval_id",
            parameters=[{"name": "@approval_id", "value": approval_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        logger.error(
            "get_verification_result: cosmos query failed | approval_id=%s error=%s",
            approval_id, exc,
        )
        raise HTTPException(status_code=500, detail="Failed to query remediation audit")

    # Filter to the primary execution record (action_type="execute"), not rollback records
    execution_records = [r for r in records if r.get("action_type") == "execute"]

    if not execution_records:
        raise HTTPException(status_code=404, detail="No execution record found for this approval")

    record = execution_records[-1]  # most recent if somehow multiple

    # Verification not yet complete — return 202
    if record.get("verification_result") is None:
        return JSONResponse(
            content={
                "execution_id": record["id"],
                "approval_id": approval_id,
                "verification_result": None,
                "status": "pending_verification",
            },
            status_code=202,
            headers={"Retry-After": "60"},
        )

    # Strip Cosmos internal fields
    clean = {k: v for k, v in record.items() if not k.startswith("_")}
    return RemediationAuditRecord(**clean)
```

#### E. New route: `GET /api/v1/audit/remediation-export` (REMEDI-013)

Add after the existing `export_audit_report` endpoint (around line 1398):

```python
@app.get("/api/v1/audit/remediation-export", response_model=AuditExportResponse)
async def export_remediation_audit(
    from_time: str,
    to_time: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> AuditExportResponse:
    """Export immutable remediation audit trail for compliance (REMEDI-013).

    Combines OneLake remediation events + Cosmos approval records +
    Cosmos remediation_audit WAL records. The remediation_audit Cosmos
    records are the authoritative source for automated ARM actions.

    Args:
        from_time: ISO 8601 start of period (required).
        to_time: ISO 8601 end of period (required).

    Authentication: Entra ID Bearer token required.
    """
    report = await generate_remediation_audit_export(
        from_time=from_time,
        to_time=to_time,
        cosmos_client=cosmos_client,
    )
    return AuditExportResponse(**report)
```

---

### 2. `services/api-gateway/audit_export.py`

Add new function `generate_remediation_audit_export` and helper `_read_remediation_audit_records`.

#### `_read_remediation_audit_records(from_time, to_time, cosmos_client) -> list[dict]`

```python
async def _read_remediation_audit_records(
    from_time: str,
    to_time: str,
    cosmos_client: Optional[Any],
) -> list[dict]:
    """Read execution records from the Cosmos remediation_audit container."""
    if cosmos_client is None:
        logger.debug("Cosmos not available — skipping remediation_audit read")
        return []
    try:
        from services.api_gateway.remediation_executor import _get_remediation_audit_container

        container = _get_remediation_audit_container(cosmos_client)
        query = (
            "SELECT * FROM c WHERE "
            "c.executed_at >= @from_time AND c.executed_at <= @to_time"
        )
        items = list(container.query_items(
            query=query,
            parameters=[
                {"name": "@from_time", "value": from_time},
                {"name": "@to_time", "value": to_time},
            ],
            enable_cross_partition_query=True,
        ))
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]
    except Exception as exc:
        logger.error("Failed to read remediation_audit records: %s", exc)
        return []
```

#### `generate_remediation_audit_export(from_time, to_time, cosmos_client) -> dict`

```python
async def generate_remediation_audit_export(
    from_time: str,
    to_time: str,
    cosmos_client: Optional[Any] = None,
) -> dict[str, Any]:
    """Generate REMEDI-013 compliance export combining all three audit sources.

    Sources:
      1. OneLake remediation events (REMEDI-007)
      2. Cosmos approvals (approval chain)
      3. Cosmos remediation_audit WAL records (authoritative for automated ARM actions)
    """
    # Source 1: OneLake
    onelake_events = await _read_onelake_events(from_time, to_time)
    # Source 2: Cosmos approvals
    approval_map = await _read_approval_records(from_time, to_time)
    # Source 3: Cosmos remediation_audit (NEW)
    audit_records = await _read_remediation_audit_records(from_time, to_time, cosmos_client)

    # Index audit records by approval_id for merge
    audit_by_approval: dict[str, dict] = {}
    for rec in audit_records:
        approval_id = rec.get("approval_id", "")
        if approval_id:
            audit_by_approval[approval_id] = rec

    # Build enriched event list
    # Start with OneLake events, enrich with approval chain + WAL data
    enriched_events: list[dict] = []
    seen_approval_ids: set[str] = set()

    for event in onelake_events:
        approval_id = event.get("approvalId", "")
        approval = approval_map.get(approval_id, {})
        audit_rec = audit_by_approval.get(approval_id, {})
        seen_approval_ids.add(approval_id)
        enriched_events.append({
            **event,
            "approval_chain": {
                "proposed_at": approval.get("proposed_at", ""),
                "decided_at": approval.get("decided_at", ""),
                "decided_by": approval.get("decided_by", ""),
                "status": approval.get("status", event.get("outcome", "")),
                "expires_at": approval.get("expires_at", ""),
            },
            "execution_audit": {
                "execution_id": audit_rec.get("id", ""),
                "status": audit_rec.get("status", ""),
                "verification_result": audit_rec.get("verification_result"),
                "verified_at": audit_rec.get("verified_at"),
                "rolled_back": audit_rec.get("rolled_back", False),
                "preflight_blast_radius_size": audit_rec.get("preflight_blast_radius_size", 0),
            } if audit_rec else None,
        })

    # Add any Cosmos audit records not already covered by OneLake events
    for audit_rec in audit_records:
        approval_id = audit_rec.get("approval_id", "")
        if approval_id in seen_approval_ids:
            continue
        approval = approval_map.get(approval_id, {})
        enriched_events.append({
            "timestamp": audit_rec.get("executed_at", ""),
            "agentId": "",
            "toolName": audit_rec.get("proposed_action", ""),
            "toolParameters": {},
            "approvedBy": audit_rec.get("executed_by", ""),
            "outcome": audit_rec.get("status", ""),
            "durationMs": 0,
            "correlationId": "",
            "threadId": audit_rec.get("thread_id", ""),
            "approvalId": approval_id,
            "approval_chain": {
                "proposed_at": approval.get("proposed_at", ""),
                "decided_at": approval.get("decided_at", ""),
                "decided_by": approval.get("decided_by", ""),
                "status": approval.get("status", ""),
                "expires_at": approval.get("expires_at", ""),
            },
            "execution_audit": {
                "execution_id": audit_rec.get("id", ""),
                "status": audit_rec.get("status", ""),
                "verification_result": audit_rec.get("verification_result"),
                "verified_at": audit_rec.get("verified_at"),
                "rolled_back": audit_rec.get("rolled_back", False),
                "preflight_blast_radius_size": audit_rec.get("preflight_blast_radius_size", 0),
            },
        })

    return {
        "report_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period": {"from": from_time, "to": to_time},
            "total_events": len(enriched_events),
            "sources": ["onelake", "cosmos_approvals", "cosmos_remediation_audit"],
        },
        "remediation_events": enriched_events,
    }
```

---

## Unit Tests

**File:** `tests/api_gateway/test_execute_endpoint.py`

### Minimum 10 test cases

#### Execute endpoint tests (5)
```
test_execute_returns_404_for_missing_approval
  - Mock approvals container query returns []
  - POST /api/v1/approvals/missing-id/execute
  - Assert 404

test_execute_returns_410_for_expired_approval
  - Mock approval record with expires_at in the past, status="approved"
  - Assert 410 Gone

test_execute_returns_409_for_non_approved_status
  - Mock approval record with status="pending"
  - Assert 409 Conflict with message containing "Must be 'approved'"

test_execute_returns_409_for_rejected_status
  - Mock approval record with status="rejected"
  - Assert 409 Conflict

test_execute_returns_202_on_success
  - Mock approval record with status="approved", not expired
  - Mock execute_remediation to return RemediationResult(
        execution_id="uuid", status="complete",
        verification_scheduled=True, preflight_passed=True, blast_radius_size=3)
  - POST /api/v1/approvals/{id}/execute
  - Assert 202 Accepted
  - Assert response body has execution_id, verification_scheduled=True
```

#### Verification endpoint tests (3)
```
test_verification_returns_404_when_no_execution_record
  - Mock remediation_audit query returns []
  - GET /api/v1/approvals/{id}/verification
  - Assert 404

test_verification_returns_202_while_pending
  - Mock remediation_audit query returns [{"id": "...", "action_type": "execute",
      "verification_result": None, ...}]
  - Assert 202 with Retry-After: 60 header
  - Assert response body has verification_result=None

test_verification_returns_200_with_classification
  - Mock remediation_audit query returns [{"id": "...", "action_type": "execute",
      "verification_result": "RESOLVED", "status": "complete", ...all required fields}]
  - Assert 200
  - Assert response body has verification_result="RESOLVED"
```

#### Audit export endpoint tests (2)
```
test_remediation_export_returns_200_with_merged_sources
  - Mock generate_remediation_audit_export to return valid report dict
  - GET /api/v1/audit/remediation-export?from_time=...&to_time=...
  - Assert 200
  - Assert response body has report_metadata.sources containing "cosmos_remediation_audit"
  - Assert remediation_events is a list

test_remediation_export_includes_cosmos_audit_records
  - Mock _read_onelake_events → []
  - Mock _read_approval_records → {}
  - Mock _read_remediation_audit_records → [one execution record]
  - Call generate_remediation_audit_export directly
  - Assert returned remediation_events has 1 item
  - Assert item["execution_audit"]["execution_id"] matches the mock record's id
```

---

## Implementation Steps

- [ ] Read `services/api-gateway/main.py` (verify current import block and last line of file)
- [ ] Read `services/api-gateway/audit_export.py` (verify current function list)
- [ ] Add `RemediationAuditRecord`, `RemediationResult` to models import block in `main.py`
- [ ] Add `execute_remediation`, `run_wal_stale_monitor` imports from `remediation_executor`
- [ ] Add `generate_remediation_audit_export` import from `audit_export`
- [ ] Add WAL monitor task creation + teardown to lifespan (after forecast sweep block)
- [ ] Add `execute_approval` endpoint after `reject_proposal`
- [ ] Add `get_verification_result` endpoint after `execute_approval`
- [ ] Add `export_remediation_audit` endpoint after existing `export_audit_report`
- [ ] Add `_read_remediation_audit_records` function to `audit_export.py`
- [ ] Add `generate_remediation_audit_export` function to `audit_export.py`
- [ ] Write `tests/api_gateway/test_execute_endpoint.py` with 10+ tests
- [ ] Run `pytest tests/api_gateway/test_execute_endpoint.py -v` — all tests must pass
- [ ] Run `pytest tests/api_gateway/test_remediation_executor.py -v` — confirm 27-2 tests still pass
- [ ] Run full test suite `pytest tests/ -x --tb=short` — no regressions

---

## Verification Checklist

- [ ] `POST /api/v1/approvals/{id}/execute` returns 404 for missing approval
- [ ] `POST /api/v1/approvals/{id}/execute` returns 409 for non-approved status
- [ ] `POST /api/v1/approvals/{id}/execute` returns 410 for expired approval
- [ ] `POST /api/v1/approvals/{id}/execute` returns 202 on success with `execution_id` in body
- [ ] `GET /api/v1/approvals/{id}/verification` returns 202 + `Retry-After: 60` while pending
- [ ] `GET /api/v1/approvals/{id}/verification` returns 200 + `RemediationAuditRecord` when complete
- [ ] `GET /api/v1/audit/remediation-export` returns 200 with `sources` list including `"cosmos_remediation_audit"`
- [ ] Existing `GET /api/v1/audit/export` is unchanged and still passes its tests
- [ ] `run_wal_stale_monitor` task is created in lifespan log: `startup: WAL stale monitor started | interval=300s`
- [ ] All 10+ new tests pass
- [ ] No existing tests regress
- [ ] `from __future__ import annotations` preserved at top of `main.py` (it is already there)

---

## Constraints

- **Do not modify existing endpoints** — `approve_proposal`, `reject_proposal`, `export_audit_report` are unchanged.
- **Do not rename** `GET /api/v1/audit/export` — new route is a separate `remediation-export` path.
- **`topology_client` is Optional** — the execute endpoint must not 503 when topology is unavailable; pre-flight degrades gracefully (see Plan 27-2 preflight design).
- **Cross-partition query for execute** — approval records are partitioned by `thread_id` but the execute endpoint only receives `approval_id`; cross-partition query is acceptable here (low frequency, operator-triggered, not machine-to-machine hot path).
- **Approval status update is best-effort** — if patching the approval to `"executed"` fails, the execution result is still returned; do not raise 500 for this.
- **File size** — `main.py` is currently ~1419 lines. The additions will bring it to ~1530 lines. Still under the 800-line guideline per file — however, note that `main.py` already exceeds the 800-line ceiling from the common coding style. The additions are minimal and do not warrant a file split within this phase (defer router extraction to a future refactoring phase).
