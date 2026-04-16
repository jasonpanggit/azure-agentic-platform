---
wave: 2
depends_on:
  - 57-1-backend-foundation-PLAN.md
files_modified:
  - services/api-gateway/capacity_planner.py
  - services/api-gateway/capacity_endpoints.py
  - services/api-gateway/models.py
  - services/api-gateway/main.py
  - tests/test_capacity_endpoints.py
autonomous: true
---

# Plan 57-2: AKS Headroom + API Endpoints

## Goal

Add `get_aks_node_quota_headroom()` (using `ContainerServiceClient` + ARG + VM-SKU-to-quota-family lookup), define Pydantic models for all capacity response shapes, build `capacity_endpoints.py` FastAPI router with 4 endpoints, and register it in `main.py`.

## must_haves

- `get_aks_node_quota_headroom()` returns per-cluster, per-pool node count vs max and SKU quota family; never raises
- VM SKU to quota family lookup table covers ≥ 20 common SKUs; unknown SKUs return `quota_family: "unknown"`
- `GET /api/v1/capacity/headroom` returns top-10 resources sorted by `days_to_exhaustion ASC` (nulls last), limited to resources with `usage_pct >= 50` or `days_to_exhaustion` not None
- All 4 endpoints follow the timing pattern and never return unhandled 500s
- Pydantic models `CapacityQuotaItem`, `CapacityHeadroomResponse`, `SubnetHeadroomItem`, `AKSNodePoolHeadroomItem` in `models.py`
- Router registered in `main.py`
- 20+ passing tests

---

## Tasks

### Task 1: Add `get_aks_node_quota_headroom()` to `capacity_planner.py`

<read_first>
- services/api-gateway/capacity_planner.py (existing class and patterns from Plan 57-1)
- .planning/phases/57-capacity-planning-engine/57-RESEARCH.md (section 2.6 — AKS node quota, ARG query, VM family mapping)
</read_first>

<action>
Add to `capacity_planner.py`:

1. VM SKU to quota family lookup table (module-level constant):
```python
_VM_SKU_TO_QUOTA_FAMILY: Dict[str, str] = {
    # D-series v3
    "Standard_D2s_v3": "standardDSv3Family",
    "Standard_D4s_v3": "standardDSv3Family",
    "Standard_D8s_v3": "standardDSv3Family",
    "Standard_D16s_v3": "standardDSv3Family",
    "Standard_D32s_v3": "standardDSv3Family",
    # D-series v4
    "Standard_D2s_v4": "standardDSv4Family",
    "Standard_D4s_v4": "standardDSv4Family",
    "Standard_D8s_v4": "standardDSv4Family",
    # D-series v5
    "Standard_D2s_v5": "standardDSv5Family",
    "Standard_D4s_v5": "standardDSv5Family",
    "Standard_D8s_v5": "standardDSv5Family",
    # E-series v3
    "Standard_E2s_v3": "standardESv3Family",
    "Standard_E4s_v3": "standardESv3Family",
    "Standard_E8s_v3": "standardESv3Family",
    "Standard_E16s_v3": "standardESv3Family",
    # E-series v5
    "Standard_E4s_v5": "standardESv5Family",
    "Standard_E8s_v5": "standardESv5Family",
    # F-series
    "Standard_F4s_v2": "standardFSv2Family",
    "Standard_F8s_v2": "standardFSv2Family",
    "Standard_F16s_v2": "standardFSv2Family",
    # B-series
    "Standard_B2s": "standardBSFamily",
    "Standard_B4ms": "standardBSFamily",
}
```

2. ARG query for AKS clusters:
```python
ARG_AKS_QUERY = """
Resources
| where type == "microsoft.containerservice/managedclusters"
| mv-expand agentPoolProfiles = properties.agentPoolProfiles
| project 
    clusterName=name,
    resourceGroup=resourceGroup,
    location=location,
    poolName=tostring(agentPoolProfiles.name),
    vmSize=tostring(agentPoolProfiles.vmSize),
    currentNodes=toint(agentPoolProfiles.count),
    maxNodes=toint(agentPoolProfiles.maxCount),
    minNodes=toint(agentPoolProfiles.minCount),
    mode=tostring(agentPoolProfiles.mode)
"""
```

3. Method `get_aks_node_quota_headroom(self) -> Dict` on `CapacityPlannerClient`:
   - Execute ARG query via `ResourceGraphClient`
   - For each pool: `quota_family = _VM_SKU_TO_QUOTA_FAMILY.get(vm_size, "unknown")`
   - `max_autoscale = max_nodes or 1000` (hard AKS limit fallback)
   - `nodes_available = max_autoscale - current_nodes`
   - `usage_pct = round(current_nodes / max(1, max_autoscale) * 100, 2)`
   - `traffic_light = _traffic_light(usage_pct, None)` (static, no regression for node count)
   - Return `{"clusters": [...], "subscription_id": ..., "generated_at": ..., "duration_ms": ...}`
   - Never raise; wrap in `try/except`

4. Standalone function `get_aks_node_quota_headroom(subscription_id, credential) -> Dict`.
</action>

<acceptance_criteria>
- `grep -n "_VM_SKU_TO_QUOTA_FAMILY" services/api-gateway/capacity_planner.py` shows the dict constant
- `python -c "from services.api_gateway.capacity_planner import _VM_SKU_TO_QUOTA_FAMILY; assert len(_VM_SKU_TO_QUOTA_FAMILY) >= 20"` passes
- `grep -n "def get_aks_node_quota_headroom" services/api-gateway/capacity_planner.py` shows method and standalone function
- `grep -n "ARG_AKS_QUERY" services/api-gateway/capacity_planner.py` shows the query constant
- `grep -n '"unknown"' services/api-gateway/capacity_planner.py` shows unknown SKU fallback
</acceptance_criteria>

---

### Task 2: Add Pydantic models to `models.py`

<read_first>
- services/api-gateway/models.py (existing model definitions — follow same BaseModel pattern, field order, Optional usage)
- .planning/phases/57-capacity-planning-engine/57-RESEARCH.md (section 4 — API response shapes)
</read_first>

<action>
In `services/api-gateway/models.py`, append these Pydantic models (add after existing models at end of file, before any `__all__` if present):

```python
# ── Capacity Planning Models ─────────────────────────────────────────────────

class CapacityQuotaItem(BaseModel):
    resource_category: str  # "compute_quota" | "network_quota" | "storage_quota"
    name: str               # human-readable display name
    quota_name: str         # machine-readable name (e.g. "standardDSv3Family")
    current_value: int
    limit: int
    usage_pct: float
    available: int
    days_to_exhaustion: Optional[float] = None
    confidence: Optional[str] = None  # "high" | "medium" | "low" | "insufficient_data"
    traffic_light: str = "green"      # "red" | "yellow" | "green"
    growth_rate_per_day: Optional[float] = None
    projected_exhaustion_date: Optional[str] = None  # ISO date string
    confidence_interval_upper_pct: Optional[float] = None  # ±90% CI upper bound as % of limit
    confidence_interval_lower_pct: Optional[float] = None  # ±90% CI lower bound as % of limit


class CapacityHeadroomResponse(BaseModel):
    subscription_id: str
    location: str
    top_constrained: List[CapacityQuotaItem]
    generated_at: str
    snapshot_count: int = 0
    data_note: Optional[str] = None


class SubnetHeadroomItem(BaseModel):
    vnet_name: str
    resource_group: str
    subnet_name: str
    address_prefix: str
    total_ips: int
    reserved_ips: int = 5
    ip_config_count: int
    available_ips: int
    usage_pct: float
    traffic_light: str = "green"
    note: Optional[str] = None


class IPSpaceHeadroomResponse(BaseModel):
    subscription_id: str
    subnets: List[SubnetHeadroomItem]
    generated_at: str
    duration_ms: int
    note: Optional[str] = None


class AKSNodePoolHeadroomItem(BaseModel):
    cluster_name: str
    resource_group: str
    location: str
    pool_name: str
    vm_size: str
    quota_family: str
    current_nodes: int
    max_nodes: int
    available_nodes: int
    usage_pct: float
    traffic_light: str = "green"


class AKSHeadroomResponse(BaseModel):
    subscription_id: str
    clusters: List[AKSNodePoolHeadroomItem]
    generated_at: str
    duration_ms: int
```

Import `List` from `typing` if not already present in models.py (check existing imports).
</action>

<acceptance_criteria>
- `grep -n "class CapacityQuotaItem" services/api-gateway/models.py` returns the class definition
- `grep -n "class CapacityHeadroomResponse" services/api-gateway/models.py` returns the class definition
- `grep -n "class SubnetHeadroomItem" services/api-gateway/models.py` returns the class definition
- `grep -n "class AKSNodePoolHeadroomItem" services/api-gateway/models.py` returns the class definition
- `grep -n "confidence_interval_upper_pct\|confidence_interval_lower_pct" services/api-gateway/models.py` returns 2 matches in CapacityQuotaItem
- `python -c "from services.api_gateway.models import CapacityQuotaItem, CapacityHeadroomResponse, SubnetHeadroomItem, AKSNodePoolHeadroomItem, IPSpaceHeadroomResponse, AKSHeadroomResponse; print('OK')"` prints "OK"
</acceptance_criteria>

---

### Task 3: Create `capacity_endpoints.py` FastAPI router

<read_first>
- services/api-gateway/capacity_planner.py (all functions from Plan 57-1 + Task 1 of this plan)
- services/api-gateway/models.py (models added in Task 2)
- services/api-gateway/finops_endpoints.py (router structure, dependency injection, Query params, JSONResponse pattern)
- services/api-gateway/dependencies.py (get_credential, get_cosmos_client)
</read_first>

<action>
Create `services/api-gateway/capacity_endpoints.py`:

```python
"""Capacity planning endpoints — quota headroom, IP space, AKS node headroom."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.capacity_planner import (
    CapacityPlannerClient,
    CAPACITY_DEFAULT_LOCATION,
)
from services.api_gateway.models import (
    CapacityHeadroomResponse,
    CapacityQuotaItem,
    IPSpaceHeadroomResponse,
    AKSHeadroomResponse,
)

router = APIRouter(prefix="/api/v1/capacity", tags=["capacity"])
logger = logging.getLogger(__name__)
```

**Endpoint 1:** `GET /api/v1/capacity/headroom`
- Query params: `subscription_id: str`, `location: str = CAPACITY_DEFAULT_LOCATION`, `days_threshold: int = 30`, `include_categories: str = "compute,network,storage,aks"`
- Instantiate `CapacityPlannerClient(cosmos_client, credential, subscription_id, location)`
- Call `get_subscription_quota_headroom()` to get all quotas
- Filter to items where `days_to_exhaustion is not None and days_to_exhaustion <= days_threshold` OR `usage_pct >= 90`
- Sort by `days_to_exhaustion ASC` (None → treated as infinity, sorts last), then by `usage_pct DESC`
- Take top 10
- Return `CapacityHeadroomResponse(subscription_id=..., location=..., top_constrained=[...], generated_at=..., snapshot_count=...)`
- `start_time` / `duration_ms` logging

**Endpoint 2:** `GET /api/v1/capacity/quotas`
- Query params: `subscription_id: str`, `location: str = CAPACITY_DEFAULT_LOCATION`
- Returns all quotas sorted by `usage_pct DESC`

**Endpoint 3:** `GET /api/v1/capacity/ip-space`
- Query params: `subscription_id: str`
- Returns `IPSpaceHeadroomResponse`

**Endpoint 4:** `GET /api/v1/capacity/aks`
- Query params: `subscription_id: str`
- Returns `AKSHeadroomResponse`

All endpoints:
- Use `start_time = time.monotonic()` and log `duration_ms`
- On exception: `logger.warning(...)` and return `JSONResponse({"error": str(exc)}, status_code=500)`
- Depend on `credential = Depends(get_credential)` and `cosmos_client = Depends(get_optional_cosmos_client)`
</action>

<acceptance_criteria>
- `grep -n "router = APIRouter" services/api-gateway/capacity_endpoints.py` shows `prefix="/api/v1/capacity"`
- `grep -n "@router.get" services/api-gateway/capacity_endpoints.py` returns 4 lines (one per endpoint)
- `grep -n '"/headroom"' services/api-gateway/capacity_endpoints.py` shows the headroom endpoint
- `grep -n '"/quotas"' services/api-gateway/capacity_endpoints.py` shows the quotas endpoint
- `grep -n '"/ip-space"' services/api-gateway/capacity_endpoints.py` shows the ip-space endpoint
- `grep -n '"/aks"' services/api-gateway/capacity_endpoints.py` shows the aks endpoint
- `grep -n "start_time = time.monotonic" services/api-gateway/capacity_endpoints.py` returns 4 lines
- `python -m py_compile services/api-gateway/capacity_endpoints.py && echo "OK"` prints "OK"
</acceptance_criteria>

---

### Task 4: Register `capacity_router` in `main.py`

<read_first>
- services/api-gateway/main.py (lines 129–137 — how other routers are imported and registered; look for `app.include_router` calls)
</read_first>

<action>
In `services/api-gateway/main.py`:

1. Add import after the `compliance_router` import line:
```python
from services.api_gateway.capacity_endpoints import router as capacity_router
```

2. Add `app.include_router(capacity_router)` alongside the other `app.include_router(...)` calls.
</action>

<acceptance_criteria>
- `grep -n "capacity_router" services/api-gateway/main.py` returns 2 lines (import and include_router)
- `grep -n "app.include_router(capacity_router)" services/api-gateway/main.py` returns 1 line
- `python -m py_compile services/api-gateway/main.py && echo "OK"` prints "OK"
</acceptance_criteria>

---

### Task 5: Write 20+ unit tests in `tests/test_capacity_endpoints.py`

<read_first>
- services/api-gateway/capacity_endpoints.py (Task 3)
- services/api-gateway/capacity_planner.py (functions being tested)
- tests/test_finops_endpoints.py (mock pattern for FastAPI TestClient + patching Azure SDK)
</read_first>

<action>
Create `tests/test_capacity_endpoints.py` using `fastapi.testclient.TestClient` + `unittest.mock.patch`:

**Headroom endpoint (6 tests):**
- Happy path: mock `CapacityPlannerClient.get_subscription_quota_headroom` returning 15 items → assert response has ≤10 items, sorted by days_to_exhaustion
- Items with `days_to_exhaustion=None` sort after items with non-None values
- Only items with `usage_pct >= 90` OR `days_to_exhaustion <= 30` appear in top_constrained
- Missing `subscription_id` → 422 validation error
- SDK unavailable (planner raises) → 500 with `{"error": ...}`
- Traffic light `"red"` items included in response

**Quotas endpoint (4 tests):**
- Happy path returns all quotas sorted by `usage_pct DESC`
- Zero-limit quotas filtered from results
- Items include `traffic_light` field
- Missing `subscription_id` → 422

**IP space endpoint (4 tests):**
- Happy path returns `subnets` list with correct `available_ips` calculation
- `/24` subnet with 10 ip_configs → `available_ips = 241`
- Empty subscription (no VNets via ARG) → `{"subnets": [], ...}`
- Missing `subscription_id` → 422

**AKS endpoint (4 tests):**
- Happy path returns clusters with pool data
- Unknown VM SKU → `quota_family = "unknown"`
- Empty subscription → `{"clusters": [], ...}`
- Missing `subscription_id` → 422

**VM SKU lookup (3 tests):**
- `_VM_SKU_TO_QUOTA_FAMILY["Standard_D8s_v3"] == "standardDSv3Family"`
- `_VM_SKU_TO_QUOTA_FAMILY.get("Standard_Unknown_v99", "unknown") == "unknown"`
- At least 20 entries in lookup table
</action>

<acceptance_criteria>
- `grep -c "^def test_" tests/test_capacity_endpoints.py` returns 20 or more
- `python -m pytest tests/test_capacity_endpoints.py -v --tb=short 2>&1 | tail -5` shows all tests passing
- `grep -n "TestClient" tests/test_capacity_endpoints.py` shows FastAPI test client usage
- `grep -n "patch" tests/test_capacity_endpoints.py` shows mock patching of Azure SDK calls
</acceptance_criteria>

---

## Verification

```bash
# Syntax
python -m py_compile services/api-gateway/capacity_endpoints.py && echo "endpoints OK"
python -m py_compile services/api-gateway/main.py && echo "main OK"

# Models importable
python -c "from services.api_gateway.models import CapacityQuotaItem, CapacityHeadroomResponse, SubnetHeadroomItem, AKSNodePoolHeadroomItem; print('models OK')"

# Router registered
grep "capacity_router" services/api-gateway/main.py

# Tests
python -m pytest tests/test_capacity_planner.py tests/test_capacity_endpoints.py -v --tb=short

# Test count
grep -c "^def test_" tests/test_capacity_endpoints.py
```

Expected: both test files pass, model imports succeed, router appears twice in main.py.
