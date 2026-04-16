# Plan 51-2: Policy Evaluation Engine + Safety Guards + restart_container_app Action

---
wave: 2
depends_on: ["51-1"]
files_modified:
  - services/api-gateway/remediation_executor.py
  - services/api-gateway/policy_engine.py
  - services/api-gateway/approvals.py
  - services/api-gateway/models.py
  - services/api-gateway/tests/test_policy_engine.py
autonomous: true
---

<threat_model>
## Threat Model

**Assets:** Production Azure resources subject to auto-remediation; safety guard integrity

**Threat actors:**
- Rogue policies bypassing HITL for high-blast-radius actions
- Race conditions between daily cap counter and concurrent auto-approvals
- Container App restart targeting wrong app due to resource ID parsing error

**Key risks and mitigations:**
1. **Auto-remediation on protected resources** — MITIGATED: `aap-protected: true` tag check is NON-NEGOTIABLE first guard; always blocks before any policy evaluation
2. **Blast-radius exceeds policy cap** — MITIGATED: Policy `max_blast_radius` (1-50) overrides the hardcoded 50 limit with a MORE restrictive per-policy cap; uses existing `_run_preflight()` topology check
3. **Daily cap bypass via race** — MITIGATED: Cosmos cross-partition count query may lag by seconds; acceptable for daily cap (not a hard safety boundary); documented in research
4. **DEGRADED rollback bypassed** — MITIGATED: `_classify_verification()` and auto-rollback logic in `_verify_remediation()` are UNCHANGED — DEGRADED always triggers rollback regardless of policy
5. **Container App restart on wrong target** — MITIGATED: `_parse_arm_resource_id()` already extracts resource group + name from ARM ID; stop/start uses exact resource group + app name
</threat_model>

## Goal

Build the policy evaluation engine (`policy_engine.py`), integrate it into the approval flow, add the `restart_container_app` action class to `SAFE_ARM_ACTIONS`, and ensure all safety guards are enforced.

## Tasks

<task id="51-2-01">
<title>Create policy_engine.py with evaluate_auto_approval()</title>
<read_first>
- services/api-gateway/remediation_executor.py (SAFE_ARM_ACTIONS, _run_preflight, _parse_arm_resource_id)
- services/api-gateway/models.py (AutoRemediationPolicy model)
- services/api-gateway/runbook_rag.py (resolve_postgres_dsn)
</read_first>
<action>
Create `services/api-gateway/policy_engine.py` with the following function:

```python
async def evaluate_auto_approval(
    action_class: str,
    resource_id: str,
    resource_tags: dict,
    topology_client: Optional[Any],
    cosmos_client: Optional[Any],
    credential: Optional[Any],
) -> tuple[bool, Optional[str], str]:
```

Returns `(auto_approved, policy_id, reason)`.

**Evaluation flow (in order):**

1. **`aap-protected` tag check** — if `resource_tags.get("aap-protected") == "true"`, return `(False, None, "resource_tagged_aap_protected")`. This is the non-negotiable emergency brake.

2. **Query PostgreSQL** for enabled policies matching `action_class`:
   ```sql
   SELECT * FROM remediation_policies WHERE action_class = $1 AND enabled = true
   ```
   Use `asyncpg.connect(dsn)` with `resolve_postgres_dsn()`. If no policies match, return `(False, None, "no_matching_policy")`.

3. **For each matching policy** (first match wins):
   a. **Tag filter check**: every key-value pair in `policy.resource_tag_filter` must be present in `resource_tags`. If not, skip to next policy.
   b. **Blast-radius check**: call `topology_client.get_blast_radius(resource_id, 3)` if available. If `total_affected > policy.max_blast_radius`, skip to next policy. If topology_client is None, use blast_radius_size=0 (pass).
   c. **Daily execution cap**: query Cosmos `remediation_audit` container:
      ```
      SELECT VALUE COUNT(1) FROM c
      WHERE c.auto_approved_by_policy = @policy_id
      AND c.executed_at >= @today_start
      AND c.action_type = 'execute'
      ```
      Where `@today_start` is `datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()`.
      If count >= `policy.max_daily_executions`, skip to next policy.
   d. **SLO health gate** (if `policy.require_slo_healthy`): check Azure Resource Health via `azure.mgmt.resourcehealth.MicrosoftResourceHealth`. If availability_state != "Available", skip to next policy. Run in thread executor. If credential is None, skip this check (pass).
   e. If all guards pass, return `(True, str(policy.id), "policy_match")`.

4. If no policy passes all guards, return `(False, None, "guards_failed")`.

All exceptions within guard checks should be caught, logged as warnings, and treated as guard-FAILURE (conservative — do not auto-approve on error).

Import `COSMOS_REMEDIATION_AUDIT_CONTAINER` and `COSMOS_DATABASE_NAME` from `services.api_gateway.remediation_executor`.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/policy_engine.py`
- File contains `async def evaluate_auto_approval(`
- File contains `aap-protected` check as the FIRST guard
- File contains `resource_tags.get("aap-protected")` or equivalent
- File contains `SELECT * FROM remediation_policies WHERE action_class = $1 AND enabled = true`
- File contains `auto_approved_by_policy` (Cosmos daily cap query)
- File contains `MicrosoftResourceHealth` or `resourcehealth` (SLO health gate)
- File contains `topology_client.get_blast_radius` (blast-radius guard)
- File contains `return (True,` (auto-approve path)
- File contains `return (False,` (at least 3 rejection paths)
- `python -c "import ast; ast.parse(open('services/api-gateway/policy_engine.py').read())"` exits 0
</acceptance_criteria>
</task>

<task id="51-2-02">
<title>Add restart_container_app to SAFE_ARM_ACTIONS and _execute_arm_action</title>
<read_first>
- services/api-gateway/remediation_executor.py (SAFE_ARM_ACTIONS dict line 31, _execute_arm_action function line 176)
</read_first>
<action>
In `services/api-gateway/remediation_executor.py`:

1. Add to `SAFE_ARM_ACTIONS` dict (after the `resize_vm` entry):
```python
"restart_container_app": {"arm_op": "restart_container_app", "rollback_op": None},
```

2. Add a new branch in `_sync_arm_call()` inside `_execute_arm_action()` (after the `resize_to_original` elif block, before the `else` block):
```python
elif arm_op == "restart_container_app":
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    ca_client = ContainerAppsAPIClient(credential, subscription_id)
    # Container Apps has no direct restart API; stop + start pattern
    poller = ca_client.container_apps.begin_stop(resource_group, vm_name)
    poller.result(timeout=120)
    poller = ca_client.container_apps.begin_start(resource_group, vm_name)
    poller.result(timeout=120)
```

Note: `vm_name` variable is actually `resource_name` (the last segment of the ARM resource ID), which works correctly for Container Apps as well.
</action>
<acceptance_criteria>
- `services/api-gateway/remediation_executor.py` contains `"restart_container_app": {"arm_op": "restart_container_app", "rollback_op": None}`
- `services/api-gateway/remediation_executor.py` contains `elif arm_op == "restart_container_app":`
- `services/api-gateway/remediation_executor.py` contains `ContainerAppsAPIClient`
- `services/api-gateway/remediation_executor.py` contains `begin_stop(resource_group`
- `services/api-gateway/remediation_executor.py` contains `begin_start(resource_group`
</acceptance_criteria>
</task>

<task id="51-2-03">
<title>Add auto_approved_by_policy field to RemediationAuditRecord</title>
<read_first>
- services/api-gateway/models.py (RemediationAuditRecord class, around line 456)
</read_first>
<action>
In `services/api-gateway/models.py`, add a new optional field to the `RemediationAuditRecord` class after the `wal_written_at` field:

```python
auto_approved_by_policy: Optional[str] = Field(
    default=None,
    description="Policy ID when auto-approved by policy engine; None when HITL-approved",
)
```
</action>
<acceptance_criteria>
- `services/api-gateway/models.py` contains `auto_approved_by_policy: Optional[str]`
- `services/api-gateway/models.py` contains `"Policy ID when auto-approved by policy engine"`
</acceptance_criteria>
</task>

<task id="51-2-04">
<title>Integrate policy evaluation into approval flow</title>
<read_first>
- services/api-gateway/approvals.py (create_approval function)
- services/api-gateway/policy_engine.py (evaluate_auto_approval from task 51-2-01)
- services/api-gateway/remediation_executor.py (execute_remediation function, line 732)
- services/api-gateway/remediation_logger.py (build_remediation_event, log_remediation_event)
</read_first>
<action>
In `services/api-gateway/approvals.py`, modify the `create_approval()` function to check for auto-approval BEFORE creating the pending approval record.

Add the following logic at the beginning of `create_approval()`, after the initial field extraction but BEFORE writing the approval record to Cosmos:

```python
# --- Phase 51: Policy auto-approval check ---
try:
    from services.api_gateway.policy_engine import evaluate_auto_approval

    # Extract resource tags from the proposal or resource_snapshot
    resource_tags = {}
    resource_snapshot = approval_data.get("resource_snapshot", {})
    if resource_snapshot:
        resource_tags = resource_snapshot.get("tags", {})

    # Extract resource_id from proposal.target_resources
    proposal = approval_data.get("proposal", {})
    target_resources = proposal.get("target_resources", [])
    resource_id = target_resources[0] if target_resources else ""
    action_class = proposal.get("action", "")

    if resource_id and action_class:
        auto_approved, policy_id, reason = await evaluate_auto_approval(
            action_class=action_class,
            resource_id=resource_id,
            resource_tags=resource_tags,
            topology_client=topology_client,
            cosmos_client=cosmos_client,
            credential=credential,
        )
        if auto_approved and policy_id:
            logger.info(
                "create_approval: auto-approved by policy | "
                "policy_id=%s action_class=%s resource_id=%s",
                policy_id, action_class, resource_id,
            )
            # Synthesize approval record for execute_remediation
            synthesized_record = {
                **approval_data,
                "decided_by": f"policy:{policy_id}",
                "decided_at": datetime.now(timezone.utc).isoformat(),
                "status": "approved",
                "auto_approved_by_policy": policy_id,
            }
            # Execute directly, bypassing HITL
            result = await execute_remediation(
                approval_id=f"auto-policy-{policy_id}",
                credential=credential,
                cosmos_client=cosmos_client,
                topology_client=topology_client,
                approval_record=synthesized_record,
            )
            return {
                "approval_id": f"auto-policy-{policy_id}",
                "status": "auto_approved",
                "policy_id": policy_id,
                "execution_result": result,
            }
except Exception as exc:
    logger.warning(
        "create_approval: policy evaluation failed (falling through to HITL) | error=%s",
        exc,
    )
# --- End Phase 51 ---
```

The `topology_client` and `credential` must be available in the function scope. If they are not currently parameters of `create_approval()`, add them as optional parameters with `Optional[Any] = None` defaults.

Also update the WAL base record construction in `execute_remediation()` to include `auto_approved_by_policy`:
In `services/api-gateway/remediation_executor.py`, after building `wal_base` dict (around line 812-826), add:
```python
"auto_approved_by_policy": approval_record.get("auto_approved_by_policy"),
```
</action>
<acceptance_criteria>
- `services/api-gateway/approvals.py` contains `from services.api_gateway.policy_engine import evaluate_auto_approval`
- `services/api-gateway/approvals.py` contains `auto_approved, policy_id, reason = await evaluate_auto_approval(`
- `services/api-gateway/approvals.py` contains `"decided_by": f"policy:{policy_id}"`
- `services/api-gateway/approvals.py` contains `"status": "auto_approved"`
- `services/api-gateway/remediation_executor.py` contains `"auto_approved_by_policy"` in the `wal_base` dict
</acceptance_criteria>
</task>

<task id="51-2-05">
<title>Write unit tests for policy evaluation engine</title>
<read_first>
- services/api-gateway/policy_engine.py (from task 51-2-01)
- services/api-gateway/tests/test_remediation_executor.py (test pattern reference)
</read_first>
<action>
Create `services/api-gateway/tests/test_policy_engine.py` with at least 12 unit tests covering all guard paths:

1. `test_aap_protected_always_blocks` — resource with `aap-protected: true` tag returns `(False, None, "resource_tagged_aap_protected")`
2. `test_no_matching_policy` — no enabled policies for action_class returns `(False, None, "no_matching_policy")`
3. `test_policy_match_all_guards_pass` — matching policy with all guards passing returns `(True, policy_id, "policy_match")`
4. `test_tag_filter_mismatch` — policy requires `tier: dev` but resource has `tier: prod` — skips that policy
5. `test_blast_radius_exceeds_cap` — topology returns blast_radius > max_blast_radius — skips policy
6. `test_blast_radius_no_topology` — topology_client is None — blast radius check passes (size=0)
7. `test_daily_cap_exceeded` — Cosmos returns count >= max_daily_executions — skips policy
8. `test_daily_cap_not_exceeded` — Cosmos returns count < max_daily_executions — passes
9. `test_slo_health_unavailable` — Resource Health returns "Unavailable" — skips policy (when require_slo_healthy=True)
10. `test_slo_health_check_disabled` — policy has require_slo_healthy=False — passes regardless of health status
11. `test_first_policy_wins` — two policies match; first one passes all guards — returns first policy's ID
12. `test_exception_in_guard_rejects` — exception during blast-radius check treated as guard failure (conservative)

Mock `asyncpg.connect()`, `resolve_postgres_dsn()`, Cosmos client, topology_client, and `MicrosoftResourceHealth` using `unittest.mock.patch` and `MagicMock`.

Use `@pytest.mark.asyncio` for all tests. Each test should directly call `evaluate_auto_approval()`.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/tests/test_policy_engine.py`
- File contains at least 12 test functions matching `def test_`
- File contains `test_aap_protected_always_blocks`
- File contains `test_no_matching_policy`
- File contains `test_policy_match_all_guards_pass`
- File contains `test_tag_filter_mismatch`
- File contains `test_blast_radius_exceeds_cap`
- File contains `test_daily_cap_exceeded`
- File contains `test_slo_health_unavailable`
- File contains `test_slo_health_check_disabled`
- File contains `test_first_policy_wins`
- File contains `test_exception_in_guard_rejects`
- `python -m pytest services/api-gateway/tests/test_policy_engine.py --tb=short` exits 0
</acceptance_criteria>
</task>

## Verification

After all tasks complete:
- `python -c "from services.api_gateway.remediation_executor import SAFE_ARM_ACTIONS; assert 'restart_container_app' in SAFE_ARM_ACTIONS"` — new action registered
- `python -m pytest services/api-gateway/tests/test_policy_engine.py -v` — all 12+ tests pass
- `grep -c "aap-protected" services/api-gateway/policy_engine.py` — returns ≥1 (emergency brake)
- `grep "auto_approved_by_policy" services/api-gateway/remediation_executor.py` — field present in WAL

## must_haves
- [ ] `policy_engine.py` with `evaluate_auto_approval()` function implementing all 5 guards
- [ ] `aap-protected: true` tag ALWAYS blocks auto-approval (non-negotiable)
- [ ] Blast-radius guard uses policy-specific `max_blast_radius` cap (1-50)
- [ ] Daily execution cap enforced via Cosmos `remediation_audit` count query
- [ ] SLO health gate checks Azure Resource Health when `require_slo_healthy=True`
- [ ] `restart_container_app` added to `SAFE_ARM_ACTIONS` with `rollback_op: None`
- [ ] Container Apps stop+start implementation in `_execute_arm_action()`
- [ ] `auto_approved_by_policy` field on `RemediationAuditRecord` and in WAL records
- [ ] Policy evaluation integrated into `create_approval()` before HITL gate
- [ ] DEGRADED verification STILL triggers auto-rollback regardless of policy
- [ ] ≥12 unit tests covering all guard paths
