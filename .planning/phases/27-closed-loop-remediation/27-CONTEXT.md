# Phase 27: Closed-Loop Remediation - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning
**Mode:** Auto-generated (new service + API phase — discuss skipped)

<domain>
## Phase Boundary

Complete the remediation loop: Incident → Triage → RCA → Runbook Selection → Proposal → Human Approval → Pre-flight Checks → **Execution → Verification → Resolution OR Rollback**.

**Requirements:**
- REMEDI-009: Closed-loop verification step fires within 10 min after execution; classified RESOLVED / IMPROVED / DEGRADED / TIMEOUT
- REMEDI-010: Pre-flight blast-radius check required; aborts if new failures detected post-approval
- REMEDI-011: Write-ahead log: audit record written status:pending before ARM call; pending records >10 min trigger operator alert
- REMEDI-012: Auto-rollback triggered when verification returns DEGRADED
- REMEDI-013: Immutable audit trail for every automated action; exportable for compliance

**What this phase does:**
1. `services/api-gateway/remediation_executor.py` — orchestrates execution, WAL, verification, rollback
2. New Cosmos container `remediation_audit` (immutable — no update/delete) + Terraform
3. New endpoints: `POST /api/v1/approvals/{id}/execute`, `GET /api/v1/approvals/{id}/verification`
4. Pre-flight check using topology blast_radius before ARM call
5. Verification BackgroundTask: poll resource health 10 min after execution → RESOLVED/IMPROVED/DEGRADED/TIMEOUT
6. Auto-rollback on DEGRADED: reverse the ARM operation (stop VM that was started, etc.)
7. WAL: write `status:pending` to remediation_audit BEFORE the ARM call; update to `status:complete/failed` after
8. Pending-WAL alert: background task checks for pending records > 10 min and emits REMEDI_WAL_ALERT incident
9. `GET /api/v1/audit/remediation-export` endpoint — returns immutable audit records for compliance (REMEDI-013)

**What this phase does NOT do:**
- Does not add UI execution panel (deferred)
- Does not change the HITL approval flow (existing approve/reject endpoints unchanged)
- Does not support Kubernetes remediation (ARM-only scope)

</domain>

<decisions>
## Implementation Decisions

### Cosmos DB `remediation_audit` container (REMEDI-013: immutable)
- Partition key: `/incident_id`
- No update/delete ever issued against this container (WAL append + status-update allowed only in WAL pattern)
- WAL pattern: write `{status: "pending", ...}` BEFORE ARM call, then `replace_item` to `{status: "complete"}` AFTER

### remediation_executor.py core flow
```python
async def execute_remediation(
    approval_id: str,
    credential: Any,
    cosmos_client: CosmosClient,
    topology_client: Optional[TopologyClient],
    approval_record: dict,
) -> RemediationResult:
    # 1. Pre-flight: get blast_radius, check for new active incidents on same resource (REMEDI-010)
    # 2. Write WAL record status=pending (REMEDI-011)
    # 3. Execute ARM action (from approval_record.proposed_action)
    # 4. Update WAL record status=complete or status=failed
    # 5. Schedule verification BackgroundTask for 10 min later (REMEDI-009)
    # 6. Return RemediationResult
```

### ARM execution (scoped — only safe reversible actions)
```python
SAFE_ARM_ACTIONS = {
    "restart_vm":   {"arm_op": "restart", "rollback_op": None},    # idempotent
    "deallocate_vm":{"arm_op": "deallocate", "rollback_op": "start"},
    "start_vm":     {"arm_op": "start", "rollback_op": "deallocate"},
    "resize_vm":    {"arm_op": "resize", "rollback_op": "resize_to_original"},
}
```
Use `azure.mgmt.compute.ComputeManagementClient` for VM operations.

### Verification (REMEDI-009): fires 10 min after execution
```python
async def verify_remediation(incident_id, resource_id, execution_id, credential, cosmos_client):
    # Query Azure Resource Health for the resource
    # Classify: RESOLVED (healthy, no active incidents), IMPROVED (health better),
    #           DEGRADED (new failures), TIMEOUT (still unhealthy after 10 min)
    # Store classification on WAL record
    # If DEGRADED → trigger rollback (REMEDI-012)
```

### Auto-rollback (REMEDI-012)
- When `verification_result = DEGRADED`: execute the `rollback_op` from SAFE_ARM_ACTIONS
- Write rollback WAL record with `action_type: "rollback"`
- Update original execution record with `rolled_back: True, rollback_execution_id`

### RemediationResult and RemediationAuditRecord Pydantic models
```python
class RemediationAuditRecord(BaseModel):
    id: str                    # execution_id
    incident_id: str
    approval_id: str
    thread_id: str
    action_type: str           # execute | rollback
    proposed_action: str       # "restart_vm", "deallocate_vm", etc.
    resource_id: str
    executed_by: str           # UPN from approval
    executed_at: str
    status: str                # pending | complete | failed
    verification_result: Optional[str]  # RESOLVED | IMPROVED | DEGRADED | TIMEOUT | None
    verified_at: Optional[str]
    rolled_back: bool = False
    rollback_execution_id: Optional[str]
    preflight_blast_radius_size: int
    wal_written_at: str

class RemediationResult(BaseModel):
    execution_id: str
    status: str
    verification_scheduled: bool
    preflight_passed: bool
    blast_radius_size: int
```

### Pending WAL alert
Background task (every 5 min): query remediation_audit for `status=pending AND wal_written_at < now-10min`
If any found: emit REMEDI_WAL_ALERT incident via incident ingestion

### POST /api/v1/approvals/{id}/execute
- Requires approval status = 'approved' (not pending/rejected/expired)
- Runs pre-flight (REMEDI-010)
- Calls execute_remediation
- Returns RemediationResult

### Compliance export (REMEDI-013)
`GET /api/v1/audit/remediation-export?from_time=X&to_time=Y` — already exists at `GET /api/v1/audit/export` but returns from OneLake. Extend to also include remediation_audit Cosmos records (more reliable than OneLake for this).

</decisions>

<code_context>
## Existing Code Insights

### approvals.py pattern
- `_get_approvals_container` — same pattern needed for `_get_remediation_audit_container`
- Approval record has `proposed_action: str`, `thread_id`, `decided_by`
- After approval: `status = "approved"`, approval record in Cosmos `approvals` container

### remediation_logger.py
- Already writes to OneLake — `log_remediation_event(event)` is fire-and-forget
- REMEDI-013 requires a second, queryable immutable Cosmos record (not just OneLake)

### Azure Compute SDK (already imported in diagnostic_pipeline.py)
```python
from azure.mgmt.compute import ComputeManagementClient
```

### Azure Resource Health (already used)
```python
from azure.mgmt.resourcehealth import MicrosoftResourceHealth
```

### Topology integration
`topology_client.get_blast_radius(resource_id)` — returns `{affected_resources: [...], hop_counts: {...}}`
Used for REMEDI-010 pre-flight.

### Existing audit export
`services/api-gateway/audit_export.py` — `generate_remediation_report()` reads from OneLake
REMEDI-013 adds a Cosmos-based export alongside this.

### Environment variables
- `REMEDIATION_EXECUTION_ENABLED` (default: "true") — safety flag
- `VERIFICATION_DELAY_MINUTES` (default: "10")
- `WAL_STALE_ALERT_MINUTES` (default: "10")

</code_context>

<deferred>
## Deferred

- UI execution panel (deferred)
- Kubernetes remediation (ARM-only scope)
- Multi-step remediation playbooks (single-action scope for this phase)
- Cost estimation pre-flight (Phase 28)

</deferred>

---
*Phase: 27-closed-loop-remediation*
*Context gathered: 2026-04-03 via autonomous mode*
