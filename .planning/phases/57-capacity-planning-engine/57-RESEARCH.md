# Phase 57: Capacity Planning Engine — Research

> **Purpose:** Everything a planner needs to know to break Phase 57 into plans.
> **Audience:** Plan author / implementation agent.
> **Date:** 2026-04-16

---

## 1. What We're Building

Give infrastructure architects a forward-looking capacity view. The three failure modes this phase prevents:

| Failure Mode | Consequence | Headroom Target |
|---|---|---|
| vCPU quota exhaustion | Deployment blocked mid-release, 2–4 week quota increase lead time | 90-day projection |
| IP space exhaustion | AKS scale-out fails mid-traffic-spike | Per-subnet available IPs |
| AKS node quota | Node pool scale-out blocked by SKU family quota | Per-cluster, per-pool |

**Deliverables (from ROADMAP):**
1. `get_subscription_quota_headroom` — all compute/network/storage quotas; usage %, linear regression growth rate, days to exhaustion
2. `get_ip_address_space_headroom` — VNet CIDR utilisation, available IPs per subnet, projected exhaustion
3. `get_aks_node_quota_headroom` — per-cluster node count vs max, node pool SKU quota
4. Capacity forecast model — linear + seasonal growth curve; 90-day projections with confidence intervals
5. `GET /api/v1/capacity/headroom` — top-10 resources approaching exhaustion (<30 days)
6. Capacity tab in UI — quota headroom table with traffic-light indicators; 90-day forecast chart

**Dependency on Phase 52:** Phase 52 built `finops_endpoints.py` with Cost Management + ARG + Monitor patterns. Phase 57 **reuses those patterns** for quota data, not cost data. No functional dependency — just pattern similarity.

---

## 2. Azure API Landscape

### 2.1 Compute Quota — Primary API

**SDK:** `azure-mgmt-compute` (already in `requirements.txt` — used by `forecaster.py` and `finops_endpoints.py`)

```python
from azure.mgmt.compute import ComputeManagementClient

client = ComputeManagementClient(credential, subscription_id)
usages = client.usage.list(location="eastus")  # Returns ItemPaged[Usage]
```

Each `Usage` object has:
- `name.value` — machine-readable name (e.g., `"standardDSv3Family"`)
- `name.localized_value` — human-readable label (e.g., `"Standard DSv3 Family vCPUs"`)
- `current_value` — current usage count
- `limit` — quota limit

**Compute quotas returned:** vCPU families (Standard DSv3, Ev4, etc.), Total Regional vCPUs, Availability Sets, Public IP Addresses, Load Balancers, Snapshots, Managed Disks.

**Multi-location:** Must call `usage.list(location)` per Azure region. For the initial implementation, use the subscription's primary region (derive from topology data, or default to `"eastus"` with configurable override via `CAPACITY_DEFAULT_LOCATION` env var). Optionally support list of locations.

**RBAC required:** `Reader` role on the subscription — already granted to api-gateway managed identity via Phase 15 (`260404-vm9`).

---

### 2.2 Network Quota — Compute Client Has Some; Network Client Has More

**Option A: Compute client** — `client.usage.list(location)` also returns some network resources (Public IP Addresses, Load Balancers, VNet Gateways count).

**Option B: Network client** — `azure-mgmt-network` (already in requirements) returns fuller network quotas:

```python
from azure.mgmt.network import NetworkManagementClient

net_client = NetworkManagementClient(credential, subscription_id)
network_usages = net_client.usages.list(location="eastus")  # Returns ItemPaged[Usage]
```

Each `Usage` object has `.name.value`, `.current_value`, `.limit` — same shape as compute.

Network quota categories include: VirtualNetworks, StaticPublicIPAddresses, NetworkSecurityGroups, PublicIPAddresses, NicPublicIPAddresses, PublicIpPrefixes, LoadBalancers, ApplicationGateways, VirtualNetworkGateways, etc.

**Decision:** Use both Compute client (vCPU families) AND Network client (networking limits) for comprehensive coverage. Filter out zero-limit entries (limit=0 means no quota enforced).

---

### 2.3 Unified Quota API (Microsoft.Quota / azure-mgmt-quota)

**SDK:** `azure-mgmt-quota` v3.0.1 (NOT in requirements yet)

**Scopes supported:** Compute, Network, MachineLearningService, Purview, HPC Cache, Storage.

```python
from azure.mgmt.quota import AzureQuotaExtensionAPI  # or QuotaMgmtClient in v3+

scope = f"/subscriptions/{subscription_id}/providers/Microsoft.Compute/locations/{location}"
client = AzureQuotaExtensionAPI(credential)
quotas = list(client.quota.list(scope=scope))   # CurrentQuotaLimitBase list
usages = list(client.usages.list(scope=scope))  # CurrentUsagesBase list
```

**Fields on CurrentUsagesBase:** `.name.value`, `.properties.usage_type`, `.properties.current_value`, `.properties.limit`.

**Pre-registration required:** `Microsoft.Quota` resource provider must be registered on each subscription. This is a one-time ops step.

**Decision for Phase 57:** Use `azure-mgmt-compute` and `azure-mgmt-network` for quota (no new packages, both already installed, no provider registration required). Add a comment noting `azure-mgmt-quota` is available for future unified quota management. Avoids a new package + registration gate.

---

### 2.4 Storage Quota

Azure Storage doesn't have per-SKU vCPU-style quotas. Instead:
- Storage Account count limit (250 per subscription per region) — retrievable via `azure-mgmt-storage` `StorageManagementClient.usages.list_by_location(location)`.
- Capacity (bytes used) from Azure Monitor metrics.

For Phase 57 scope: include Storage Account count quota from `azure-mgmt-storage`. Capacity metrics are handled by Phase 26 `forecaster.py`.

```python
from azure.mgmt.storage import StorageManagementClient

storage_client = StorageManagementClient(credential, subscription_id)
storage_usages = storage_client.usages.list_by_location(location)
```

---

### 2.5 IP Address Space Headroom

**VNet + Subnet data:** `azure-mgmt-network.NetworkManagementClient`

```python
net_client = NetworkManagementClient(credential, subscription_id)
vnets = list(net_client.virtual_networks.list_all())  # all VNets in subscription

for vnet in vnets:
    for subnet in (vnet.subnets or []):
        address_prefix = subnet.address_prefix  # e.g. "10.0.1.0/24"
        ip_configs = subnet.ip_configurations    # list of attached NICs/resources
```

**Available IP calculation (Azure rules):**
- Azure reserves **5 IPs per subnet**: `.0` (network), `.1` (default gateway), `.2-.3` (Azure DNS), `.255` (broadcast for /24; highest for any subnet).
- Formula: `total_ips = 2^(32 - prefix_len)`; `available = total_ips - 5 - len(ip_configurations or [])`
- For subnet sizes < /29 (fewer than 8 addresses), all IPs may be reserved.
- Use Python's `ipaddress` stdlib: `network = ipaddress.ip_network(address_prefix, strict=False)`; `total_ips = network.num_addresses`.

**Address spaces with multiple prefixes:** `subnet.address_prefixes` (plural) for multi-CIDR subnets — iterate all prefixes.

**Subnet types to skip:** Subnets with `delegations` set to Container Apps, PostgreSQL (they have special IP rules); note in output but still report.

**Projected exhaustion:** If the subnet feeds an AKS cluster or VMSS (check `subnet.ip_configurations` source resource types), growth rate = nodes added per day × node IP consumption. For Phase 57, use simpler model: if `usage_pct > 80`, flag as "watch"; if `usage_pct > 90`, flag as "critical" with days-to-exhaustion based on linear regression over the last 14 days of usage data (retrieve from Monitor if available) or static snapshot.

**ARG alternative (faster for large estates):** Use ARG to query subnets in bulk:
```kusto
Resources
| where type == "microsoft.network/virtualnetworks"
| mv-expand subnets = properties.subnets
| project vnetName=name, rg=resourceGroup, subnetName=subnets.name, prefix=tostring(subnets.properties.addressPrefix), ipConfigCount=array_length(subnets.properties.ipConfigurations)
```
This is faster than iterating VNets via SDK for large subscriptions. ARG client (`azure-mgmt-resourcegraph`) already in requirements.

---

### 2.6 AKS Node Quota

**Two separate constraints:**

1. **SKU family vCPU quota** — same as compute quota above (e.g., `standardDSv3Family`). If node pool uses `Standard_D8s_v3`, it needs 8 vCPUs per node × desired node count.

2. **AKS Managed Cluster quota** (new as of September 2025) — maximum AKS clusters per subscription per region. Retrievable via the Quota API or ARM:
   - Enterprise Agreement: default 100 clusters/region
   - Pay-as-you-go: default 10 clusters/region

3. **Node count vs max_count:** Each agent pool has `count` (current), `min_count`, `max_count` from the Autoscaler. `max_count` is the configured autoscaler ceiling, NOT a hard Azure limit. Hard limit is 5,000 nodes/cluster, 1,000 nodes/pool.

**SDK approach:**
```python
from azure.mgmt.containerservice import ContainerServiceClient

aks_client = ContainerServiceClient(credential, subscription_id)
clusters = list(aks_client.managed_clusters.list())
for cluster in clusters:
    for pool in (cluster.agent_pool_profiles or []):
        current = pool.count
        max_autoscale = pool.max_count  # autoscaler ceiling
        vm_size = pool.vm_size  # e.g. "Standard_D8s_v3"
        # lookup vCPU count from VM size → compute quota family
```

`azure-mgmt-containerservice` is NOT currently in requirements. Need to add.

**VM size → quota family mapping:** `azure-mgmt-compute` provides `ComputeManagementClient.virtual_machine_sizes.list(location)` which returns VM sizes with `number_of_cores`. For quota family mapping (e.g., `Standard_D8s_v3` → `standardDSv3Family`), use a local lookup table or ARG:
```kusto
Resources
| where type == "microsoft.containerservice/managedclusters"
| mv-expand agentPoolProfiles = properties.agentPoolProfiles
| project clusterName=name, rg=resourceGroup, poolName=agentPoolProfiles.name, vmSize=tostring(agentPoolProfiles.vmSize), currentNodes=toint(agentPoolProfiles.count), maxNodes=toint(agentPoolProfiles.maxCount)
```

**Decision:** Use ARG for AKS cluster discovery (single bulk query, no per-cluster API call), then enrich with vCPU quota data from `ComputeManagementClient.usage.list()`.

---

## 3. Forecast Model Design

### 3.1 Phase 26 Forecaster vs. Phase 57 Capacity Forecaster

| | `forecaster.py` (Phase 26) | Capacity Forecaster (Phase 57) |
|---|---|---|
| **Input data** | Azure Monitor time-series metrics (CPU %, memory) | Quota usage snapshots (current_value / limit) |
| **Algorithm** | Holt double exponential smoothing (α=0.3, β=0.1) | Linear regression on daily snapshots |
| **Data frequency** | 5-minute intervals, 2h window | Daily snapshots over 90 days |
| **Time horizon** | 60-minute breach detection | 90-day exhaustion projection |
| **Storage** | Cosmos `baselines` container | Cosmos `capacity_baselines` container (new) OR PostgreSQL |
| **Trigger** | Background sweep every 15 min | Background sweep every 24h (or on-demand) |
| **Confidence** | MAPE hold-out validation | R² of linear fit + confidence interval |

### 3.2 Linear Regression (Pure Python)

For quota headroom, linear regression is more appropriate than Holt smoothing because:
- Quota usage grows steadily with infrastructure additions (not seasonally)
- Daily snapshots (not 5-min) make exponential smoothing less suited
- Linear projection → days to 100% is directly interpretable

**Pure Python implementation** (no numpy/scipy — matching project pattern):

```python
def _linear_regression(x: List[float], y: List[float]) -> tuple[float, float, float]:
    """Returns (slope, intercept, r_squared).
    x: day offsets [0, 1, 2, ...], y: usage values.
    """
    n = len(x)
    if n < 2:
        return 0.0, y[-1] if y else 0.0, 0.0
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    den = sum((xi - x_mean) ** 2 for xi in x)
    slope = num / den if den != 0 else 0.0
    intercept = y_mean - slope * x_mean
    # R²
    ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    r_sq = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
    return slope, intercept, max(0.0, r_sq)

def _days_to_exhaustion(current_pct: float, slope_per_day: float, limit: float = 100.0) -> Optional[float]:
    """Days until usage_pct reaches limit (100% = exhausted).
    Returns None if slope <= 0 (stable/declining) or already exhausted.
    """
    if current_pct >= limit:
        return None  # already exhausted
    if slope_per_day <= 0:
        return None  # not growing
    days = (limit - current_pct) / slope_per_day
    return round(days, 1) if days <= 365 else None  # cap at 1 year
```

### 3.3 Growth Data — Where to Get History

**Problem:** Quota usage changes instantly when resources are added. Azure doesn't provide historical quota usage — only the current snapshot.

**Solution:** Store daily snapshots ourselves in Cosmos `capacity_snapshots` container:
- Document: `{ id, subscription_id, location, quota_name, timestamp, current_value, limit, usage_pct }`
- Partition key: `/subscription_id`
- Background task: run daily sweep that upserts today's snapshot

This means on first deploy, only 1 data point (today). Regression activates after 3+ daily snapshots. Until then, use **static projection** based on current usage% relative to threshold.

**Fallback for first 3 days:** No regression — report current headroom only with `days_to_exhaustion: null` and `confidence: "insufficient_data"`.

**Alternative for immediate value (no history required):** Use subnet-level data with ARG for IP space (static calculation, no history needed). Quota time-series can be seeded from ARM Activity Log to reconstruct historic additions.

---

## 4. API Endpoint Design

### 4.1 `GET /api/v1/capacity/headroom`

Returns top-10 resources/quotas approaching exhaustion (< 30 days).

```json
{
  "subscription_id": "...",
  "location": "eastus",
  "top_constrained": [
    {
      "resource_category": "compute_quota",
      "name": "Standard DSv3 Family vCPUs",
      "quota_name": "standardDSv3Family",
      "current_value": 180,
      "limit": 200,
      "usage_pct": 90.0,
      "available": 20,
      "days_to_exhaustion": 14,
      "confidence": "medium",
      "traffic_light": "red",
      "projected_exhaustion_date": "2026-04-30"
    }
  ],
  "generated_at": "2026-04-16T...",
  "snapshot_count": 12,
  "data_note": "Projections require ≥3 daily snapshots. Items with <3 snapshots show current state only."
}
```

**Traffic light logic:**
- `red` — `days_to_exhaustion < 30` OR `usage_pct >= 90`
- `yellow` — `days_to_exhaustion < 90` OR `usage_pct >= 75`
- `green` — otherwise

**Query params:**
- `subscription_id` (required)
- `location` (default: env var `CAPACITY_DEFAULT_LOCATION` or `"eastus"`)
- `days_threshold` (default: `30`, configurable)
- `include_categories` (default: `compute,network,ip_space,aks`)

---

### 4.2 `GET /api/v1/capacity/quotas`

Full quota list for a subscription/location — all categories, sorted by usage_pct descending.

---

### 4.3 `GET /api/v1/capacity/ip-space`

All subnets in the subscription with available IP count and projected exhaustion.

---

### 4.4 `GET /api/v1/capacity/aks`

All AKS clusters with node pool headroom and SKU quota mapping.

---

## 5. Codebase Patterns to Follow

### 5.1 Endpoint Pattern (`finops_endpoints.py`)

```python
# services/api-gateway/capacity_endpoints.py
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from services.api_gateway.dependencies import get_credential
from fastapi import Depends

# Lazy imports pattern (all SDKs use this):
try:
    from azure.mgmt.compute import ComputeManagementClient
    _COMPUTE_IMPORT_ERROR: str = ""
except Exception as _e:
    ComputeManagementClient = None  # type: ignore
    _COMPUTE_IMPORT_ERROR = str(_e)

router = APIRouter(prefix="/api/v1/capacity", tags=["capacity"])
logger = logging.getLogger(__name__)
```

### 5.2 Cosmos Background Sweep Pattern (`forecaster.py`)

```python
# New capacity_planner.py — mirrors forecaster.py structure
async def run_capacity_sweep_loop(cosmos_client, credential, interval_seconds=86400):
    """Daily sweep — stores quota snapshots in Cosmos capacity_snapshots."""
    while True:
        await asyncio.sleep(interval_seconds)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_capacity_sweep_sync, ...)
```

### 5.3 Module-level SDK availability logging (`forecaster.py`, `finops_endpoints.py`)

```python
def _log_sdk_availability():
    if ComputeManagementClient is None:
        logger.warning("azure-mgmt-compute unavailable: %s", _COMPUTE_IMPORT_ERROR or "ImportError")
_log_sdk_availability()
```

### 5.4 Timing pattern (all agent tools)

```python
start_time = time.monotonic()
try:
    result = ...
    duration_ms = int((time.monotonic() - start_time) * 1000)
    return {..., "duration_ms": duration_ms}
except Exception as exc:
    duration_ms = int((time.monotonic() - start_time) * 1000)
    logger.warning("capacity.xxx: error | duration_ms=%d error=%s", duration_ms, exc)
    return JSONResponse({"error": str(exc)}, status_code=500)
```

### 5.5 Tool function pattern (agent tools never raise)

```python
@ai_function
def get_subscription_quota_headroom(subscription_id: str, location: str = "eastus") -> Dict:
    """..."""
    start_time = time.monotonic()
    try:
        ...
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return {"quotas": [...], "duration_ms": duration_ms}
    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return {"error": str(exc), "quotas": [], "duration_ms": duration_ms}
```

### 5.6 New Pydantic models go in `models.py`

Following existing pattern, add `CapacityQuotaItem`, `CapacityHeadroomResponse`, `SubnetHeadroomItem`, `AKSNodePoolHeadroomItem` to `services/api-gateway/models.py`.

### 5.7 Router registration in `main.py`

```python
from services.api_gateway.capacity_endpoints import router as capacity_router
# ... in app registration:
app.include_router(capacity_router)
```

---

## 6. UI Design

### 6.1 Tab Placement

New `capacity` tab in `DashboardPanel.tsx`. Add to the "Monitoring & cost" group:
```typescript
// In TAB_GROUPS, "Monitoring & cost" group:
{ id: 'capacity', label: 'Capacity', Icon: Gauge },
```

**Current tabs (15):** ops, alerts, audit, topology, resources, vms, vmss, aks, cost, observability, sla, patch, compliance, runbooks, settings → becomes **16 tabs**.

### 6.2 `CapacityTab.tsx` Component Structure

```
CapacityTab
├── Header row: [Refresh] [Subscription selector] [Location selector]
├── Summary cards (4): Total Quotas | Red (critical) | Yellow (warning) | Green (healthy)
├── Section 1: Quota Headroom Table
│   ├── Columns: Category | Name | Used | Limit | Usage % | Available | Days Left | Status
│   ├── Rows sorted by days_to_exhaustion ASC (nulls last)
│   └── Traffic-light badge in Status column (red/yellow/green)
├── Section 2: IP Address Space
│   ├── VNet grouping
│   └── Columns: VNet | Subnet | CIDR | Used IPs | Available | Usage % | Status
└── Section 3: 90-Day Forecast Chart (Recharts LineChart)
    ├── X-axis: Date (today + 90 days)
    ├── Y-axis: Usage %
    ├── Lines: top 3-5 constrained resources
    └── Reference line at 100% (exhaustion threshold)
```

### 6.3 Proxy Routes

```
app/api/proxy/capacity/headroom/route.ts
app/api/proxy/capacity/quotas/route.ts
app/api/proxy/capacity/ip-space/route.ts
app/api/proxy/capacity/aks/route.ts
```

All follow the standard proxy pattern: `getApiGatewayUrl() + buildUpstreamHeaders(request) + AbortSignal.timeout(15000)`.

### 6.4 Traffic Light Styling

Follow existing badge pattern from `SLATab.tsx` / `PatchTab.tsx`:
```tsx
// Use CSS semantic tokens, never hardcoded Tailwind colors
const trafficLightStyle = (status: 'red' | 'yellow' | 'green') => ({
  red:    'var(--accent-red)',
  yellow: 'var(--accent-yellow)',
  green:  'var(--accent-green)',
}[status])
```

---

## 7. New Cosmos Container

**Container:** `capacity_snapshots`
- Partition key: `/subscription_id`
- TTL: 400 days (retains 13 months of daily snapshots)
- No vector index needed

**Document schema:**
```json
{
  "id": "{subscription_id}:{location}:{quota_name}:{date}",
  "subscription_id": "...",
  "location": "eastus",
  "quota_name": "standardDSv3Family",
  "quota_display_name": "Standard DSv3 Family vCPUs",
  "category": "compute",
  "current_value": 150,
  "limit": 200,
  "usage_pct": 75.0,
  "snapshot_date": "2026-04-16",
  "created_at": "2026-04-16T12:00:00Z"
}
```

**Terraform:** Add to `terraform/modules/databases/cosmos.tf` — new container alongside existing 8.

---

## 8. New Python Packages Required

| Package | Version | Purpose | Already in requirements? |
|---|---|---|---|
| `azure-mgmt-containerservice` | `~=31.0` | AKS cluster + node pool data | ❌ **NEW** |

Compute, Network, Storage SDKs already present. No `azure-mgmt-quota` needed for Phase 57 (see Section 2.3 decision).

**Note on `azure-mgmt-containerservice` version:** Check current pinned versions in `requirements.txt` for consistency. The AKS SDK has been stable; use `>=28.0.0,<32.0.0` range.

---

## 9. RBAC Requirements

The api-gateway managed identity already has `Reader` role on subscriptions (added Phase 15). This covers:
- `ComputeManagementClient.usage.list()` ✅
- `NetworkManagementClient.usages.list()` ✅
- `ContainerServiceClient.managed_clusters.list()` ✅
- ARG queries ✅
- `StorageManagementClient.usages.list_by_location()` ✅

No new RBAC assignments needed.

---

## 10. Risks & Constraints

### Risk 1: No Historical Quota Data on Day 1
- **Issue:** Linear regression requires ≥3 daily snapshots. On initial deploy, only current snapshot exists.
- **Mitigation:** Static headroom reporting for the first 3 days with `days_to_exhaustion: null`. Include `snapshot_count` in response so UI can display "Insufficient history" note instead of a forecast chart.

### Risk 2: Multi-Location Complexity
- **Issue:** Quotas are regional. A subscription might have resources in 5 regions.
- **Mitigation:** Default to single configurable location (`CAPACITY_DEFAULT_LOCATION`). Endpoint accepts `location` parameter. Cross-location aggregation deferred to future phase.

### Risk 3: Subnet IP Count Accuracy
- **Issue:** `subnet.ip_configurations` may not include all reserved IPs (e.g., Azure Load Balancer VIPs, NAT gateway IPs).
- **Mitigation:** Use `ip_configurations` count + 5 Azure reserved = conservative estimate. Document caveat in response.

### Risk 4: AKS Node Pool to vCPU Family Mapping
- **Issue:** Must map VM SKU (e.g., `Standard_D8s_v3`) to quota family name (e.g., `standardDSv3Family`). No official API for this mapping.
- **Mitigation:** Implement a static lookup table for the 20 most common VM families. For unmapped SKUs, return `quota_family: "unknown"` and skip quota correlation. The table can be extended incrementally.

### Risk 5: Container App Context Window for `azure-mgmt-containerservice`
- **Issue:** Adding a new large SDK package increases Docker image size.
- **Mitigation:** Use lazy import pattern (existing standard). SDK loads only when AKS endpoints are called.

### Risk 6: Rate Limiting
- **Issue:** `NetworkManagementClient.usages.list()` + VNet traversal for many VNets could hit ARM throttling.
- **Mitigation:** Use ARG for subnet discovery (single bulk query). Cap VNet list at 50 for IP space analysis.

---

## 11. Recommended Plan Breakdown (3 Plans)

### Plan 57-1: Backend Foundation (capacity_planner.py + Cosmos + Quotas)
- New `capacity_planner.py`: pure-Python linear regression, `_linear_regression()`, `_days_to_exhaustion()`, `CapacityPlannerClient` with Cosmos `capacity_snapshots` container
- New Cosmos `capacity_snapshots` container (Terraform)
- `get_subscription_quota_headroom()` function using Compute + Network SDK
- Background daily sweep wired in `main.py` lifespan
- `get_ip_address_space_headroom()` using ARG + `ipaddress` stdlib
- 30+ unit tests (regression math, headroom calculations, ARG parsing)

### Plan 57-2: AKS + API Endpoints
- `get_aks_node_quota_headroom()` using `ContainerServiceClient` + ARG
- VM-size-to-quota-family lookup table (20 common SKUs)
- `capacity_endpoints.py`: `GET /api/v1/capacity/headroom`, `/quotas`, `/ip-space`, `/aks`
- New Pydantic models in `models.py`: `CapacityQuotaItem`, `CapacityHeadroomResponse`, etc.
- Router registration in `main.py`
- 20+ unit tests for endpoints + AKS headroom

### Plan 57-3: Capacity Tab UI
- `CapacityTab.tsx`: summary cards, quota headroom table (traffic-light), IP space table, 90-day Recharts forecast chart
- 4 proxy routes (`/api/proxy/capacity/**`)
- `DashboardPanel.tsx` update: add `capacity` tab to "Monitoring & cost" group
- TypeScript types for all capacity response shapes
- `npx tsc --noEmit` and `npm run build` pass

---

## 12. Success Metric Validation Approach

**From ROADMAP:** "For a subscription with known quota constraints, headroom endpoint correctly identifies the constrained resource and projects exhaustion date within ±7 days."

**Test strategy:**
1. Unit test: Seed mock daily snapshots (14 days of data, linear growth from 50% to 80% usage). Assert `days_to_exhaustion` ≈ expected value ± 1 day.
2. Integration test: Mock ARG + Compute SDK responses; assert `traffic_light: "yellow"` for 75% usage, `traffic_light: "red"` for >90%.
3. E2E: After deploy, call `GET /api/v1/capacity/headroom?subscription_id=...`. Assert response structure is valid and at least 1 quota item returned.

---

## 13. Key Architectural Decisions to Confirm in Planning

1. **Snapshot storage:** Cosmos vs. PostgreSQL?
   - **Recommend Cosmos** — consistent with forecaster.py pattern (Cosmos `baselines`); avoids PostgreSQL migration complexity.

2. **Single location vs. multi-location:** Phase 57 = single configurable location. Multi-location in a future phase.

3. **Subnet growth forecast:** Static snapshot (usage today) vs. time-series regression?
   - **Recommend static snapshot** for IP space in Phase 57 — subnet IPs are a one-time calculation. Growth projection for subnets requires knowing planned deployments, which is out of scope.

4. **Background sweep interval:** Daily (86400s) for quota snapshots vs. hourly?
   - **Recommend daily** — quota changes are infrequent (infrastructure additions, not real-time metrics).

5. **Agent tool placement:** In `agents/sre/tools.py` or a new `agents/finops/tools.py`?
   - **Recommend SRE agent** — capacity planning is an SRE function; no new container needed. FinOps agent is cost-focused.

---

## Sources

- Azure Quota Service REST API: https://learn.microsoft.com/en-us/rest/api/quota/
- `azure-mgmt-quota` v3.0.1: https://pypi.org/project/azure-mgmt-quota/
- AKS Quotas and Limits: https://learn.microsoft.com/en-us/azure/aks/quotas-skus-regions
- `ComputeManagementClient.usage.list()`: https://learn.microsoft.com/en-us/python/api/azure-mgmt-compute/azure.mgmt.compute.operations.usageoperations
- Azure Public IP Addresses overview: https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/public-ip-addresses
