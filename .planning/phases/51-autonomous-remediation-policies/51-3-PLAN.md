# Plan 51-3: Learning Suggestion Engine

---
wave: 2
depends_on: ["51-1"]
files_modified:
  - terraform/modules/databases/cosmos.tf
  - terraform/modules/databases/outputs.tf
  - services/api-gateway/suggestion_engine.py
  - services/api-gateway/admin_endpoints.py
  - services/api-gateway/main.py
  - services/api-gateway/tests/test_suggestion_engine.py
autonomous: true
---

<threat_model>
## Threat Model

**Assets:** Operator experience — suggestions should be helpful, not noisy; Cosmos DB write throughput

**Threat actors:**
- Runaway suggestion engine flooding Cosmos with suggestions
- Operator creating a policy from a misleading suggestion (5 identical actions that happened to succeed, but on unique circumstances)

**Key risks and mitigations:**
1. **Suggestion spam** — MITIGATED: 6-hour sweep interval (max 4 suggestions/day); 30-day TTL on Cosmos container; threshold requires 5 approvals + 0 rollbacks (conservative)
2. **Misleading suggestions** — MITIGATED: Suggestions are dismissible; no auto-creation of policies; operator must explicitly convert; UI shows approval count + rollback count for informed decision
3. **Cosmos write costs** — MITIGATED: Suggestions are rare (few distinct action_class+tag patterns); TTL auto-expires old suggestions; partition key on `action_class` limits fan-out
</threat_model>

## Goal

Build the learning suggestion engine that detects repeated HITL-approved remediation patterns and suggests creating auto-approval policies. Includes new Cosmos DB container, background sweep, and API endpoints.

## Tasks

<task id="51-3-01">
<title>Add policy_suggestions Cosmos container to Terraform</title>
<read_first>
- terraform/modules/databases/cosmos.tf (pattern for existing containers like remediation_audit, pattern_analysis)
- terraform/modules/databases/outputs.tf
</read_first>
<action>
In `terraform/modules/databases/cosmos.tf`, add a new container resource after the existing `business_tiers` container:

```hcl
resource "azurerm_cosmosdb_sql_container" "policy_suggestions" {
  name                  = "policy_suggestions"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/action_class"]
  partition_key_version = 2
  default_ttl           = 2592000  # 30 days in seconds

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }

    excluded_path {
      path = "/\"_etag\"/?"
    }
  }
}
```

In `terraform/modules/databases/outputs.tf`, add:
```hcl
output "cosmos_policy_suggestions_container_name" {
  value = azurerm_cosmosdb_sql_container.policy_suggestions.name
}
```
</action>
<acceptance_criteria>
- `terraform/modules/databases/cosmos.tf` contains `resource "azurerm_cosmosdb_sql_container" "policy_suggestions"`
- `terraform/modules/databases/cosmos.tf` contains `partition_key_paths   = ["/action_class"]`
- `terraform/modules/databases/cosmos.tf` contains `default_ttl           = 2592000`
- `terraform/modules/databases/outputs.tf` contains `cosmos_policy_suggestions_container_name`
- `cd terraform && terraform fmt -check modules/databases/cosmos.tf` exits 0
- `cd terraform && terraform fmt -check modules/databases/outputs.tf` exits 0
</acceptance_criteria>
</task>

<task id="51-3-02">
<title>Create suggestion_engine.py with pattern detection</title>
<read_first>
- services/api-gateway/pattern_analyzer.py (background sweep loop pattern)
- services/api-gateway/remediation_executor.py (COSMOS_REMEDIATION_AUDIT_CONTAINER, COSMOS_DATABASE_NAME)
- services/api-gateway/models.py (PolicySuggestion model)
</read_first>
<action>
Create `services/api-gateway/suggestion_engine.py` with:

1. **Constants:**
```python
SUGGESTION_APPROVAL_THRESHOLD = int(os.environ.get("SUGGESTION_APPROVAL_THRESHOLD", "5"))
SUGGESTION_SWEEP_INTERVAL_SECONDS = int(os.environ.get("SUGGESTION_SWEEP_INTERVAL_SECONDS", "21600"))  # 6 hours
COSMOS_POLICY_SUGGESTIONS_CONTAINER = os.environ.get("COSMOS_POLICY_SUGGESTIONS_CONTAINER", "policy_suggestions")
```

2. **`async def run_suggestion_sweep(cosmos_client: Optional[Any]) -> list[dict]`:**
   - Query `remediation_audit` container for HITL-approved executions (where `auto_approved_by_policy IS NOT DEFINED OR auto_approved_by_policy = null`):
     ```
     SELECT c.proposed_action, c.resource_id, c.verification_result, c.executed_at
     FROM c
     WHERE c.action_type = 'execute'
     AND c.status = 'complete'
     AND (NOT IS_DEFINED(c.auto_approved_by_policy) OR c.auto_approved_by_policy = null)
     AND c.executed_at >= @thirty_days_ago
     ```
   - Group by `proposed_action` (action_class)
   - For each group, count total executions and rollbacks (verification_result == "DEGRADED")
   - If total >= `SUGGESTION_APPROVAL_THRESHOLD` and rollbacks == 0:
     - Check if a suggestion for this `action_class` already exists in `policy_suggestions` container (not dismissed)
     - If not, create a new suggestion:
       ```python
       suggestion = {
           "id": str(uuid.uuid4()),
           "action_class": action_class,
           "resource_pattern": {},  # could be enriched with common tags later
           "approval_count": total_count,
           "rollback_count": 0,
           "suggested_at": datetime.now(timezone.utc).isoformat(),
           "dismissed": False,
           "converted_to_policy_id": None,
           "message": f"Consider creating a policy for '{action_class}' — approved {total_count} times with 0 rollbacks in the last 30 days.",
       }
       ```
     - Upsert into `policy_suggestions` container
   - Return list of new suggestions created

3. **`async def run_suggestion_sweep_loop(cosmos_client: Optional[Any], interval_seconds: int = SUGGESTION_SWEEP_INTERVAL_SECONDS) -> None`:**
   - Infinite loop: sleep interval_seconds, then call `run_suggestion_sweep(cosmos_client)`
   - Catch `asyncio.CancelledError` and re-raise
   - Catch all other exceptions, log error, continue loop

4. **`async def get_pending_suggestions(cosmos_client: Optional[Any]) -> list[dict]`:**
   - Query `policy_suggestions` container:
     ```
     SELECT * FROM c WHERE c.dismissed = false AND (NOT IS_DEFINED(c.converted_to_policy_id) OR c.converted_to_policy_id = null)
     ```
   - Return list of suggestion dicts

5. **`async def dismiss_suggestion(cosmos_client: Optional[Any], suggestion_id: str, action_class: str) -> bool`:**
   - Read suggestion from container using `suggestion_id` and partition key `action_class`
   - Update `dismissed = True`
   - Return True on success, False on failure

6. **`async def convert_suggestion_to_policy(cosmos_client: Optional[Any], suggestion_id: str, action_class: str, policy_id: str) -> bool`:**
   - Read suggestion from container using `suggestion_id` and partition key `action_class`
   - Update `converted_to_policy_id = policy_id`
   - Return True on success, False on failure
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/suggestion_engine.py`
- File contains `SUGGESTION_APPROVAL_THRESHOLD`
- File contains `async def run_suggestion_sweep(`
- File contains `async def run_suggestion_sweep_loop(`
- File contains `async def get_pending_suggestions(`
- File contains `async def dismiss_suggestion(`
- File contains `async def convert_suggestion_to_policy(`
- File contains `auto_approved_by_policy` in the Cosmos query (to exclude auto-approved records)
- File contains `"Consider creating a policy for"` (human-readable message)
- File contains `COSMOS_POLICY_SUGGESTIONS_CONTAINER`
- `python -c "import ast; ast.parse(open('services/api-gateway/suggestion_engine.py').read())"` exits 0
</acceptance_criteria>
</task>

<task id="51-3-03">
<title>Add suggestion API endpoints to admin_endpoints.py</title>
<read_first>
- services/api-gateway/admin_endpoints.py (from Plan 51-1)
- services/api-gateway/suggestion_engine.py (from task 51-3-02)
- services/api-gateway/models.py (PolicySuggestion model)
</read_first>
<action>
Add 3 new endpoints to `services/api-gateway/admin_endpoints.py`:

1. **`GET /api/v1/admin/policy-suggestions`** — calls `get_pending_suggestions(cosmos_client)` and returns `list[PolicySuggestion]`. Requires `Depends(verify_token)`.

2. **`POST /api/v1/admin/policy-suggestions/{suggestion_id}/dismiss`** — calls `dismiss_suggestion(cosmos_client, suggestion_id, action_class)`. The `action_class` should be provided as a query parameter. Returns `{"status": "dismissed"}` on success, 404 on failure. Requires `Depends(verify_token)`.

3. **`POST /api/v1/admin/policy-suggestions/{suggestion_id}/convert`** — accepts a JSON body with `AutoRemediationPolicyCreate` fields. Creates the policy in PostgreSQL (reusing the create logic), then calls `convert_suggestion_to_policy(cosmos_client, suggestion_id, action_class, policy_id)`. Returns the created policy. Requires `Depends(verify_token)`.

Import from `services.api_gateway.suggestion_engine`:
```python
from services.api_gateway.suggestion_engine import (
    get_pending_suggestions,
    dismiss_suggestion,
    convert_suggestion_to_policy,
)
```
</action>
<acceptance_criteria>
- `services/api-gateway/admin_endpoints.py` contains `@router.get("/policy-suggestions"`
- `services/api-gateway/admin_endpoints.py` contains `@router.post("/policy-suggestions/{suggestion_id}/dismiss"`
- `services/api-gateway/admin_endpoints.py` contains `@router.post("/policy-suggestions/{suggestion_id}/convert"`
- `services/api-gateway/admin_endpoints.py` contains `from services.api_gateway.suggestion_engine import`
- `services/api-gateway/admin_endpoints.py` contains `get_pending_suggestions`
- `services/api-gateway/admin_endpoints.py` contains `dismiss_suggestion`
- `services/api-gateway/admin_endpoints.py` contains `convert_suggestion_to_policy`
</acceptance_criteria>
</task>

<task id="51-3-04">
<title>Start suggestion sweep loop in main.py lifespan</title>
<read_first>
- services/api-gateway/main.py (lines 380-486 — lifespan background tasks)
</read_first>
<action>
In `services/api-gateway/main.py`:

1. Add import at top (near the pattern_analyzer imports):
```python
from services.api_gateway.suggestion_engine import (
    SUGGESTION_SWEEP_INTERVAL_SECONDS,
    run_suggestion_sweep_loop,
)
```

2. In the `lifespan()` function, after the pattern analysis loop start (around line 446), add:
```python
# Start learning suggestion sweep loop (Phase 51)
_suggestion_sweep_task: Optional[asyncio.Task] = None
if app.state.cosmos_client is not None:
    _suggestion_sweep_task = asyncio.create_task(
        run_suggestion_sweep_loop(
            cosmos_client=app.state.cosmos_client,
            interval_seconds=SUGGESTION_SWEEP_INTERVAL_SECONDS,
        )
    )
    logger.info(
        "startup: suggestion sweep loop started | interval=%ds",
        SUGGESTION_SWEEP_INTERVAL_SECONDS,
    )
else:
    logger.warning("startup: suggestion sweep loop not started (COSMOS_ENDPOINT not set)")
```

3. In the shutdown section (after the pattern analysis loop cancellation), add:
```python
# Cancel suggestion sweep loop on shutdown
if _suggestion_sweep_task is not None and not _suggestion_sweep_task.done():
    _suggestion_sweep_task.cancel()
    try:
        await _suggestion_sweep_task
    except asyncio.CancelledError:
        pass
    logger.info("shutdown: suggestion sweep loop cancelled")
```
</action>
<acceptance_criteria>
- `services/api-gateway/main.py` contains `from services.api_gateway.suggestion_engine import`
- `services/api-gateway/main.py` contains `run_suggestion_sweep_loop`
- `services/api-gateway/main.py` contains `suggestion sweep loop started`
- `services/api-gateway/main.py` contains `suggestion sweep loop cancelled`
- `services/api-gateway/main.py` contains `_suggestion_sweep_task`
</acceptance_criteria>
</task>

<task id="51-3-05">
<title>Write unit tests for suggestion engine</title>
<read_first>
- services/api-gateway/suggestion_engine.py (from task 51-3-02)
- services/api-gateway/tests/test_remediation_executor.py (test pattern reference)
</read_first>
<action>
Create `services/api-gateway/tests/test_suggestion_engine.py` with at least 6 unit tests:

1. `test_sweep_no_qualifying_patterns` — remediation_audit has <5 records for any action_class → no suggestions created
2. `test_sweep_creates_suggestion` — 5+ HITL-approved records for `restart_vm` with 0 rollbacks → creates a suggestion with `action_class="restart_vm"` and `approval_count=5`
3. `test_sweep_skips_if_rollback_present` — 5 records but one has `verification_result="DEGRADED"` → no suggestion (1 rollback)
4. `test_sweep_skips_auto_approved` — records where `auto_approved_by_policy` is set are excluded from the count
5. `test_get_pending_suggestions` — returns only non-dismissed suggestions without `converted_to_policy_id`
6. `test_dismiss_suggestion_success` — dismiss sets `dismissed=True` on the Cosmos record

Mock `cosmos_client` with `MagicMock()` providing `get_database_client().get_container_client()` chain. Mock `query_items` to return test data. Use `@pytest.mark.asyncio`.
</action>
<acceptance_criteria>
- File exists at `services/api-gateway/tests/test_suggestion_engine.py`
- File contains at least 6 test functions matching `def test_`
- File contains `test_sweep_no_qualifying_patterns`
- File contains `test_sweep_creates_suggestion`
- File contains `test_sweep_skips_if_rollback_present`
- File contains `test_sweep_skips_auto_approved`
- File contains `test_get_pending_suggestions`
- File contains `test_dismiss_suggestion_success`
- `python -m pytest services/api-gateway/tests/test_suggestion_engine.py --tb=short` exits 0
</acceptance_criteria>
</task>

## Verification

After all tasks complete:
- `cd terraform && terraform fmt -check modules/databases/cosmos.tf` — formatting passes
- `python -m pytest services/api-gateway/tests/test_suggestion_engine.py -v` — all 6+ tests pass
- `grep -c "policy_suggestions" terraform/modules/databases/cosmos.tf` — returns ≥1

## must_haves
- [ ] Cosmos `policy_suggestions` container defined in Terraform with `/action_class` partition key and 30-day TTL
- [ ] `suggestion_engine.py` with sweep logic: 5+ HITL approvals + 0 rollbacks → suggestion
- [ ] Auto-approved records excluded from suggestion counts
- [ ] 3 suggestion API endpoints (list, dismiss, convert) added to admin_endpoints.py
- [ ] Background sweep loop started in main.py lifespan with cancellation on shutdown
- [ ] ≥6 unit tests covering sweep logic and API
