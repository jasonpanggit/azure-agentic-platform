---
wave: 2
depends_on: [52-1-PLAN.md]
files_modified:
  - services/api-gateway/finops_endpoints.py
  - services/api-gateway/main.py
  - agents/orchestrator/agent.py
  - agents/shared/routing.py
  - services/api-gateway/models.py
  - services/detection-plane/classify_domain.py
  - fabric/kql/functions/classify_domain.kql
  - tests/api-gateway/test_finops_endpoints.py
autonomous: true
---

# Plan 52-2: API Gateway Integration + Orchestrator Routing

## Goal

Add 6 FinOps REST endpoints to the API gateway (`services/api-gateway/finops_endpoints.py`), register them in `main.py`, wire the `finops` domain into orchestrator routing (`DOMAIN_AGENT_MAP`, `_A2A_DOMAINS`, system prompt keywords), add `finops` to the `IncidentPayload.domain` regex and `QUERY_DOMAIN_KEYWORDS`, update the detection-plane domain classifiers, and add ≥20 gateway tests.

## Context

The API gateway is a thin FastAPI router with no business logic. FinOps tab endpoints call the Azure SDK directly (same pattern as `services/api-gateway/vm_cost.py`) for fast UI response — they do NOT delegate to the FinOps agent. The FinOps **agent** is for conversational Foundry threads. The orchestrator's `DOMAIN_AGENT_MAP` already has entries through `"messaging"` (Phase 49); `"finops"` is added as entry 13. The `IncidentPayload.domain` regex currently ends at `messaging`; `finops` must be appended. `SAFE_ARM_ACTIONS["deallocate_vm"]` is already in `remediation_executor.py` — no executor changes needed.

<threat_model>
## Security Threat Assessment

**1. FinOps endpoints call Azure SDK directly**: Use `DefaultAzureCredential` resolved by `get_credential()` from `services/api-gateway/dependencies.py`. No credentials in request parameters. Auth mode controlled by `API_GATEWAY_AUTH_MODE` env var (same as all other endpoints).

**2. `subscription_id` path/query parameter**: Validated as a non-empty string. The Azure SDK validates the subscription GUID format internally — invalid GUIDs return a 4xx from Azure, which is returned as a structured error dict, not leaked to the caller.

**3. `days` query parameter**: Validated as `ge=7, le=90` via FastAPI Query constraint — FastAPI returns 422 on out-of-range values before reaching the SDK call.

**4. `group_by` parameter**: Validated against allowlist `{"ResourceGroup", "ResourceType", "ServiceName"}` at both the gateway layer and in the tool function. Double-validation prevents invalid strings reaching the Cost Management API.

**5. `IncidentPayload.domain` regex update**: Adding `finops` to the allowlist regex expands accepted values. The regex still rejects any value not in the enumerated set. No security regression.

**6. `VALID_DOMAINS` frozenset update in `classify_domain.py`**: Same expansion pattern as Phase 49. The frozenset still validates all domain values; `finops` is simply a new valid member.

**7. Orchestrator system prompt routing keywords**: Natural-language routing hints only — no code execution path. LLM uses them to select the correct agent tool to call.
</threat_model>

---

## Tasks

### Task 1: Create `services/api-gateway/finops_endpoints.py`

<read_first>
- `services/api-gateway/vm_cost.py` — FULL FILE — exact router pattern to replicate: `APIRouter`, `@router.get()`, `DefaultAzureCredential`, direct Azure SDK calls, structured error returns
- `services/api-gateway/dependencies.py` — `get_credential()` and `get_cosmos_client()` dependency patterns
- `services/api-gateway/auth.py` — `verify_token` dependency (used in all routers)
- `52-RESEARCH.md` Section 7 — exact endpoint paths and query parameters for all 6 routes
- `agents/finops/tools.py` — tool function signatures and return shapes (NOT called directly; replicated as direct SDK calls at the gateway layer for fast response)
</read_first>

<action>
Create `services/api-gateway/finops_endpoints.py` with a FastAPI `APIRouter` and 6 GET endpoints. The file should directly call Azure SDK (same pattern as `vm_cost.py`) — NOT delegate to the FinOps agent. This is for the UI polling use case where fast direct responses are needed.

**Router setup:**
```python
"""FinOps API endpoints — Azure Cost Management direct queries for the Web UI.

These endpoints call Azure Cost Management SDK directly (not via the FinOps agent)
for fast Web UI polling. The FinOps agent is for conversational Foundry threads.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from azure.identity import DefaultAzureCredential
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

router = APIRouter(prefix="/api/v1/finops", tags=["finops"])
logger = logging.getLogger(__name__)

_VALID_GROUP_BY = frozenset({"ResourceGroup", "ResourceType", "ServiceName"})
_DATA_LAG_NOTE = "Azure Cost Management data has a 24–48 hour reporting lag. Values reflect costs up to 48h ago."
```

**Endpoint 1 — `GET /api/v1/finops/cost-breakdown`:**
```python
@router.get("/cost-breakdown")
async def get_cost_breakdown(
    subscription_id: str = Query(..., description="Azure subscription GUID"),
    days: int = Query(30, ge=7, le=90, description="Look-back window in days"),
    group_by: str = Query("ResourceGroup", description="Dimension: ResourceGroup | ResourceType | ServiceName"),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
```
- Validate `group_by in _VALID_GROUP_BY` → return 422 if invalid
- Call `CostManagementClient(credential).query.usage(scope, QueryDefinition(...))` with `group_by` grouping
- Return `{subscription_id, days, group_by, total_cost, currency, breakdown: [{name, cost, currency}], data_lag_note}`
- On exception: `return JSONResponse({"error": str(e), "query_status": "error", "data_lag_note": _DATA_LAG_NOTE}, status_code=500)`

**Endpoint 2 — `GET /api/v1/finops/resource-cost`:**
```python
@router.get("/resource-cost")
async def get_resource_cost(
    subscription_id: str = Query(...),
    resource_id: str = Query(..., description="Full ARM resource ID"),
    days: int = Query(30, ge=7, le=90),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
```
- `AmortizedCost` query filtered by `ResourceId`
- Return `{subscription_id, resource_id, days, total_cost, currency, cost_type: "AmortizedCost", data_lag_note}`

**Endpoint 3 — `GET /api/v1/finops/idle-resources`:**
```python
@router.get("/idle-resources")
async def get_idle_resources(
    subscription_id: str = Query(...),
    threshold_cpu_pct: float = Query(2.0, ge=0.1, le=10.0),
    hours: int = Query(72, ge=24, le=168),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
```
- ARG query for VMs + Monitor metrics for CPU + Network (same logic as `identify_idle_resources` tool but without creating approval records — approval records are created by the agent, not the UI endpoint)
- Return `{subscription_id, vms_evaluated, idle_count, idle_resources: [{resource_id, vm_name, resource_group, avg_cpu_pct, avg_network_mbps, monthly_cost_usd}]}`

**Endpoint 4 — `GET /api/v1/finops/ri-utilization`:**
```python
@router.get("/ri-utilization")
async def get_ri_utilization(
    subscription_id: str = Query(...),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
```
- AmortizedCost vs ActualCost delta method (30-day window, no grouping)
- Return `{subscription_id, method: "amortized_delta", actual_cost_usd, amortized_cost_usd, ri_benefit_estimated_usd, utilisation_note, data_lag_note}`

**Endpoint 5 — `GET /api/v1/finops/cost-forecast`:**
```python
@router.get("/cost-forecast")
async def get_cost_forecast(
    subscription_id: str = Query(...),
    budget_name: Optional[str] = Query(None),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
```
- Month-to-date ActualCost + burn rate calculation + optional budget comparison
- Return `{subscription_id, current_spend_usd, forecast_month_end_usd, budget_amount_usd, burn_rate_pct, days_elapsed, days_in_month, over_budget, over_budget_pct, data_lag_note}`

**Endpoint 6 — `GET /api/v1/finops/top-cost-drivers`:**
```python
@router.get("/top-cost-drivers")
async def get_top_cost_drivers(
    subscription_id: str = Query(...),
    n: int = Query(10, ge=1, le=25),
    days: int = Query(30, ge=7, le=90),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
```
- Group by `ServiceName` dimension, sort descending, take top `n`
- Return `{subscription_id, n, days, drivers: [{service_name, cost_usd, currency, rank}], total_cost_usd, data_lag_note}`

**Important**: All endpoints must:
1. Use lazy SDK import at function level (not module level) — same pattern as `vm_cost.py`
2. Return structured error dicts (never 500 with raw exception message exposed)
3. Include `data_lag_note` in every successful response
4. Log at INFO level with subscription_id context
</action>

<acceptance_criteria>
- File `services/api-gateway/finops_endpoints.py` exists
- `grep 'router = APIRouter(prefix="/api/v1/finops"' services/api-gateway/finops_endpoints.py` exits 0
- `grep 'def get_cost_breakdown' services/api-gateway/finops_endpoints.py` exits 0
- `grep 'def get_resource_cost' services/api-gateway/finops_endpoints.py` exits 0
- `grep 'def get_idle_resources' services/api-gateway/finops_endpoints.py` exits 0
- `grep 'def get_ri_utilization' services/api-gateway/finops_endpoints.py` exits 0
- `grep 'def get_cost_forecast' services/api-gateway/finops_endpoints.py` exits 0
- `grep 'def get_top_cost_drivers' services/api-gateway/finops_endpoints.py` exits 0
- `grep "_DATA_LAG_NOTE" services/api-gateway/finops_endpoints.py` exits 0
- `grep "_VALID_GROUP_BY" services/api-gateway/finops_endpoints.py` exits 0
- `grep -c '@router.get' services/api-gateway/finops_endpoints.py` outputs `6`
</acceptance_criteria>

---

### Task 2: Register FinOps router in `services/api-gateway/main.py`

<read_first>
- `services/api-gateway/main.py` lines 102–133 — current router import block (`from services.api_gateway.vm_cost import router as vm_cost_router`, `app.include_router(vm_cost_router)` pattern)
- `services/api-gateway/main.py` — find `app.include_router(vm_cost_router)` line to place the new `include_router` call adjacent to it
</read_first>

<action>
Make 2 targeted changes to `services/api-gateway/main.py`:

**Change 1 — Import block** (after the `vm_cost_router` import line, around line 129):
```python
from services.api_gateway.finops_endpoints import router as finops_router
```

**Change 2 — Router registration** (after `app.include_router(vm_cost_router)` in the `app` setup section, typically in the lifespan or at module level):
```python
app.include_router(finops_router)
```

Find the exact location by searching for `app.include_router(vm_cost_router)` and placing the finops registration immediately after it.
</action>

<acceptance_criteria>
- `grep "from services.api_gateway.finops_endpoints import router as finops_router" services/api-gateway/main.py` exits 0
- `grep "app.include_router(finops_router)" services/api-gateway/main.py` exits 0
</acceptance_criteria>

---

### Task 3: Update `agents/orchestrator/agent.py` — add `finops` domain routing

<read_first>
- `agents/orchestrator/agent.py` lines 140–190 — current `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, `_A2A_DOMAINS`
- `agents/orchestrator/agent.py` lines 100–138 — system prompt routing keywords section and tool allowlist line
- `52-RESEARCH.md` Section 6 — exact keys/values for `DOMAIN_AGENT_MAP`, `RESOURCE_TYPE_TO_DOMAIN`, routing keywords, `_A2A_DOMAINS`
</read_first>

<action>
Make 4 targeted changes to `agents/orchestrator/agent.py`:

**Change 1 — `DOMAIN_AGENT_MAP`** (after `"messaging": "messaging_agent"` entry, around line 157):
```python
"finops": "finops_agent",
"cost": "finops_agent",  # alias — conversational "cost" queries route to FinOps agent
```

**Change 2 — System prompt routing keywords** (add one new bullet BEFORE the `"Topic is ambiguous..."` sre fallback bullet, after the messaging bullet):
```
- Mentions "cost", "spend", "billing", "finops", "budget", "waste", "idle resources",
    "reserved instance", "ri utilization", "savings plan", "cost breakdown", "cloud cost",
    "rightsizing", "cost optimization", "monthly bill", "burn rate", "overspend" → call `finops_agent`
```

Also update the Tool allowlist line from:
```
    Tool allowlist: `compute_agent`, ..., `messaging_agent`, `classify_incident_domain`.
```
to:
```
    Tool allowlist: `compute_agent`, `network_agent`, `storage_agent`, `security_agent`,
        `arc_agent`, `sre_agent`, `patch_agent`, `eol_agent`, `database_agent`,
        `appservice_agent`, `containerapps_agent`, `messaging_agent`, `finops_agent`,
        `classify_incident_domain`.
```

**Change 3 — `_A2A_DOMAINS` list** (append `"finops"` after `"messaging"`):
```python
_A2A_DOMAINS = [
    "compute", "patch", "network", "security",
    "arc", "sre", "eol", "storage", "database", "appservice", "containerapps",
    "messaging",
    "finops",  # Phase 52
]
```

**Change 4 — `RESOURCE_TYPE_TO_DOMAIN`** (no new ARM resource type maps to finops — cost management is cross-resource, not a specific resource type): Skip this change. FinOps is triggered by conversational intent only.
</action>

<acceptance_criteria>
- `grep '"finops": "finops_agent"' agents/orchestrator/agent.py` exits 0
- `grep '"cost": "finops_agent"' agents/orchestrator/agent.py` exits 0
- `grep '"finops_agent"' agents/orchestrator/agent.py` — returns at least 2 lines
- `grep '"finops".*# Phase 52' agents/orchestrator/agent.py` exits 0
- `grep '"burn rate"' agents/orchestrator/agent.py` exits 0
- `grep '"idle resources"' agents/orchestrator/agent.py` exits 0
- `grep 'finops_agent.*classify_incident_domain' agents/orchestrator/agent.py` exits 0
</acceptance_criteria>

---

### Task 4: Update `agents/shared/routing.py` — add finops domain keywords

<read_first>
- `agents/shared/routing.py` — FULL FILE — current `QUERY_DOMAIN_KEYWORDS` tuple structure; `messaging` entry was added in Phase 49 (most recent); `finops` goes after `messaging`
- `52-RESEARCH.md` Section 6 — exact keyword list for `"finops"` domain
</read_first>

<action>
Add one new entry to `QUERY_DOMAIN_KEYWORDS` in `agents/shared/routing.py`. Insert after the `messaging` tuple entry:

```python
(
    "finops",
    (
        "finops",
        "cost breakdown",
        "cloud cost",
        "spending",
        "monthly bill",
        "burn rate",
        "budget",
        "reserved instance",
        "ri utilization",
        "savings plan",
        "idle resources",
        "rightsizing",
        "cost optimization",
        "overspend",
        "cost management",
    ),
),
```

Note: "cost" and "spend" (single-word) are intentionally NOT in this list because they are too generic and would conflict with cost-related queries within other domains (e.g., "compute costs"). The phrases above are more specific.
</action>

<acceptance_criteria>
- `grep '"finops"' agents/shared/routing.py` exits 0
- `grep '"burn rate"' agents/shared/routing.py` exits 0
- `grep '"cost breakdown"' agents/shared/routing.py` exits 0
- `grep '"idle resources"' agents/shared/routing.py` exits 0
- `grep '"reserved instance"' agents/shared/routing.py` exits 0
</acceptance_criteria>

---

### Task 5: Update `services/api-gateway/models.py` — add `finops` to `IncidentPayload.domain` regex

<read_first>
- `services/api-gateway/models.py` — search for `pattern=r"^(compute|network|storage|security|arc|sre|patch|eol|messaging)$"` (line ~47) — this is the `IncidentPayload.domain` field validator
</read_first>

<action>
Update the `IncidentPayload.domain` field `pattern` from:
```python
pattern=r"^(compute|network|storage|security|arc|sre|patch|eol|messaging)$",
```
to:
```python
pattern=r"^(compute|network|storage|security|arc|sre|patch|eol|messaging|finops)$",
```

This allows detection-plane incidents with `domain: "finops"` (e.g., a budget alert firing) to be routed correctly.
</action>

<acceptance_criteria>
- `grep 'finops' services/api-gateway/models.py` exits 0
- `grep 'pattern=r".*finops' services/api-gateway/models.py` exits 0
- The pattern string contains all previous domains plus `finops`: `grep 'compute.*network.*storage.*security.*arc.*sre.*patch.*eol.*messaging.*finops' services/api-gateway/models.py` exits 0
</acceptance_criteria>

---

### Task 6: Update `services/detection-plane/classify_domain.py` — add `finops` domain

<read_first>
- `services/detection-plane/classify_domain.py` — FULL FILE — current `DOMAIN_MAPPINGS` dict, `VALID_DOMAINS` frozenset, and any comments referencing the regex pattern
- `52-RESEARCH.md` Section 6 — note that `finops` does NOT map to specific ARM resource types (it's intent-based); however `microsoft.costmanagement` budgets should be mapped
</read_first>

<action>
Make 2 changes to `services/detection-plane/classify_domain.py`:

**Change 1 — `DOMAIN_MAPPINGS` dict**: Add entries after the `messaging` domain block (before the closing `}`):
```python
# FinOps domain (Phase 52) — Cost Management and Budget alerts
"microsoft.costmanagement": "finops",
"microsoft.costmanagement/budgets": "finops",
"microsoft.costmanagement/alerts": "finops",
"microsoft.billing": "finops",
```

**Change 2 — `VALID_DOMAINS` frozenset**: Update from:
```python
VALID_DOMAINS = frozenset({"compute", "network", "storage", "security", "arc", "sre", "patch", "eol", "messaging"})
```
to:
```python
VALID_DOMAINS = frozenset({"compute", "network", "storage", "security", "arc", "sre", "patch", "eol", "messaging", "finops"})
```

Also update the comment above `VALID_DOMAINS` to include `finops` in the regex reference comment.
</action>

<acceptance_criteria>
- `grep '"microsoft.costmanagement": "finops"' services/detection-plane/classify_domain.py` exits 0
- `grep '"finops"' services/detection-plane/classify_domain.py` — returns at least 3 lines (frozenset + dict entries)
- `grep 'frozenset.*"finops"' services/detection-plane/classify_domain.py` exits 0
</acceptance_criteria>

---

### Task 7: Update `fabric/kql/functions/classify_domain.kql` — add finops case

<read_first>
- `fabric/kql/functions/classify_domain.kql` — FULL FILE — current `case()` structure; new `finops` case must go BEFORE the final `"sre"` fallback
</read_first>

<action>
Add a new `finops` case in the `case()` function body, inserted immediately before the `// SRE fallback` comment line:

```kql
        // FinOps domain (Phase 52) — Cost Management and Budget alerts
        resource_type has_any (
            "Microsoft.CostManagement/budgets",
            "Microsoft.CostManagement/alerts",
            "Microsoft.Billing/billingAccounts"
        ), "finops",
```

The ordering after this change:
```
compute case,
network case,
storage case,
security case,
arc case,
messaging case,
finops case,   ← new
"sre" fallback ← unchanged, still last
```
</action>

<acceptance_criteria>
- `grep "finops" fabric/kql/functions/classify_domain.kql` exits 0
- `grep "Microsoft.CostManagement/budgets" fabric/kql/functions/classify_domain.kql` exits 0
- `grep '"finops"' fabric/kql/functions/classify_domain.kql` exits 0
- The `"sre"` fallback is still the last case: `grep '"sre"' fabric/kql/functions/classify_domain.kql` exits 0
- File still starts with `.create-or-alter function classify_domain`
</acceptance_criteria>

---

### Task 8: Create `tests/api-gateway/test_finops_endpoints.py`

<read_first>
- `tests/api-gateway/` directory listing — confirm existing test file naming pattern (e.g., `test_vm_cost.py`, `test_patch_endpoints.py`)
- `services/api-gateway/finops_endpoints.py` (just written) — exact endpoint paths and response shapes to test against
- `tests/api-gateway/test_vm_cost.py` (or closest existing test file) — exact `TestClient` + `mock.patch` pattern to replicate
</read_first>

<action>
Create `tests/api-gateway/test_finops_endpoints.py` with ≥20 tests across 6 test classes. Use `fastapi.testclient.TestClient` with `mock.patch` for Azure SDK calls.

**Test setup:**
```python
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from services.api_gateway.finops_endpoints import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)
```

**`TestCostBreakdown` (4 tests):**
- `test_returns_200_with_valid_params` — mock SDK returns 3-row result; `GET /api/v1/finops/cost-breakdown?subscription_id=abc&days=30&group_by=ResourceGroup`; assert `status_code == 200`, `"breakdown" in data`, `"data_lag_note" in data`
- `test_returns_422_on_invalid_group_by` — `GET .../cost-breakdown?subscription_id=abc&group_by=Tag`; assert `status_code == 422`
- `test_returns_422_on_days_out_of_range` — `GET .../cost-breakdown?subscription_id=abc&days=200`; assert `status_code == 422`
- `test_returns_error_on_sdk_exception` — mock raises `Exception("Unauthorized")`; assert `status_code == 500`, `"error" in data`

**`TestResourceCost` (3 tests):**
- `test_returns_200_with_cost` — mock returns single-row result; assert `status_code == 200`, `"total_cost" in data`, `data["cost_type"] == "AmortizedCost"`
- `test_returns_422_on_missing_resource_id` — omit `resource_id` param; assert `status_code == 422`
- `test_returns_error_on_sdk_exception` — mock raises; assert error

**`TestIdleResources` (4 tests):**
- `test_returns_200_with_idle_vms` — mock ARG + Monitor returns 2 idle VMs; assert `status_code == 200`, `data["idle_count"] == 2`
- `test_returns_200_with_no_idle_vms` — mock Monitor returns high CPU; assert `status_code == 200`, `data["idle_count"] == 0`, `data["idle_resources"] == []`
- `test_cpu_threshold_param_accepted` — `GET .../idle-resources?subscription_id=abc&threshold_cpu_pct=5.0`; assert `status_code == 200`
- `test_returns_error_on_sdk_exception` — mock raises; assert error

**`TestRiUtilization` (3 tests):**
- `test_returns_200_with_ri_data` — mock two cost queries (actual + amortized); assert `status_code == 200`, `"ri_benefit_estimated_usd" in data`, `data["method"] == "amortized_delta"`
- `test_returns_200_with_data_lag_note` — assert `"data_lag_note" in data`
- `test_returns_error_on_sdk_exception` — assert error

**`TestCostForecast` (4 tests):**
- `test_returns_200_without_budget` — `GET .../cost-forecast?subscription_id=abc`; assert `status_code == 200`, `"forecast_month_end_usd" in data`, `data["budget_amount_usd"] is None`
- `test_returns_200_with_budget_name` — mock `client.budgets.get()` returns `budget.amount = 10000`; `GET .../cost-forecast?subscription_id=abc&budget_name=my-budget`; assert `data["budget_amount_usd"] == 10000`, `"burn_rate_pct" in data`
- `test_over_budget_flag_set` — mock current spend = $12,000 on day 20 of 30-day month, budget $10,000; assert `data["over_budget"] == True`
- `test_returns_error_on_sdk_exception` — assert error

**`TestTopCostDrivers` (4 tests):**
- `test_returns_200_with_drivers` — mock returns 5-row ServiceName result; `GET .../top-cost-drivers?subscription_id=abc&n=5`; assert `status_code == 200`, `len(data["drivers"]) == 5`, `data["drivers"][0]["rank"] == 1`
- `test_n_validated_max_25` — `GET .../top-cost-drivers?subscription_id=abc&n=100`; assert `status_code == 422`
- `test_n_validated_min_1` — `GET .../top-cost-drivers?subscription_id=abc&n=0`; assert `status_code == 422`
- `test_returns_error_on_sdk_exception` — assert error
</action>

<acceptance_criteria>
- File `tests/api-gateway/test_finops_endpoints.py` exists
- `grep -c "def test_" tests/api-gateway/test_finops_endpoints.py` outputs a number >= 20
- `grep "class TestCostBreakdown" tests/api-gateway/test_finops_endpoints.py` exits 0
- `grep "class TestIdleResources" tests/api-gateway/test_finops_endpoints.py` exits 0
- `grep "class TestCostForecast" tests/api-gateway/test_finops_endpoints.py` exits 0
- `grep "class TestTopCostDrivers" tests/api-gateway/test_finops_endpoints.py` exits 0
- `grep "data_lag_note" tests/api-gateway/test_finops_endpoints.py` exits 0
- `python -m pytest tests/api-gateway/test_finops_endpoints.py -v --tb=short` exits 0 with all tests passing
</acceptance_criteria>

---

## Verification

After all tasks complete:

```bash
# 1. Gateway starts without import errors
python -c "from services.api_gateway.main import app; print('OK')"

# 2. FinOps router registered
python -c "
from services.api_gateway.main import app
routes = [r.path for r in app.routes]
finops_routes = [r for r in routes if '/finops/' in r]
assert len(finops_routes) == 6, f'Expected 6 finops routes, found {len(finops_routes)}: {finops_routes}'
print('OK: all 6 finops routes registered')
"

# 3. All gateway tests pass
python -m pytest tests/api-gateway/test_finops_endpoints.py -v --tb=short

# 4. IncidentPayload accepts finops domain
python -c "
from services.api_gateway.models import IncidentPayload
p = IncidentPayload(
    incident_id='det-test-001',
    severity='Sev2',
    domain='finops',
    affected_resources=[{'resource_id': '/subscriptions/abc', 'resource_type': 'Microsoft.CostManagement/budgets'}],
    detection_rule='budget_alert',
    kql_evidence='',
)
print('OK: finops domain accepted by IncidentPayload')
"

# 5. Orchestrator routing contains finops
python -c "
from agents.orchestrator.agent import DOMAIN_AGENT_MAP, _A2A_DOMAINS
assert 'finops' in DOMAIN_AGENT_MAP, 'finops not in DOMAIN_AGENT_MAP'
assert 'cost' in DOMAIN_AGENT_MAP, 'cost alias not in DOMAIN_AGENT_MAP'
assert 'finops' in _A2A_DOMAINS, 'finops not in _A2A_DOMAINS'
print('OK')
"
```

## must_haves

- [ ] `services/api-gateway/finops_endpoints.py` exists with 6 GET endpoints under `/api/v1/finops/` prefix
- [ ] All 6 routes registered in `services/api-gateway/main.py` via `app.include_router(finops_router)`
- [ ] `agents/orchestrator/agent.py` `DOMAIN_AGENT_MAP` contains `"finops": "finops_agent"` and `"cost": "finops_agent"`
- [ ] `agents/orchestrator/agent.py` `_A2A_DOMAINS` contains `"finops"`
- [ ] `agents/shared/routing.py` `QUERY_DOMAIN_KEYWORDS` contains `"finops"` domain with `"burn rate"`, `"idle resources"`, `"reserved instance"` keywords
- [ ] `services/api-gateway/models.py` `IncidentPayload.domain` regex includes `finops`
- [ ] `services/detection-plane/classify_domain.py` `VALID_DOMAINS` frozenset contains `"finops"`
- [ ] `services/detection-plane/classify_domain.py` `DOMAIN_MAPPINGS` contains `"microsoft.costmanagement"` → `"finops"`
- [ ] `fabric/kql/functions/classify_domain.kql` contains `"finops"` case before `"sre"` fallback
- [ ] `tests/api-gateway/test_finops_endpoints.py` has ≥20 tests all passing
- [ ] All 6 endpoints include `data_lag_note` in successful responses
