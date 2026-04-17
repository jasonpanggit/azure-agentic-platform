from __future__ import annotations
"""FinOps API endpoints — Azure Cost Management direct queries for the Web UI.

These endpoints call Azure Cost Management SDK directly (not via the FinOps agent)
for fast Web UI polling. The FinOps agent is for conversational Foundry threads.
"""

import logging
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_credential
from fastapi import Depends

# Lazy imports — SDK may not be available in all environments
try:
    from azure.mgmt.costmanagement import CostManagementClient
    from azure.mgmt.costmanagement.models import (
        QueryDefinition,
        QueryTimePeriod,
        QueryDataset,
        QueryAggregation,
        QueryGrouping,
        GranularityType,
        TimeframeType,
    )
    _COST_IMPORT_ERROR: str = ""
except Exception as _e:  # noqa: BLE001
    CostManagementClient = None  # type: ignore[assignment,misc]
    QueryDefinition = None  # type: ignore[assignment,misc]
    QueryTimePeriod = None  # type: ignore[assignment,misc]
    QueryDataset = None  # type: ignore[assignment,misc]
    QueryAggregation = None  # type: ignore[assignment,misc]
    QueryGrouping = None  # type: ignore[assignment,misc]
    GranularityType = None  # type: ignore[assignment,misc]
    TimeframeType = None  # type: ignore[assignment,misc]
    _COST_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest
    _ARG_IMPORT_ERROR: str = ""
except Exception as _e:  # noqa: BLE001
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    _ARG_IMPORT_ERROR = str(_e)

try:
    from azure.mgmt.monitor import MonitorManagementClient
    _MONITOR_IMPORT_ERROR: str = ""
except Exception as _e:  # noqa: BLE001
    MonitorManagementClient = None  # type: ignore[assignment,misc]
    _MONITOR_IMPORT_ERROR = str(_e)

router = APIRouter(prefix="/api/v1/finops", tags=["finops"])
logger = logging.getLogger(__name__)

_VALID_GROUP_BY = frozenset({"ResourceGroup", "ResourceType", "ServiceName"})
_DATA_LAG_NOTE = (
    "Azure Cost Management data has a 24–48 hour reporting lag. "
    "Values reflect costs up to 48h ago."
)

if CostManagementClient is None:
    logger.warning(
        "azure-mgmt-costmanagement unavailable: %s",
        _COST_IMPORT_ERROR or "ImportError",
    )
if ResourceGraphClient is None:
    logger.warning(
        "azure-mgmt-resourcegraph unavailable: %s",
        _ARG_IMPORT_ERROR or "ImportError",
    )
if MonitorManagementClient is None:
    logger.warning(
        "azure-mgmt-monitor unavailable: %s",
        _MONITOR_IMPORT_ERROR or "ImportError",
    )


def _build_time_period(days: int) -> "tuple[datetime, datetime]":
    """Return (from_dt, to_dt) for a look-back window of *days* days.

    Subtracts an extra 2 days from the end to account for Cost Management's
    24–48 h reporting lag so the query always covers a complete period.
    """
    now = datetime.now(timezone.utc)
    to_dt = now - timedelta(days=2)  # account for data lag
    from_dt = to_dt - timedelta(days=days)
    return from_dt, to_dt


def _parse_cost_rows(result: Any, group_by_col: str) -> "tuple[float, str, list]":
    """Parse raw CostManagementClient query result into (total, currency, breakdown).

    Returns a 3-tuple: total cost (float), currency (str), and a list of
    ``{name, cost, currency}`` dicts.  Column ordering is NOT guaranteed by the
    API, so we do a dynamic lookup by column name.
    """
    columns = [col.name for col in (result.columns or [])]

    cost_idx = next(
        (i for i, c in enumerate(columns) if c.lower() in ("cost", "pretaxcost", "totalcost")),
        None,
    )
    currency_idx = next(
        (i for i, c in enumerate(columns) if c.lower() in ("currency", "billingcurrencycode")),
        None,
    )
    group_idx = next(
        (i for i, c in enumerate(columns) if c.lower() == group_by_col.lower()),
        None,
    )

    rows = result.rows or []
    breakdown: List[Dict[str, Any]] = []
    total_cost = 0.0
    currency = "USD"

    for row in rows:
        cost = float(row[cost_idx]) if cost_idx is not None else 0.0
        cur = str(row[currency_idx]) if currency_idx is not None else "USD"
        name = str(row[group_idx]) if group_idx is not None else ""
        total_cost += cost
        currency = cur
        breakdown.append({"name": name, "cost": round(cost, 4), "currency": cur})

    breakdown.sort(key=lambda x: x["cost"], reverse=True)
    return round(total_cost, 4), currency, breakdown


# ---------------------------------------------------------------------------
# Endpoint 1 — Cost breakdown by dimension
# ---------------------------------------------------------------------------


@router.get("/cost-breakdown")
async def get_cost_breakdown(
    subscription_id: str = Query(..., description="Azure subscription GUID"),
    days: int = Query(30, ge=7, le=90, description="Look-back window in days"),
    group_by: str = Query(
        "ResourceGroup",
        description="Dimension: ResourceGroup | ResourceType | ServiceName",
    ),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return cost breakdown grouped by dimension for the subscription.

    Returns:
        {subscription_id, days, group_by, total_cost, currency,
         breakdown: [{name, cost, currency}], data_lag_note}
    """
    if group_by not in _VALID_GROUP_BY:
        return JSONResponse(
            {
                "error": f"Invalid group_by '{group_by}'. Must be one of: {sorted(_VALID_GROUP_BY)}",
                "query_status": "error",
                "data_lag_note": _DATA_LAG_NOTE,
            },
            status_code=422,
        )

    if CostManagementClient is None:
        return {
            "error": f"azure-mgmt-costmanagement not installed: {_COST_IMPORT_ERROR}" if _COST_IMPORT_ERROR else "azure-mgmt-costmanagement not installed",
            "subscription_id": subscription_id,
            "breakdown": [],
            "total_cost": 0.0,
            "data_lag_note": _DATA_LAG_NOTE,
        }

    logger.info(
        "finops.cost_breakdown | subscription_id=%s days=%d group_by=%s",
        subscription_id, days, group_by,
    )

    try:
        from_dt, to_dt = _build_time_period(days)
        scope = f"/subscriptions/{subscription_id}"

        client = CostManagementClient(credential)
        query = QueryDefinition(
            type="ActualCost",
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(from_property=from_dt, to=to_dt),
            dataset=QueryDataset(
                granularity=GranularityType.MONTHLY,
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                grouping=[QueryGrouping(type="Dimension", name=group_by)],
            ),
        )
        result = client.query.usage(scope=scope, parameters=query)
        total_cost, currency, breakdown = _parse_cost_rows(result, group_by)

        return {
            "subscription_id": subscription_id,
            "days": days,
            "group_by": group_by,
            "total_cost": total_cost,
            "currency": currency,
            "breakdown": breakdown,
            "data_lag_note": _DATA_LAG_NOTE,
        }
    except Exception as exc:
        logger.warning("finops.cost_breakdown: error | subscription_id=%s error=%s", subscription_id, exc)
        return JSONResponse(
            {"error": str(exc), "query_status": "error", "data_lag_note": _DATA_LAG_NOTE},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Endpoint 2 — Per-resource amortized cost
# ---------------------------------------------------------------------------


@router.get("/resource-cost")
async def get_resource_cost(
    subscription_id: str = Query(..., description="Azure subscription GUID"),
    resource_id: str = Query(..., description="Full ARM resource ID"),
    days: int = Query(30, ge=7, le=90, description="Look-back window in days"),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return amortized cost for a specific Azure resource.

    Returns:
        {subscription_id, resource_id, days, total_cost, currency,
         cost_type, data_lag_note}
    """
    if CostManagementClient is None:
        return {
            "error": "azure-mgmt-costmanagement not installed",
            "subscription_id": subscription_id,
            "resource_id": resource_id,
            "total_cost": 0.0,
            "data_lag_note": _DATA_LAG_NOTE,
        }

    logger.info(
        "finops.resource_cost | subscription_id=%s resource_id=%s days=%d",
        subscription_id, resource_id[:80], days,
    )

    try:
        from_dt, to_dt = _build_time_period(days)
        scope = f"/subscriptions/{subscription_id}"

        client = CostManagementClient(credential)
        query = QueryDefinition(
            type="AmortizedCost",
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(from_property=from_dt, to=to_dt),
            dataset=QueryDataset(
                granularity=GranularityType.MONTHLY,
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                filter={
                    "dimensions": {
                        "name": "ResourceId",
                        "operator": "In",
                        "values": [resource_id],
                    }
                },
            ),
        )
        result = client.query.usage(scope=scope, parameters=query)
        columns = [col.name for col in (result.columns or [])]
        cost_idx = next(
            (i for i, c in enumerate(columns) if c.lower() in ("cost", "pretaxcost", "totalcost")),
            None,
        )
        currency_idx = next(
            (i for i, c in enumerate(columns) if c.lower() in ("currency", "billingcurrencycode")),
            None,
        )
        rows = result.rows or []
        total_cost = sum(float(row[cost_idx]) for row in rows if cost_idx is not None)
        currency = str(rows[0][currency_idx]) if rows and currency_idx is not None else "USD"

        return {
            "subscription_id": subscription_id,
            "resource_id": resource_id,
            "days": days,
            "total_cost": round(total_cost, 4),
            "currency": currency,
            "cost_type": "AmortizedCost",
            "data_lag_note": _DATA_LAG_NOTE,
        }
    except Exception as exc:
        logger.warning("finops.resource_cost: error | subscription_id=%s error=%s", subscription_id, exc)
        return JSONResponse(
            {"error": str(exc), "query_status": "error", "data_lag_note": _DATA_LAG_NOTE},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Endpoint 3 — Idle resource detection
# ---------------------------------------------------------------------------


@router.get("/idle-resources")
async def get_idle_resources(
    subscription_id: str = Query(..., description="Azure subscription GUID"),
    threshold_cpu_pct: float = Query(2.0, ge=0.1, le=10.0, description="CPU % threshold for idle classification"),
    hours: int = Query(72, ge=24, le=168, description="Look-back window in hours"),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return VMs identified as idle based on CPU and network thresholds.

    Uses ARG to list VMs then queries Monitor metrics for each VM.
    Does NOT create approval records — that is done by the FinOps agent.
    Caps at 50 VMs to avoid Monitor API throttling.

    Returns:
        {subscription_id, vms_evaluated, idle_count,
         idle_resources: [{resource_id, vm_name, resource_group, avg_cpu_pct,
                           avg_network_mbps, monthly_cost_usd}]}
    """
    if ResourceGraphClient is None or MonitorManagementClient is None:
        missing = []
        if ResourceGraphClient is None:
            missing.append("azure-mgmt-resourcegraph")
        if MonitorManagementClient is None:
            missing.append("azure-mgmt-monitor")
        return {
            "error": f"Required SDK(s) not installed: {', '.join(missing)}",
            "subscription_id": subscription_id,
            "vms_evaluated": 0,
            "idle_count": 0,
            "idle_resources": [],
        }

    logger.info(
        "finops.idle_resources | subscription_id=%s threshold_cpu_pct=%.1f hours=%d",
        subscription_id, threshold_cpu_pct, hours,
    )

    try:
        # Step 1: List VMs via ARG (cap at 50)
        arg_client = ResourceGraphClient(credential)
        arg_query = QueryRequest(
            subscriptions=[subscription_id],
            query=(
                "Resources "
                "| where type == 'microsoft.compute/virtualmachines' "
                "| where properties.provisioningState == 'Succeeded' "
                "| project id, name, resourceGroup "
                "| limit 50"
            ),
        )
        arg_result = arg_client.resources(arg_query)
        vm_list = arg_result.data or []
        vms_evaluated = len(vm_list)

        if vms_evaluated == 0:
            return {
                "subscription_id": subscription_id,
                "vms_evaluated": 0,
                "idle_count": 0,
                "idle_resources": [],
            }

        # Step 2: Query Monitor metrics for each VM
        monitor_client = MonitorManagementClient(credential, subscription_id)
        timespan = f"PT{hours}H"
        idle_resources: List[Dict[str, Any]] = []

        for vm in vm_list:
            resource_id = vm.get("id", "")
            vm_name = vm.get("name", "")
            resource_group = vm.get("resourceGroup", "")

            try:
                metrics_response = monitor_client.metrics.list(
                    resource_uri=resource_id,
                    metricnames="Percentage CPU,Network In Total,Network Out Total",
                    timespan=timespan,
                    interval="PT1H",
                    aggregation="Average,Total",
                )

                avg_cpu = 0.0
                avg_network_mbps = 0.0

                for metric in (metrics_response.value or []):
                    metric_name = metric.name.value if metric.name else ""
                    timeseries = metric.timeseries or []
                    if not timeseries:
                        continue
                    data_points = timeseries[0].data or []
                    if not data_points:
                        continue

                    if "Percentage CPU" in metric_name:
                        values = [p.average for p in data_points if p.average is not None]
                        avg_cpu = sum(values) / len(values) if values else 0.0
                    elif "Network" in metric_name:
                        values = [p.total for p in data_points if p.total is not None]
                        total_bytes = sum(values) if values else 0.0
                        # Convert bytes/hour to MB/s
                        avg_network_mbps += (total_bytes / len(data_points)) / (1024 * 1024 * 3600) if data_points else 0.0

                # Both conditions must be true: CPU < threshold AND network < 1 MB/s
                if avg_cpu < threshold_cpu_pct and avg_network_mbps < 1.0:
                    idle_resources.append({
                        "resource_id": resource_id,
                        "vm_name": vm_name,
                        "resource_group": resource_group,
                        "avg_cpu_pct": round(avg_cpu, 2),
                        "avg_network_mbps": round(avg_network_mbps, 4),
                        "monthly_cost_usd": None,  # cost enrichment done by agent, not UI endpoint
                    })
            except Exception as vm_exc:
                logger.debug(
                    "finops.idle_resources: VM metrics error | vm=%s error=%s",
                    vm_name, vm_exc,
                )
                continue

        return {
            "subscription_id": subscription_id,
            "vms_evaluated": vms_evaluated,
            "idle_count": len(idle_resources),
            "idle_resources": idle_resources,
        }
    except Exception as exc:
        logger.warning("finops.idle_resources: error | subscription_id=%s error=%s", subscription_id, exc)
        return JSONResponse(
            {"error": str(exc), "query_status": "error"},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Endpoint 4 — RI utilisation (amortized-delta method)
# ---------------------------------------------------------------------------


@router.get("/ri-utilization")
async def get_ri_utilization(
    subscription_id: str = Query(..., description="Azure subscription GUID"),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return estimated RI/Savings Plan benefit using the amortized-delta method.

    Queries ActualCost and AmortizedCost at subscription scope over 30 days.
    The delta (AmortizedCost - ActualCost) approximates the RI benefit consumed.
    This method avoids the Billing Reader role requirement.

    Returns:
        {subscription_id, method, actual_cost_usd, amortized_cost_usd,
         ri_benefit_estimated_usd, utilisation_note, data_lag_note}
    """
    if CostManagementClient is None:
        return {
            "error": "azure-mgmt-costmanagement not installed",
            "subscription_id": subscription_id,
            "actual_cost_usd": None,
            "amortized_cost_usd": None,
            "ri_benefit_estimated_usd": None,
            "data_lag_note": _DATA_LAG_NOTE,
        }

    logger.info("finops.ri_utilization | subscription_id=%s", subscription_id)

    try:
        from_dt, to_dt = _build_time_period(30)
        scope = f"/subscriptions/{subscription_id}"
        client = CostManagementClient(credential)

        def _run_query(cost_type: str) -> float:
            q = QueryDefinition(
                type=cost_type,
                timeframe=TimeframeType.CUSTOM,
                time_period=QueryTimePeriod(from_property=from_dt, to=to_dt),
                dataset=QueryDataset(
                    granularity=GranularityType.MONTHLY,
                    aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                ),
            )
            res = client.query.usage(scope=scope, parameters=q)
            columns = [col.name for col in (res.columns or [])]
            cost_idx = next(
                (i for i, c in enumerate(columns) if c.lower() in ("cost", "pretaxcost", "totalcost")),
                None,
            )
            rows = res.rows or []
            return round(sum(float(r[cost_idx]) for r in rows if cost_idx is not None), 4)

        actual_cost = _run_query("ActualCost")
        amortized_cost = _run_query("AmortizedCost")
        ri_benefit = round(amortized_cost - actual_cost, 4)

        return {
            "subscription_id": subscription_id,
            "method": "amortized_delta",
            "actual_cost_usd": actual_cost,
            "amortized_cost_usd": amortized_cost,
            "ri_benefit_estimated_usd": ri_benefit,
            "utilisation_note": (
                "RI benefit estimated via AmortizedCost−ActualCost delta at subscription scope. "
                "This method does not require Billing Reader role. "
                "For exact per-reservation utilisation, use the Billing Reservations API."
            ),
            "data_lag_note": _DATA_LAG_NOTE,
        }
    except Exception as exc:
        logger.warning("finops.ri_utilization: error | subscription_id=%s error=%s", subscription_id, exc)
        return JSONResponse(
            {"error": str(exc), "query_status": "error", "data_lag_note": _DATA_LAG_NOTE},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Endpoint 5 — Month-to-date forecast + budget comparison
# ---------------------------------------------------------------------------


@router.get("/cost-forecast")
async def get_cost_forecast(
    subscription_id: str = Query(..., description="Azure subscription GUID"),
    budget_name: Optional[str] = Query(None, description="Budget name for comparison (optional)"),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return month-to-date spend, end-of-month forecast, and optional budget comparison.

    Uses ActualCost for the current month MTD, then extrapolates via burn rate.
    Optionally compares against a named budget from Cost Management.

    Returns:
        {subscription_id, current_spend_usd, forecast_month_end_usd,
         budget_amount_usd, burn_rate_pct, days_elapsed, days_in_month,
         over_budget, over_budget_pct, data_lag_note}
    """
    if CostManagementClient is None:
        return {
            "error": "azure-mgmt-costmanagement not installed",
            "subscription_id": subscription_id,
            "current_spend_usd": None,
            "forecast_month_end_usd": None,
            "data_lag_note": _DATA_LAG_NOTE,
        }

    logger.info(
        "finops.cost_forecast | subscription_id=%s budget_name=%s",
        subscription_id, budget_name,
    )

    try:
        now = datetime.now(timezone.utc)
        # Start of month
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Account for data lag: use yesterday as end
        to_dt = now - timedelta(days=2)
        days_in_month = monthrange(now.year, now.month)[1]
        days_elapsed = max((to_dt - start_of_month).days + 1, 1)

        scope = f"/subscriptions/{subscription_id}"
        client = CostManagementClient(credential)

        # MTD actual cost
        mtd_query = QueryDefinition(
            type="ActualCost",
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(from_property=start_of_month, to=to_dt),
            dataset=QueryDataset(
                granularity=GranularityType.MONTHLY,
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
            ),
        )
        mtd_result = client.query.usage(scope=scope, parameters=mtd_query)
        columns = [col.name for col in (mtd_result.columns or [])]
        cost_idx = next(
            (i for i, c in enumerate(columns) if c.lower() in ("cost", "pretaxcost", "totalcost")),
            None,
        )
        rows = mtd_result.rows or []
        current_spend = round(
            sum(float(r[cost_idx]) for r in rows if cost_idx is not None),
            4,
        )

        # Burn-rate extrapolation: current_spend / days_elapsed * days_in_month
        daily_burn = current_spend / days_elapsed if days_elapsed > 0 else 0.0
        forecast_month_end = round(daily_burn * days_in_month, 4)

        # Budget comparison (optional)
        budget_amount: Optional[float] = None
        burn_rate_pct: Optional[float] = None
        over_budget = False
        over_budget_pct: Optional[float] = None

        if budget_name:
            try:
                budget = client.budgets.get(scope=scope, budget_name=budget_name)
                budget_amount = float(budget.amount) if budget.amount is not None else None
            except Exception as budget_exc:
                logger.debug("finops.cost_forecast: budget lookup failed | error=%s", budget_exc)

        if budget_amount is not None and budget_amount > 0:
            burn_rate_pct = round((forecast_month_end / budget_amount) * 100, 1)
            over_budget = forecast_month_end > budget_amount
            over_budget_pct = round((forecast_month_end / budget_amount - 1) * 100, 1) if over_budget else 0.0

        return {
            "subscription_id": subscription_id,
            "current_spend_usd": current_spend,
            "forecast_month_end_usd": forecast_month_end,
            "budget_amount_usd": budget_amount,
            "burn_rate_pct": burn_rate_pct,
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
            "over_budget": over_budget,
            "over_budget_pct": over_budget_pct,
            "data_lag_note": _DATA_LAG_NOTE,
        }
    except Exception as exc:
        logger.warning("finops.cost_forecast: error | subscription_id=%s error=%s", subscription_id, exc)
        return JSONResponse(
            {"error": str(exc), "query_status": "error", "data_lag_note": _DATA_LAG_NOTE},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Endpoint 6 — Top cost drivers by ServiceName
# ---------------------------------------------------------------------------


@router.get("/top-cost-drivers")
async def get_top_cost_drivers(
    subscription_id: str = Query(..., description="Azure subscription GUID"),
    n: int = Query(10, ge=1, le=25, description="Number of top cost drivers to return"),
    days: int = Query(30, ge=7, le=90, description="Look-back window in days"),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return top-N Azure service cost drivers ranked by spend.

    Groups spend by ServiceName dimension, sorts descending, returns top N.

    Returns:
        {subscription_id, n, days,
         drivers: [{service_name, cost_usd, currency, rank}],
         total_cost_usd, data_lag_note}
    """
    if CostManagementClient is None:
        return {
            "error": "azure-mgmt-costmanagement not installed",
            "subscription_id": subscription_id,
            "drivers": [],
            "total_cost_usd": 0.0,
            "data_lag_note": _DATA_LAG_NOTE,
        }

    logger.info(
        "finops.top_cost_drivers | subscription_id=%s n=%d days=%d",
        subscription_id, n, days,
    )

    try:
        from_dt, to_dt = _build_time_period(days)
        scope = f"/subscriptions/{subscription_id}"

        client = CostManagementClient(credential)
        query = QueryDefinition(
            type="ActualCost",
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(from_property=from_dt, to=to_dt),
            dataset=QueryDataset(
                granularity=GranularityType.MONTHLY,
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                grouping=[QueryGrouping(type="Dimension", name="ServiceName")],
            ),
        )
        result = client.query.usage(scope=scope, parameters=query)
        total_cost, currency, breakdown = _parse_cost_rows(result, "ServiceName")

        top_n = breakdown[:n]
        drivers = [
            {
                "service_name": item["name"],
                "cost_usd": item["cost"],
                "currency": item["currency"],
                "rank": idx + 1,
            }
            for idx, item in enumerate(top_n)
        ]

        return {
            "subscription_id": subscription_id,
            "n": n,
            "days": days,
            "drivers": drivers,
            "total_cost_usd": total_cost,
            "data_lag_note": _DATA_LAG_NOTE,
        }
    except Exception as exc:
        logger.warning("finops.top_cost_drivers: error | subscription_id=%s error=%s", subscription_id, exc)
        return JSONResponse(
            {"error": str(exc), "query_status": "error", "data_lag_note": _DATA_LAG_NOTE},
            status_code=500,
        )
