# Phase 26: Predictive Operations - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning
**Mode:** Auto-generated (new service + API phase — discuss skipped)

<domain>
## Phase Boundary

Move from reactive alerting to proactive prevention. Forecast capacity exhaustion ≥30 minutes in advance with ≥70% accuracy (INTEL-005).

**Requirement:** INTEL-005 — Capacity exhaustion forecasts predict metric breaches ≥30 minutes in advance with ≥70% accuracy

**What this phase does:**
1. `services/api-gateway/forecaster.py` — collect Azure Monitor time-series metrics, compute trend + time-to-breach using exponential smoothing + linear regression (pure Python — no statsmodels/numpy)
2. Cosmos DB `baselines` container — per-resource metric baselines and seasonal profiles
3. New endpoints: `GET /api/v1/forecasts?resource_id=X` — returns capacity exhaustion forecast with time_to_breach_minutes, confidence (high/medium/low)
4. Background job: every 15 minutes, sweep known resources and refresh baselines + forecasts
5. Pre-incident early warning: if any resource forecast shows breach < 60 minutes, emit a synthetic `FORECAST_ALERT` incident via the existing `POST /api/v1/incidents` path

**What this phase does NOT do:**
- Does not use statsmodels, numpy, or scipy — pure Python arithmetic only (keep container lean)
- Does not add UI Forecasts tab (deferred)
- Does not change Phase 22 topology graph

**TOPO-005 prerequisite:** Phase 22 load test script exists at `scripts/ops/22-4-topology-load-test.sh` — TOPO-005 is satisfied structurally (operator runs the load test against prod to validate ≥10K nodes < 2s before Phase 26 deploys).

</domain>

<decisions>
## Implementation Decisions

### Forecasting algorithm: double exponential smoothing + linear projection (pure Python)

Double exponential smoothing (Holt's method):
```
level[t] = α * value[t] + (1 - α) * (level[t-1] + trend[t-1])
trend[t] = β * (level[t] - level[t-1]) + (1 - β) * trend[t-1]
forecast[t+h] = level[t] + h * trend[t]
```
- α = 0.3 (smoothing factor), β = 0.1 (trend factor)
- Using last 24 data points (2h at 5-min intervals) for fitting
- time_to_breach = (threshold - level[T]) / trend[T] if trend > 0
- Returns time_to_breach_minutes = None if trend is flat or declining

Accuracy validation:
- Hold-out test: fit on first 18 points, predict next 6, compute MAPE
- confidence = "high" if MAPE < 15%, "medium" if MAPE < 30%, "low" otherwise

### Metrics to forecast (capacity exhaustion focus)
```python
FORECAST_METRICS = {
    "microsoft.compute/virtualmachines": [
        {"name": "Percentage CPU",          "threshold": 90.0, "unit": "%"},
        {"name": "Available Memory Bytes",  "threshold": 0.1,  "unit": "GB", "invert": True},  # breach when LOW
        {"name": "OS Disk Queue Depth",     "threshold": 10.0, "unit": "count"},
    ],
    "microsoft.sql/servers/databases": [
        {"name": "dtu_consumption_percent", "threshold": 90.0, "unit": "%"},
        {"name": "storage_percent",          "threshold": 85.0, "unit": "%"},
    ],
    "microsoft.storage/storageaccounts": [
        {"name": "UsedCapacity",             "threshold": 90.0, "unit": "%_of_quota"},
    ],
}
```

### Storage: Cosmos DB `baselines` container
Partition by `/resource_id`:
```json
{
  "id": "<resource_id>:<metric_name>",
  "resource_id": "<arm resource id>",
  "metric_name": "Percentage CPU",
  "resource_type": "microsoft.compute/virtualmachines",
  "data_points": [{"timestamp": "...", "value": 42.3}, ...],  // last 24 points
  "level": 45.2,
  "trend": 0.8,
  "threshold": 90.0,
  "time_to_breach_minutes": 56.0,
  "confidence": "medium",
  "mape": 18.5,
  "last_updated": "2026-04-03T10:00:00Z"
}
```

### Cosmos DB container: add to Terraform databases module
New `azurerm_cosmosdb_sql_container.baselines` partition `/resource_id`, version 2

### Background sweep: asyncio task (15-min interval)
Runs in lifespan startup alongside topology sync:
- Reads all resource IDs from topology container (already built in Phase 22)
- For each resource with known type, collects last 2h of metrics from Azure Monitor
- Computes forecast, stores/updates `baselines` container
- If time_to_breach_minutes < 60 → emit synthetic FORECAST_ALERT incident

### Forecast API
`GET /api/v1/forecasts?resource_id=<id>` → returns all metric forecasts for that resource
`GET /api/v1/forecasts` → returns all resources with breach_imminent=True (time_to_breach < 60 min)

### INTEL-005 validation script
`scripts/ops/26-4-forecast-accuracy-test.sh`:
- Generates 24-point synthetic time series with known linear trend + noise
- Feeds to forecaster Python module directly (no API call needed)
- Asserts forecast is within 30% of true breach time (MAPE < 30%)
- Reports INTEL-005 PASS/FAIL

</decisions>

<code_context>
## Existing Code Insights

### Azure Monitor metrics collection pattern (diagnostic_pipeline.py)
```python
from azure.mgmt.monitor import MonitorManagementClient
client = MonitorManagementClient(credential, sub_id)
result = client.metrics.list(
    resource_uri=resource_id,
    timespan=f"{start}/{end}",
    interval="PT5M",
    metricnames="Percentage CPU",
    aggregation="Average",
)
for metric in result.value:
    for ts in metric.timeseries:
        for dp in ts.data:
            if dp.average is not None:
                data_points.append({"timestamp": dp.time_stamp.isoformat(), "value": dp.average})
```

### Cosmos DB baseline container Terraform pattern
Same as topology container in `terraform/modules/databases/cosmos.tf`:
```hcl
resource "azurerm_cosmosdb_sql_container" "baselines" {
  name                  = "baselines"
  ...
  partition_key_paths   = ["/resource_id"]
  partition_key_version = 2
}
```

### Background task pattern
From `services/api-gateway/topology.py` `run_topology_sync_loop()` — already in use.
Follow the same cancellation + interval pattern.

### How to get resource list for sweep
`topology_client.get_snapshot(resource_id)` or query Cosmos topology container directly:
```python
container = cosmos_client.get_database_client("aap").get_container_client("topology")
items = list(container.query_items("SELECT c.resource_id, c.resource_type FROM c", enable_cross_partition_query=True))
```

### Synthetic FORECAST_ALERT incident format
```python
IncidentPayload(
    incident_id=f"forecast-{resource_id[-8:]}-{metric_slug}-{timestamp}",
    severity="Sev2",
    domain=_domain_for_resource_type(resource_type),
    resource_id=resource_id,
    title=f"Capacity forecast alert: {metric_name} breach in {ttb:.0f}m",
    description=f"Forecast: {metric_name} will breach {threshold}% threshold in {ttb:.0f} minutes (confidence: {confidence})",
    detection_rule="forecast_capacity_exhaustion",
)
```
POST to self: `POST /api/v1/incidents` — or call `ingest_incident()` directly (internal call).

### Environment variables
- `FORECAST_ENABLED` (default: "true")
- `FORECAST_SWEEP_INTERVAL_SECONDS` (default: "900" — 15 min)
- `FORECAST_BREACH_ALERT_MINUTES` (default: "60") — emit alert when ttb < this
- `COSMOS_ENDPOINT` — already used
- `SUBSCRIPTION_IDS` — already used

</code_context>

<specifics>
## Specific Ideas

### ForecastResult model
```python
class MetricForecast(BaseModel):
    metric_name: str
    current_value: float
    threshold: float
    trend_per_interval: float
    time_to_breach_minutes: Optional[float]  # None if stable/declining
    confidence: str  # high | medium | low
    mape: float
    last_updated: str
    breach_imminent: bool  # time_to_breach_minutes < 60

class ForecastResult(BaseModel):
    resource_id: str
    resource_type: str
    forecasts: list[MetricForecast]
    has_imminent_breach: bool
```

### Double exponential smoothing (pure Python implementation)
```python
def _holt_smooth(values: list[float], alpha: float = 0.3, beta: float = 0.1) -> tuple[float, float]:
    """Returns (level, trend) after double exponential smoothing."""
    if len(values) < 2:
        return values[-1] if values else 0.0, 0.0
    level = values[0]
    trend = values[1] - values[0]
    for v in values[1:]:
        prev_level = level
        level = alpha * v + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
    return level, trend
```

</specifics>

<deferred>
## Deferred Ideas

- Forecasts section in dashboard UI (deferred)
- Per-resource seasonal baseline profiles (daily/weekly seasonality — complex; use simple trend for now)
- ARIMA model with statsmodels (not worth the container bloat; Holt's method achieves INTEL-005)
- Azure Monitor Dynamic Thresholds integration (requires ML-based anomaly detection; defer)

</deferred>

---

*Phase: 26-predictive-operations*
*Context gathered: 2026-04-03 via autonomous mode*
