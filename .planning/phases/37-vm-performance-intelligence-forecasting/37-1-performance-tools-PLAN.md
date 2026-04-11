---
wave: 1
depends_on: []
files_modified:
  - agents/compute/tools.py
  - agents/compute/requirements.txt
autonomous: true
---

# Plan 37-1: Performance Intelligence Tools

Add three new `@ai_function` tools to the compute agent: `get_vm_forecast`,
`query_vm_performance_baseline`, and `detect_performance_drift`. All follow
the established tool pattern from Phase 36 (`query_ama_guest_metrics`).

---

## Task 37-1-A: Add lazy imports for ForecasterClient and CosmosClient

<read_first>
- agents/compute/tools.py (lines 1–80 — existing lazy import block)
- services/api-gateway/forecaster.py (lines 257–448 — ForecasterClient class)
</read_first>

<action>
Append two new lazy import blocks to the existing lazy import section in
`agents/compute/tools.py`, directly after the `ContainerServiceClient` block
(after line ~67, before the `from shared.approval_manager` line):

```python
# Lazy import — azure-cosmos may not be installed in all envs
try:
    from azure.cosmos import CosmosClient
except ImportError:
    CosmosClient = None  # type: ignore[assignment,misc]

# Lazy import — ForecasterClient from api-gateway (co-located in container image)
try:
    from services.api_gateway.forecaster import ForecasterClient
except ImportError:
    ForecasterClient = None  # type: ignore[assignment,misc]
```
</action>

<acceptance_criteria>
- `grep -n "from azure.cosmos import CosmosClient" agents/compute/tools.py` returns a match
- `grep -n "from services.api_gateway.forecaster import ForecasterClient" agents/compute/tools.py` returns a match
- Both imports are inside `try/except ImportError` blocks that assign `None` on failure
- `grep -n "CosmosClient = None" agents/compute/tools.py` returns a match
- `grep -n "ForecasterClient = None" agents/compute/tools.py` returns a match
</acceptance_criteria>

---

## Task 37-1-B: Implement `get_vm_forecast` tool

<read_first>
- agents/compute/tools.py (lines 2047–2160 — `query_ama_guest_metrics` as the pattern to follow exactly)
- services/api-gateway/forecaster.py (lines 425–448 — `get_forecasts` method signature and return shape)
- .planning/phases/37-vm-performance-intelligence-forecasting/37-CONTEXT.md (decisions section)
</read_first>

<action>
Append the following function to the end of `agents/compute/tools.py` (after
the final `query_ama_guest_metrics` function). Use the exact tool pattern:
`start_time = time.monotonic()` → `instrument_tool_call` context manager →
`try/except` → return structured dict, never raise.

```python
@ai_function
def get_vm_forecast(
    resource_id: str,
    subscription_id: str,
    thread_id: str = "",
) -> Dict[str, Any]:
    """Return capacity exhaustion forecasts for a VM from the Cosmos baselines store.

    Wraps ForecasterClient.get_forecasts() to surface time-to-breach estimates,
    Holt smoothing level/trend, MAPE confidence, and an imminent_breach flag
    for CPU, memory, and disk metrics collected by the background sweep loop.

    Args:
        resource_id: ARM resource ID of the VM.
        subscription_id: Azure subscription ID (used for tracing only).
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with forecasts list. Each forecast includes: metric_name,
        time_to_breach_minutes, confidence, mape, level, trend,
        imminent_breach (bool: time_to_breach_minutes < 60).
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="get_vm_forecast",
        tool_parameters={"resource_id": resource_id, "subscription_id": subscription_id},
        correlation_id=resource_id,
        thread_id=thread_id,
    ):
        try:
            cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
            if not cosmos_endpoint:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "COSMOS_ENDPOINT environment variable is not set",
                    "resource_id": resource_id,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            if CosmosClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-cosmos not installed",
                    "resource_id": resource_id,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            if ForecasterClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "ForecasterClient not available (services.api_gateway not installed)",
                    "resource_id": resource_id,
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            cosmos_client = CosmosClient(url=cosmos_endpoint, credential=credential)
            forecaster = ForecasterClient(cosmos_client=cosmos_client, credential=credential)

            raw_forecasts = forecaster.get_forecasts(resource_id)

            forecasts: List[Dict[str, Any]] = []
            for item in raw_forecasts:
                ttb = item.get("time_to_breach_minutes")
                forecasts.append({
                    "metric_name": item.get("metric_name"),
                    "time_to_breach_minutes": ttb,
                    "confidence": item.get("confidence"),
                    "mape": item.get("mape"),
                    "level": item.get("level"),
                    "trend": item.get("trend"),
                    "threshold": item.get("threshold"),
                    "imminent_breach": ttb is not None and ttb < 60,
                    "last_updated": item.get("last_updated"),
                })

            duration_ms = int((time.monotonic() - start_time) * 1000)
            imminent_count = sum(1 for f in forecasts if f["imminent_breach"])
            logger.info(
                "get_vm_forecast: complete | resource=%s forecasts=%d imminent=%d duration_ms=%d",
                resource_id,
                len(forecasts),
                imminent_count,
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "forecasts": forecasts,
                "total_forecasts": len(forecasts),
                "imminent_breach_count": imminent_count,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("get_vm_forecast error: %s", exc)
            return {
                "error": str(exc),
                "resource_id": resource_id,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```
</action>

<acceptance_criteria>
- `grep -n "def get_vm_forecast" agents/compute/tools.py` returns a match
- `grep -n "imminent_breach" agents/compute/tools.py` returns at least 2 matches (flag assignment + return)
- `grep -n "@ai_function" agents/compute/tools.py | grep -A1 "get_vm_forecast"` confirms decorator
- `grep -n "COSMOS_ENDPOINT" agents/compute/tools.py` returns a match inside the function
- `grep -n "ForecasterClient(" agents/compute/tools.py` returns a match (instantiation)
- `grep -n '"query_status": "error"' agents/compute/tools.py` has matches in get_vm_forecast (3 early-exit paths)
- `grep -n "start_time = time.monotonic()" agents/compute/tools.py` count increases by 1
</acceptance_criteria>

---

## Task 37-1-C: Implement `query_vm_performance_baseline` tool

<read_first>
- agents/compute/tools.py (lines 2047–2160 — `query_ama_guest_metrics` KQL pattern with LogsQueryClient)
- agents/compute/tools.py (lines 2034–2044 — `_safe_float` helper)
- .planning/phases/37-vm-performance-intelligence-forecasting/37-CONTEXT.md (decisions section — Perf table fallback logic)
</read_first>

<action>
Append the following function immediately after `get_vm_forecast` in `agents/compute/tools.py`.
Uses `LogsQueryClient` (already imported). Queries the `Perf` table first for 30-day P50/P95/P99;
falls back to `InsightsMetrics` if Perf returns zero rows.

```python
@ai_function
def query_vm_performance_baseline(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    workspace_id: str,
    thread_id: str = "",
) -> Dict[str, Any]:
    """Query 30-day performance baseline percentiles (P50/P95/P99) for a VM.

    Queries the Log Analytics `Perf` table for CPU %, Memory Available MB,
    and Disk Reads/sec. Falls back to `InsightsMetrics` if the Perf table
    returns no rows (VM uses AMA instead of MMA).

    Args:
        resource_group: Azure resource group name.
        vm_name: VM name (used to filter Perf table by Computer field).
        subscription_id: Azure subscription ID.
        workspace_id: Log Analytics workspace ID.
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with per-metric percentile stats: {metric: {p50, p95, p99,
        sample_count, trend_direction}} and query_status.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="query_vm_performance_baseline",
        tool_parameters={"vm_name": vm_name, "subscription_id": subscription_id},
        correlation_id=f"{subscription_id}/{resource_group}/{vm_name}",
        thread_id=thread_id,
    ):
        try:
            if not workspace_id:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "query_status": "skipped",
                    "reason": "workspace_id is required for performance baseline query",
                    "duration_ms": duration_ms,
                }

            if LogsQueryClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-monitor-query not installed",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            client = LogsQueryClient(credential)

            # Primary: Perf table (MMA/AMA with Performance collection rule)
            perf_kql = (
                "Perf"
                f' | where Computer =~ "{vm_name}"'
                " | where TimeGenerated > ago(30d)"
                ' | where (ObjectName == "Processor" and CounterName == "% Processor Time" and InstanceName == "_Total")'
                '     or (ObjectName == "Memory" and CounterName == "Available MBytes")'
                '     or (ObjectName == "LogicalDisk" and CounterName == "Disk Reads/sec" and InstanceName == "_Total")'
                " | summarize"
                "     p50  = percentile(CounterValue, 50),"
                "     p95  = percentile(CounterValue, 95),"
                "     p99  = percentile(CounterValue, 99),"
                "     sample_count = count()"
                "     by ObjectName, CounterName"
            )

            response = client.query_workspace(
                workspace_id=workspace_id,
                query=perf_kql,
                timespan="P30D",
            )

            metrics: Dict[str, Any] = {}
            used_fallback = False

            if response.status == LogsQueryStatus.SUCCESS:
                for table in response.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        row_dict = dict(zip(col_names, row))
                        obj = row_dict.get("ObjectName", "")
                        counter = row_dict.get("CounterName", "")
                        if obj == "Processor":
                            key = "cpu_pct"
                        elif obj == "Memory":
                            key = "memory_available_mb"
                        elif obj == "LogicalDisk" and "Disk Reads" in counter:
                            key = "disk_reads_per_sec"
                        else:
                            continue
                        metrics[key] = {
                            "p50": _safe_float(row_dict.get("p50")),
                            "p95": _safe_float(row_dict.get("p95")),
                            "p99": _safe_float(row_dict.get("p99")),
                            "sample_count": int(row_dict.get("sample_count") or 0),
                            "trend_direction": "unknown",
                        }

            # Fallback: InsightsMetrics (AMA without Perf DCR)
            if not metrics:
                used_fallback = True
                resource_id = (
                    f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                    f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
                )
                fallback_kql = (
                    "InsightsMetrics"
                    f' | where _ResourceId =~ "{resource_id}"'
                    " | where TimeGenerated > ago(30d)"
                    ' | where (Namespace == "Processor" and Name == "UtilizationPercentage")'
                    '     or (Namespace == "Memory" and Name == "AvailableMB")'
                    '     or (Namespace == "LogicalDisk" and Name == "ReadsPerSecond")'
                    " | summarize"
                    "     p50  = percentile(Val, 50),"
                    "     p95  = percentile(Val, 95),"
                    "     p99  = percentile(Val, 99),"
                    "     sample_count = count()"
                    "     by Namespace, Name"
                )
                fallback_resp = client.query_workspace(
                    workspace_id=workspace_id,
                    query=fallback_kql,
                    timespan="P30D",
                )
                if fallback_resp.status == LogsQueryStatus.SUCCESS:
                    for table in fallback_resp.tables:
                        col_names = [col.name for col in table.columns]
                        for row in table.rows:
                            row_dict = dict(zip(col_names, row))
                            ns = row_dict.get("Namespace", "")
                            name = row_dict.get("Name", "")
                            if ns == "Processor":
                                key = "cpu_pct"
                            elif ns == "Memory":
                                key = "memory_available_mb"
                            elif ns == "LogicalDisk" and "Reads" in name:
                                key = "disk_reads_per_sec"
                            else:
                                continue
                            metrics[key] = {
                                "p50": _safe_float(row_dict.get("p50")),
                                "p95": _safe_float(row_dict.get("p95")),
                                "p99": _safe_float(row_dict.get("p99")),
                                "sample_count": int(row_dict.get("sample_count") or 0),
                                "trend_direction": "unknown",
                            }

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "query_vm_performance_baseline: complete | vm=%s metrics=%d fallback=%s duration_ms=%d",
                vm_name,
                len(metrics),
                used_fallback,
                duration_ms,
            )
            return {
                "vm_name": vm_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "workspace_id": workspace_id,
                "baseline_window_days": 30,
                "metrics": metrics,
                "metric_count": len(metrics),
                "used_fallback_table": used_fallback,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("query_vm_performance_baseline error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```
</action>

<acceptance_criteria>
- `grep -n "def query_vm_performance_baseline" agents/compute/tools.py` returns a match
- `grep -n "Perf" agents/compute/tools.py` returns at least 2 matches (primary KQL table reference)
- `grep -n "InsightsMetrics" agents/compute/tools.py | wc -l` shows multiple matches (baseline + existing AMA tool)
- `grep -n "used_fallback" agents/compute/tools.py` returns matches for flag assignment and return key
- `grep -n "baseline_window_days" agents/compute/tools.py` returns a match in the return dict
- `grep -n '"P30D"' agents/compute/tools.py` returns at least 2 matches (Perf query + fallback)
- `grep -n "query_status.*skipped" agents/compute/tools.py | grep -i "workspace"` confirms workspace_id guard
</acceptance_criteria>

---

## Task 37-1-D: Implement `detect_performance_drift` tool

<read_first>
- agents/compute/tools.py — `query_vm_performance_baseline` just added (understand Perf/InsightsMetrics KQL shape)
- agents/compute/tools.py (lines 2034–2044 — `_safe_float` helper)
- .planning/phases/37-vm-performance-intelligence-forecasting/37-CONTEXT.md (decisions — drift score formula, threshold 30, narrative examples)
</read_first>

<action>
Append the following function immediately after `query_vm_performance_baseline` in
`agents/compute/tools.py`. Queries last 24h avg/P95 against 30-day P95 baseline;
drift score formula: `min(100, int((recent_p95 / baseline_p95 - 1) * 100))`.

```python
@ai_function
def detect_performance_drift(
    resource_group: str,
    vm_name: str,
    subscription_id: str,
    workspace_id: str,
    thread_id: str = "",
) -> Dict[str, Any]:
    """Detect performance drift by comparing last 24h against 30-day baseline.

    Computes a drift score (0–100) per metric. A score of 0 means no drift;
    100 means the recent P95 is 2x the baseline P95.
    Flags the VM as drifting when any metric drift_score exceeds 30.

    Drift score formula: min(100, int((recent_p95 / baseline_p95 - 1) * 100))

    Args:
        resource_group: Azure resource group name.
        vm_name: VM name.
        subscription_id: Azure subscription ID.
        workspace_id: Log Analytics workspace ID.
        thread_id: Foundry thread ID for tracing.

    Returns:
        Dict with per-metric drift_score, recent_p95, baseline_p95, narrative,
        is_drifting (bool), and query_status.
    """
    start_time = time.monotonic()
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="compute-agent",
        agent_id=agent_id,
        tool_name="detect_performance_drift",
        tool_parameters={"vm_name": vm_name, "subscription_id": subscription_id},
        correlation_id=f"{subscription_id}/{resource_group}/{vm_name}",
        thread_id=thread_id,
    ):
        try:
            if not workspace_id:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "query_status": "skipped",
                    "reason": "workspace_id is required for drift detection",
                    "duration_ms": duration_ms,
                }

            if LogsQueryClient is None:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return {
                    "error": "azure-monitor-query not installed",
                    "query_status": "error",
                    "duration_ms": duration_ms,
                }

            credential = get_credential()
            client = LogsQueryClient(credential)

            # 30-day baseline: P95 per metric
            baseline_kql = (
                "Perf"
                f' | where Computer =~ "{vm_name}"'
                " | where TimeGenerated > ago(30d)"
                ' | where (ObjectName == "Processor" and CounterName == "% Processor Time" and InstanceName == "_Total")'
                '     or (ObjectName == "Memory" and CounterName == "Available MBytes")'
                '     or (ObjectName == "LogicalDisk" and CounterName == "Disk Reads/sec" and InstanceName == "_Total")'
                " | summarize baseline_p95 = percentile(CounterValue, 95) by ObjectName, CounterName"
            )
            baseline_resp = client.query_workspace(
                workspace_id=workspace_id,
                query=baseline_kql,
                timespan="P30D",
            )

            # 24h recent: avg and P95 per metric
            recent_kql = (
                "Perf"
                f' | where Computer =~ "{vm_name}"'
                " | where TimeGenerated > ago(24h)"
                ' | where (ObjectName == "Processor" and CounterName == "% Processor Time" and InstanceName == "_Total")'
                '     or (ObjectName == "Memory" and CounterName == "Available MBytes")'
                '     or (ObjectName == "LogicalDisk" and CounterName == "Disk Reads/sec" and InstanceName == "_Total")'
                " | summarize"
                "     recent_avg = avg(CounterValue),"
                "     recent_p95 = percentile(CounterValue, 95)"
                "     by ObjectName, CounterName"
            )
            recent_resp = client.query_workspace(
                workspace_id=workspace_id,
                query=recent_kql,
                timespan="PT24H",
            )

            # Parse baseline
            baseline_p95: Dict[str, float] = {}
            if baseline_resp.status == LogsQueryStatus.SUCCESS:
                for table in baseline_resp.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        row_dict = dict(zip(col_names, row))
                        obj = row_dict.get("ObjectName", "")
                        if obj == "Processor":
                            key = "cpu_pct"
                        elif obj == "Memory":
                            key = "memory_available_mb"
                        elif obj == "LogicalDisk":
                            key = "disk_reads_per_sec"
                        else:
                            continue
                        val = _safe_float(row_dict.get("baseline_p95"))
                        if val is not None:
                            baseline_p95[key] = val

            # Parse recent
            recent_avg: Dict[str, float] = {}
            recent_p95_vals: Dict[str, float] = {}
            if recent_resp.status == LogsQueryStatus.SUCCESS:
                for table in recent_resp.tables:
                    col_names = [col.name for col in table.columns]
                    for row in table.rows:
                        row_dict = dict(zip(col_names, row))
                        obj = row_dict.get("ObjectName", "")
                        if obj == "Processor":
                            key = "cpu_pct"
                        elif obj == "Memory":
                            key = "memory_available_mb"
                        elif obj == "LogicalDisk":
                            key = "disk_reads_per_sec"
                        else:
                            continue
                        avg_val = _safe_float(row_dict.get("recent_avg"))
                        p95_val = _safe_float(row_dict.get("recent_p95"))
                        if avg_val is not None:
                            recent_avg[key] = avg_val
                        if p95_val is not None:
                            recent_p95_vals[key] = p95_val

            # Compute drift scores
            drift_metrics: Dict[str, Any] = {}
            narrative_parts: List[str] = []
            is_drifting = False

            all_keys = set(baseline_p95.keys()) | set(recent_p95_vals.keys())
            for key in sorted(all_keys):
                b_p95 = baseline_p95.get(key)
                r_p95 = recent_p95_vals.get(key)
                r_avg = recent_avg.get(key)

                # Guard against zero/None baseline
                if b_p95 is None or b_p95 == 0.0:
                    drift_score = 0
                elif r_p95 is None:
                    drift_score = 0
                else:
                    drift_score = min(100, int((r_p95 / b_p95 - 1) * 100))
                    drift_score = max(0, drift_score)

                drifting_metric = drift_score > 30
                if drifting_metric:
                    is_drifting = True

                drift_metrics[key] = {
                    "drift_score": drift_score,
                    "recent_avg": r_avg,
                    "recent_p95": r_p95,
                    "baseline_p95": b_p95,
                    "is_drifting": drifting_metric,
                }

                # Build narrative fragment
                metric_label = {
                    "cpu_pct": "CPU",
                    "memory_available_mb": "Memory Available",
                    "disk_reads_per_sec": "Disk Reads/sec",
                }.get(key, key)

                if r_p95 is not None and b_p95 is not None and b_p95 > 0:
                    if drifting_metric:
                        narrative_parts.append(
                            f"{metric_label} P95 is {r_p95:.1f} (baseline {b_p95:.1f}) "
                            f"— {drift_score}% above normal."
                        )
                    else:
                        narrative_parts.append(f"{metric_label} within normal range.")
                else:
                    narrative_parts.append(f"{metric_label} — insufficient data.")

            narrative = " ".join(narrative_parts) if narrative_parts else "No performance data available."

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "detect_performance_drift: complete | vm=%s is_drifting=%s metrics=%d duration_ms=%d",
                vm_name,
                is_drifting,
                len(drift_metrics),
                duration_ms,
            )
            return {
                "vm_name": vm_name,
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "workspace_id": workspace_id,
                "is_drifting": is_drifting,
                "drift_metrics": drift_metrics,
                "narrative": narrative,
                "query_status": "success",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("detect_performance_drift error: %s", exc)
            return {
                "error": str(exc),
                "vm_name": vm_name,
                "query_status": "error",
                "duration_ms": duration_ms,
            }
```
</action>

<acceptance_criteria>
- `grep -n "def detect_performance_drift" agents/compute/tools.py` returns a match
- `grep -n "drift_score" agents/compute/tools.py` returns at least 5 matches (formula, assignment, dict key, return, test)
- `grep -n "is_drifting" agents/compute/tools.py` returns matches including the `> 30` threshold check
- `grep -n "min(100" agents/compute/tools.py` returns a match in detect_performance_drift
- `grep -n "narrative" agents/compute/tools.py` returns matches for narrative string construction and return key
- `grep -n "baseline_p95" agents/compute/tools.py` returns multiple matches (dict key, comparison, return)
- `grep -n '"query_status": "skipped"' agents/compute/tools.py | grep -i "drift"` confirms workspace guard
</acceptance_criteria>

---

## Task 37-1-E: Add `azure-cosmos` to compute requirements.txt

<read_first>
- agents/compute/requirements.txt (full file — check if azure-cosmos is already present)
</read_first>

<action>
Read `agents/compute/requirements.txt`. If `azure-cosmos` is NOT already listed,
append the following line:

```
azure-cosmos>=4.0.0
```

If it is already present, no change needed (note it in the task completion).
</action>

<acceptance_criteria>
- `grep "azure-cosmos" agents/compute/requirements.txt` returns a match with version `>=4.0.0`
- File is valid (no duplicate entries, no blank lines inserted mid-file)
</acceptance_criteria>

---

## Verification

```bash
# Confirm all 3 tool functions exist
grep -n "^def get_vm_forecast\|^def query_vm_performance_baseline\|^def detect_performance_drift" agents/compute/tools.py

# Confirm lazy imports added
grep -n "CosmosClient = None\|ForecasterClient = None" agents/compute/tools.py

# Confirm imminent_breach field
grep -n "imminent_breach" agents/compute/tools.py

# Confirm drift score formula
grep -n "min(100" agents/compute/tools.py

# Confirm requirements
grep "azure-cosmos" agents/compute/requirements.txt
```

## must_haves

- `get_vm_forecast` function defined with `@ai_function` decorator and returns `imminent_breach` boolean
- `query_vm_performance_baseline` function queries `Perf` table with 30-day window (`P30D`) and falls back to `InsightsMetrics`
- `detect_performance_drift` function returns per-metric `drift_score` dict and `is_drifting` boolean
- `azure-cosmos>=4.0.0` present in `agents/compute/requirements.txt`
- Both `CosmosClient` and `ForecasterClient` have module-level lazy imports with `= None` fallback
