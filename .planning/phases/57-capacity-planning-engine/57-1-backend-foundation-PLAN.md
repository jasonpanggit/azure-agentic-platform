---
wave: 1
depends_on: []
files_modified:
  - services/api-gateway/capacity_planner.py
  - terraform/modules/databases/cosmos.tf
  - services/api-gateway/requirements.txt
  - services/api-gateway/main.py
  - tests/test_capacity_planner.py
autonomous: true
# NOTE: Seasonal decomposition is deferred to a future phase; linear regression is appropriate
# per RESEARCH.md §3.2 (daily quota snapshots are too short a series for seasonal modelling).
---

# Plan 57-1: Backend Foundation — capacity_planner.py + Cosmos + Quota Functions

## Goal

Build the core capacity planning module: pure-Python linear regression engine, daily Cosmos snapshot persistence, `get_subscription_quota_headroom()` (Compute + Network), and `get_ip_address_space_headroom()` (ARG-based). Wire the daily sweep into `main.py` lifespan. Provision the Cosmos `capacity_snapshots` container via Terraform.

## must_haves

- `_linear_regression(x, y)` returns `(slope, intercept, r_squared)` correctly for known datasets
- `_days_to_exhaustion()` returns `None` for slope ≤ 0 and correctly projects days for positive slope
- `get_subscription_quota_headroom()` calls both `ComputeManagementClient.usage.list()` AND `NetworkManagementClient.usages.list()`, filters out zero-limit entries, and never raises
- `get_ip_address_space_headroom()` uses ARG query (not per-VNet SDK iteration), computes `available = total_ips - 5 - ip_config_count`
- Daily sweep upserts today's snapshot to Cosmos `capacity_snapshots` container
- Cosmos container `capacity_snapshots` exists in Terraform with partition key `/subscription_id` and TTL 400 days
- 30+ passing unit tests covering regression math, edge cases, headroom calculations

---

## Tasks

### Task 1: Create `capacity_planner.py` skeleton with linear regression engine

<read_first>
- services/api-gateway/forecaster.py (background sweep pattern, Cosmos client usage, run_in_executor pattern)
- services/api-gateway/finops_endpoints.py (lazy import pattern, _log_sdk_availability, timing pattern)
</read_first>

<action>
Create `services/api-gateway/capacity_planner.py` with:

1. Module-level lazy imports with `_IMPORT_ERROR` guards:
```python
try:
    from azure.mgmt.compute import ComputeManagementClient
    _COMPUTE_IMPORT_ERROR: str = ""
except Exception as _e:
    ComputeManagementClient = None  # type: ignore[assignment,misc]
    _COMPUTE_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.network import NetworkManagementClient
    _NETWORK_IMPORT_ERROR: str = ""
except Exception as _e:
    NetworkManagementClient = None  # type: ignore[assignment,misc]
    _NETWORK_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest
    _ARG_IMPORT_ERROR: str = ""
except Exception as _e:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    _ARG_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.storage import StorageManagementClient
    _STORAGE_IMPORT_ERROR: str = ""
except Exception as _e:
    StorageManagementClient = None  # type: ignore[assignment,misc]
    _STORAGE_IMPORT_ERROR = str(_e)
```

2. `_log_sdk_availability()` function called at module level.

3. Pure-Python `_linear_regression(x: List[float], y: List[float]) -> tuple[float, float, float]`:
   - Returns `(slope, intercept, r_squared)`
   - n < 2 → returns `(0.0, y[-1] if y else 0.0, 0.0)`
   - Computes x_mean, y_mean, numerator, denominator, R²
   - Clamps R² to `max(0.0, r_sq)`
   - Also computes confidence interval bounds from regression residuals:
     - `residuals = [y[i] - (slope * x[i] + intercept) for i in range(n)]`
     - `mean_residual = sum(residuals) / n`
     - `std_residual = (sum((r - mean_residual)**2 for r in residuals) / n) ** 0.5`
     - `ci_upper_pct = round((mean_residual + 1.645 * std_residual) / max(1, intercept) * 100, 2)` (±90% CI as % of limit)
     - `ci_lower_pct = round((mean_residual - 1.645 * std_residual) / max(1, intercept) * 100, 2)`
     - Store as module-level helper `_regression_ci(x, y, slope, intercept) -> tuple[float, float]` returning `(ci_upper_pct, ci_lower_pct)`

4. `_days_to_exhaustion(current_pct: float, slope_per_day: float, limit: float = 100.0) -> Optional[float]`:
   - Returns `None` if `current_pct >= limit`
   - Returns `None` if `slope_per_day <= 0`
   - Returns `round((limit - current_pct) / slope_per_day, 1)` capped at 365 days (else None)

5. `_traffic_light(usage_pct: float, days_to_exhaustion: Optional[float]) -> str`:
   - `"red"` if `days_to_exhaustion is not None and days_to_exhaustion < 30` OR `usage_pct >= 90`
   - `"yellow"` if `days_to_exhaustion is not None and days_to_exhaustion < 90` OR `usage_pct >= 75`
   - `"green"` otherwise

6. `class CapacityPlannerClient` with:
   - `__init__(self, cosmos_client, credential, subscription_id: str, location: str = "eastus")`
   - `_get_snapshots(quota_name: str, days: int = 90) -> List[Dict]` — queries Cosmos `capacity_snapshots` container
   - `_upsert_snapshot(doc: Dict) -> None` — upserts to Cosmos container
   - `_compute_regression_from_snapshots(snapshots: List[Dict]) -> Dict` — returns slope, intercept, r_squared, snapshot_count, **confidence_interval_upper_pct, confidence_interval_lower_pct** (derived from `_regression_ci`); returns fallback with zeros if < 3 snapshots

7. `CAPACITY_SWEEP_ENABLED = os.environ.get("CAPACITY_SWEEP_ENABLED", "true").lower() == "true"`
8. `CAPACITY_SWEEP_INTERVAL_SECONDS = int(os.environ.get("CAPACITY_SWEEP_INTERVAL_SECONDS", "86400"))`
9. `CAPACITY_DEFAULT_LOCATION = os.environ.get("CAPACITY_DEFAULT_LOCATION", "eastus")`
10. `COSMOS_CAPACITY_SNAPSHOTS_CONTAINER = os.environ.get("COSMOS_CAPACITY_SNAPSHOTS_CONTAINER", "capacity_snapshots")`
</action>

<acceptance_criteria>
- `grep -n "_linear_regression" services/api-gateway/capacity_planner.py` returns the function definition
- `grep -n "_days_to_exhaustion" services/api-gateway/capacity_planner.py` returns the function definition
- `grep -n "_traffic_light" services/api-gateway/capacity_planner.py` returns the function definition
- `grep -n "CapacityPlannerClient" services/api-gateway/capacity_planner.py` returns the class definition
- `grep -n "CAPACITY_SWEEP_ENABLED" services/api-gateway/capacity_planner.py` returns the constant
- `grep -n "_log_sdk_availability" services/api-gateway/capacity_planner.py` shows function AND call at module level
- `grep -n "ComputeManagementClient = None" services/api-gateway/capacity_planner.py` shows the fallback assignment
- `grep -n "confidence_interval_upper_pct\|confidence_interval_lower_pct" services/api-gateway/capacity_planner.py` returns matches in `_compute_regression_from_snapshots`
- `grep -n "_regression_ci" services/api-gateway/capacity_planner.py` shows the CI helper function
</acceptance_criteria>

---

### Task 2: Add `get_subscription_quota_headroom()` to `CapacityPlannerClient`

<read_first>
- services/api-gateway/capacity_planner.py (just created in Task 1)
- .planning/phases/57-capacity-planning-engine/57-RESEARCH.md (sections 2.1, 2.2, 2.4 — API shapes)
</read_first>

<action>
Add method `get_subscription_quota_headroom(self, location: Optional[str] = None) -> Dict` to `CapacityPlannerClient`:

1. `start_time = time.monotonic()` at entry
2. `loc = location or self.location`
3. Collect compute quotas:
   - `compute_client = ComputeManagementClient(self.credential, self.subscription_id)`
   - `usages = list(compute_client.usage.list(loc))`
   - Filter: `item.limit > 0`
   - Map each to `{"quota_name": item.name.value, "display_name": item.name.localized_value, "category": "compute", "current_value": item.current_value, "limit": item.limit, "usage_pct": round(item.current_value / item.limit * 100, 2), "available": item.limit - item.current_value}`
4. Collect network quotas (same shape, `category: "network"`):
   - `net_client = NetworkManagementClient(self.credential, self.subscription_id)`
   - `network_usages = list(net_client.usages.list(loc))`
   - Filter: `item.limit > 0`
   - Include `"available": item.limit - item.current_value` in each mapped item
5. Collect storage quotas (`category: "storage"`):
   - `storage_client = StorageManagementClient(self.credential, self.subscription_id)`
   - `storage_usages = list(storage_client.usages.list_by_location(loc))`
   - Filter: `item.limit > 0`
   - Include `"available": item.limit - item.current_value` in each mapped item
6. For each quota item, retrieve snapshots from Cosmos and compute regression → populate `days_to_exhaustion`, `traffic_light`, `growth_rate_per_day`, `confidence`, `confidence_interval_upper_pct`, `confidence_interval_lower_pct`
7. If SDK unavailable (client is None), skip that category and add a `"warnings"` list to response
8. Return dict: `{"quotas": [...], "location": loc, "subscription_id": ..., "generated_at": ..., "duration_ms": ...}`
9. Wrap all in `try/except Exception` → return `{"error": str(exc), "quotas": [], "duration_ms": ...}` (never raise)

Separately add standalone function `get_subscription_quota_headroom(subscription_id: str, location: str, credential, cosmos_client) -> Dict` that instantiates `CapacityPlannerClient` and delegates — this is used by SRE agent tools.
</action>

<acceptance_criteria>
- `grep -n "def get_subscription_quota_headroom" services/api-gateway/capacity_planner.py` shows both the method AND standalone function
- `grep -n "ComputeManagementClient(self.credential" services/api-gateway/capacity_planner.py` shows client instantiation
- `grep -n "NetworkManagementClient(self.credential" services/api-gateway/capacity_planner.py` shows client instantiation
- `grep -n "StorageManagementClient(self.credential" services/api-gateway/capacity_planner.py` shows client instantiation
- `grep -n "item.limit > 0" services/api-gateway/capacity_planner.py` shows zero-limit filter
- `grep -n '"error": str(exc)' services/api-gateway/capacity_planner.py` shows never-raise error handling
- `grep -n '"available"' services/api-gateway/capacity_planner.py` returns 1+ match (available field populated as limit - current_value)
</acceptance_criteria>

---

### Task 3: Add `get_ip_address_space_headroom()` using ARG

<read_first>
- services/api-gateway/capacity_planner.py (Tasks 1–2)
- .planning/phases/57-capacity-planning-engine/57-RESEARCH.md (section 2.5 — ARG query and available IP formula)
- services/api-gateway/finops_endpoints.py (ARG client usage pattern — `ResourceGraphClient`)
</read_first>

<action>
Add `get_ip_address_space_headroom(self) -> Dict` to `CapacityPlannerClient`:

1. `start_time = time.monotonic()`
2. ARG query (single bulk call, not per-VNet iteration):
```python
ARG_SUBNET_QUERY = """
Resources
| where type == "microsoft.network/virtualnetworks"
| mv-expand subnets = properties.subnets
| project vnetName=name, resourceGroup=resourceGroup, 
    subnetName=tostring(subnets.name), 
    addressPrefix=tostring(subnets.properties.addressPrefix),
    ipConfigCount=toint(array_length(subnets.properties.ipConfigurations))
| order by vnetName asc, subnetName asc
"""
```
3. Execute via `ResourceGraphClient(self.credential)`:
```python
arg_client = ResourceGraphClient(self.credential)
request = QueryRequest(subscriptions=[self.subscription_id], query=ARG_SUBNET_QUERY)
result = arg_client.resources(request)
rows = result.data if result.data else []
```
4. For each row, compute:
   - `import ipaddress`
   - `network = ipaddress.ip_network(address_prefix, strict=False)`
   - `total_ips = network.num_addresses`
   - `reserved = 5`
   - `ip_config_count = row.get("ipConfigCount") or 0`
   - `available = max(0, total_ips - reserved - ip_config_count)`
   - `usage_pct = round((total_ips - reserved - available) / max(1, total_ips - reserved) * 100, 2)`
   - `traffic_light = _traffic_light(usage_pct, None)` (static, no regression for subnets)
5. Return: `{"subnets": [...], "subscription_id": ..., "generated_at": ..., "duration_ms": ..., "note": "Available IPs = total - 5 (Azure reserved) - attached IP configurations. Estimate only."}`
6. Wrap in `try/except` → never raise; return `{"error": str(exc), "subnets": [], "duration_ms": ...}`

Add standalone function `get_ip_address_space_headroom(subscription_id, credential) -> Dict`.
</action>

<acceptance_criteria>
- `grep -n "def get_ip_address_space_headroom" services/api-gateway/capacity_planner.py` shows method and standalone function
- `grep -n "ipaddress.ip_network" services/api-gateway/capacity_planner.py` shows stdlib usage
- `grep -n "ARG_SUBNET_QUERY" services/api-gateway/capacity_planner.py` shows the ARG query constant
- `grep -n "ipConfigCount" services/api-gateway/capacity_planner.py` shows ARG field used
- `grep -n "total_ips - reserved - available" services/api-gateway/capacity_planner.py` shows the available IP formula
</acceptance_criteria>

---

### Task 4: Add daily snapshot sweep and wire into `main.py`

<read_first>
- services/api-gateway/capacity_planner.py (Tasks 1–3)
- services/api-gateway/main.py (lifespan function pattern — how forecaster sweep is wired, lines 110–115 import pattern and lifespan asynccontextmanager)
- services/api-gateway/forecaster.py (run_forecast_sweep_loop pattern — async loop, run_in_executor, sleep)
</read_first>

<action>
In `capacity_planner.py`, add:

```python
async def run_capacity_sweep_loop(
    cosmos_client: Any,
    credential: Any,
    subscription_ids: List[str],
    interval_seconds: int = CAPACITY_SWEEP_INTERVAL_SECONDS,
) -> None:
    """Daily loop — for each subscription, fetch quota snapshot and upsert to Cosmos."""
    logger.info("capacity_sweep: starting loop interval_seconds=%d", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        for subscription_id in subscription_ids:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    _run_single_subscription_sweep_sync,
                    cosmos_client, credential, subscription_id
                )
            except Exception as exc:
                logger.warning("capacity_sweep: subscription=%s error=%s", subscription_id, exc)
```

Add `_run_single_subscription_sweep_sync(cosmos_client, credential, subscription_id: str) -> None`:
- Instantiates `CapacityPlannerClient`
- Calls `get_subscription_quota_headroom()` (sync)
- For each quota item, calls `_upsert_snapshot()` with document `{id: f"{subscription_id}:{location}:{quota_name}:{date}", subscription_id, location, quota_name, quota_display_name, category, current_value, limit, usage_pct, snapshot_date: datetime.utcnow().date().isoformat(), created_at: datetime.utcnow().isoformat()}`

In `main.py`, add after `finops_router` import block:
```python
from services.api_gateway.capacity_planner import (
    CAPACITY_SWEEP_ENABLED,
    CAPACITY_SWEEP_INTERVAL_SECONDS,
    run_capacity_sweep_loop,
)
```
In the `@asynccontextmanager async def lifespan` block, alongside the forecaster sweep, add:
```python
if CAPACITY_SWEEP_ENABLED:
    asyncio.create_task(
        run_capacity_sweep_loop(
            cosmos_client=cosmos_client,
            credential=credential,
            subscription_ids=list(registry.get_all_subscription_ids()),
            interval_seconds=CAPACITY_SWEEP_INTERVAL_SECONDS,
        )
    )
    logger.info("Capacity sweep task started (interval=%ds)", CAPACITY_SWEEP_INTERVAL_SECONDS)
```
</action>

<acceptance_criteria>
- `grep -n "run_capacity_sweep_loop" services/api-gateway/capacity_planner.py` shows the async function
- `grep -n "_run_single_subscription_sweep_sync" services/api-gateway/capacity_planner.py` shows the sync helper
- `grep -n "run_capacity_sweep_loop" services/api-gateway/main.py` shows import and usage in lifespan
- `grep -n "CAPACITY_SWEEP_ENABLED" services/api-gateway/main.py` shows the guard condition
- `grep -n "snapshot_date" services/api-gateway/capacity_planner.py` shows the field in upsert doc
</acceptance_criteria>

---

### Task 5: Add Cosmos `capacity_snapshots` container to Terraform

<read_first>
- terraform/modules/databases/cosmos.tf (existing container definitions — copy the pattern for container block, TTL, partition key)
</read_first>

<action>
In `terraform/modules/databases/cosmos.tf`, add a new `azurerm_cosmosdb_sql_container` resource:

```hcl
resource "azurerm_cosmosdb_sql_container" "capacity_snapshots" {
  name                  = "capacity_snapshots"
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_path    = "/subscription_id"
  partition_key_version = 1
  default_ttl           = 34560000  # 400 days in seconds

  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/*" }
    excluded_path { path = "/\"_etag\"/?" }
  }

  throughput = 400
}
```
</action>

<acceptance_criteria>
- `grep -n "capacity_snapshots" terraform/modules/databases/cosmos.tf` shows the resource block
- `grep -n "partition_key_path.*subscription_id" terraform/modules/databases/cosmos.tf` shows correct partition key
- `grep -n "default_ttl.*34560000" terraform/modules/databases/cosmos.tf` shows 400-day TTL
- `terraform validate` passes (run from `terraform/` directory) OR file syntax is valid HCL
</acceptance_criteria>

---

### Task 6: Add `azure-mgmt-containerservice` to requirements (for Plan 57-2)

<read_first>
- services/api-gateway/requirements.txt (check existing azure-mgmt-* version pins for consistency)
</read_first>

<action>
In `services/api-gateway/requirements.txt`, add:
```
azure-mgmt-containerservice>=28.0.0,<32.0.0
```
Place it in alphabetical order with the other `azure-mgmt-*` packages.
</action>

<acceptance_criteria>
- `grep "azure-mgmt-containerservice" services/api-gateway/requirements.txt` returns the line with the version constraint
</acceptance_criteria>

---

### Task 7: Write 30+ unit tests in `tests/test_capacity_planner.py`

<read_first>
- services/api-gateway/capacity_planner.py (all functions from Tasks 1–4)
- tests/test_forecaster.py (test structure to follow — pytest fixtures, mock patterns)
</read_first>

<action>
Create `tests/test_capacity_planner.py` covering:

**Linear regression (10 tests):**
- Perfect linear growth: `x=[0,1,2,3,4], y=[50,52,54,56,58]` → slope=2.0, intercept=50.0, r²=1.0
- Flat/constant: `x=[0,1,2], y=[60,60,60]` → slope=0.0, r²=0.0 (or 1.0 for constant line — handle edge)
- Single point: `x=[0], y=[50]` → slope=0.0, r²=0.0
- Empty: `x=[], y=[]` → slope=0.0, intercept=0.0
- Negative slope: returns negative slope value
- n=2 (minimum for regression): assert slope computed correctly

**Days to exhaustion (8 tests):**
- `current_pct=90, slope=2.0` → `days = 5.0`
- `current_pct=50, slope=0` → `None`
- `current_pct=50, slope=-1` → `None`
- `current_pct=100` → `None` (already exhausted)
- `current_pct=1, slope=0.001` → `None` (cap at 365 days)
- `current_pct=80, slope=1.0` → `20.0`

**Traffic light (6 tests):**
- `usage_pct=91, days=None` → `"red"` (usage threshold)
- `usage_pct=50, days=15` → `"red"` (days threshold)
- `usage_pct=76, days=100` → `"yellow"` (usage threshold)
- `usage_pct=50, days=60` → `"yellow"` (days threshold)
- `usage_pct=50, days=None` → `"green"`
- `usage_pct=74, days=91` → `"green"`

**IP space headroom (6 tests — unit):**
- `/24` subnet, 10 ip_configs → `available = 256 - 5 - 10 = 241`
- `/28` subnet (16 IPs), 5 ip_configs → `available = 16 - 5 - 5 = 6`
- Empty subnet (0 ip_configs) → `available = total - 5`
- `available` never goes below 0: high ip_config count → `max(0, ...)`
- `usage_pct` calculation is correct for above
- Delegated subnet (has ip_configs) → still computes correctly

**Quota tool (4 tests — mock SDK):**
- SDK unavailable (ComputeManagementClient=None) → returns `{"quotas": [], "warnings": [...], "duration_ms": ...}` not an exception
- Quota with `limit=0` → filtered out
- Happy path (mock ComputeManagementClient.usage.list) → quotas returned with `usage_pct`
- Exception from Azure SDK → returns `{"error": ..., "quotas": []}` not raised
</action>

<acceptance_criteria>
- `grep -c "^def test_" tests/test_capacity_planner.py` returns 30 or more
- `python -m pytest tests/test_capacity_planner.py -v --tb=short 2>&1 | tail -5` shows all tests passing (0 failures)
- `grep -n "test_linear_regression" tests/test_capacity_planner.py` shows multiple test functions
- `grep -n "test_days_to_exhaustion" tests/test_capacity_planner.py` shows multiple test functions
- `grep -n "test_traffic_light" tests/test_capacity_planner.py` shows multiple test functions
- `grep -n "test_ip_space" tests/test_capacity_planner.py` shows multiple test functions
</acceptance_criteria>

---

## Verification

After all tasks complete:

```bash
# Lint
python -m py_compile services/api-gateway/capacity_planner.py && echo "syntax OK"

# Tests
python -m pytest tests/test_capacity_planner.py -v --tb=short

# Terraform validate
cd terraform && terraform init -backend=false && terraform validate && cd ..

# Check main.py still imports cleanly
python -c "import sys; sys.path.insert(0,'services/api-gateway'); from services.api_gateway import capacity_planner; print('import OK')"

# Test count check
grep -c "^def test_" tests/test_capacity_planner.py
```

Expected: all tests pass, terraform validates, capacity_planner.py imports without error, test count ≥ 30.
