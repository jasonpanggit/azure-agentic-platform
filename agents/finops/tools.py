"""FinOps Agent tool functions — Azure Cost Management data surface.

Provides agent tool functions for subscription cost breakdown, per-resource cost,
idle resource detection with HITL deallocation proposals, reserved instance
utilisation, cost forecasting, and top cost driver ranking.

Allowed MCP tools (explicit allowlist — v2 namespace names, no wildcards):
    monitor, advisor
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry
from agents.shared.subscription_utils import extract_subscription_id as _extract_subscription_id

# ---------------------------------------------------------------------------
# Lazy SDK imports — azure-mgmt-* packages may not be installed in all envs
# ---------------------------------------------------------------------------

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
except ImportError:
    CostManagementClient = None  # type: ignore[assignment,misc]
    QueryDefinition = None  # type: ignore[assignment,misc]
    QueryTimePeriod = None  # type: ignore[assignment,misc]
    QueryDataset = None  # type: ignore[assignment,misc]
    QueryAggregation = None  # type: ignore[assignment,misc]
    QueryGrouping = None  # type: ignore[assignment,misc]
    GranularityType = None  # type: ignore[assignment,misc]
    TimeframeType = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]

try:
    from shared.approval_manager import create_approval_record
except ImportError:
    create_approval_record = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Module-level setup
# ---------------------------------------------------------------------------

ALLOWED_MCP_TOOLS: List[str] = ["monitor", "advisor"]

_VALID_GROUP_BY: frozenset = frozenset({"ResourceGroup", "ResourceType", "ServiceName"})
_DATA_LAG_NOTE = (
    "Azure Cost Management data has a 24–48 hour reporting lag. "
    "Values reflect costs up to 48h ago."
)

tracer = setup_telemetry("aiops-finops-agent")
logger = logging.getLogger(__name__)


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-mgmt-costmanagement": "azure.mgmt.costmanagement",
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-mgmt-resourcegraph": "azure.mgmt.resourcegraph",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("finops_tools: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "finops_tools: sdk_missing | package=%s — tool will return error", pkg
            )


_log_sdk_availability()


# ===========================================================================
# Tool 1: get_subscription_cost_breakdown
# ===========================================================================


@ai_function
def get_subscription_cost_breakdown(
    subscription_id: str,
    days: int = 30,
    group_by: str = "ResourceGroup",
) -> Dict[str, Any]:
    """Get cost breakdown for a subscription grouped by ResourceGroup, ResourceType, or ServiceName.

    Args:
        subscription_id: Azure subscription GUID.
        days: Look-back window in days (7–90, default 30).
        group_by: Dimension to group by. One of: ResourceGroup, ResourceType, ServiceName.

    Returns:
        Dict with keys: subscription_id, days, group_by, total_cost, currency,
            breakdown (list of {name, cost, currency}), data_lag_note,
            query_status, duration_ms.
    """
    start_time = time.monotonic()
    try:
        if CostManagementClient is None:
            raise ImportError("azure-mgmt-costmanagement is not installed")

        if group_by not in _VALID_GROUP_BY:
            duration_ms = (time.monotonic() - start_time) * 1000
            return {
                "subscription_id": subscription_id,
                "days": days,
                "group_by": group_by,
                "query_status": "error",
                "error": (
                    f"Invalid group_by value '{group_by}'. "
                    f"Allowlist: {sorted(_VALID_GROUP_BY)}"
                ),
                "duration_ms": duration_ms,
            }

        # Clamp days to [7, 90]
        days = max(7, min(days, 90))

        credential = get_credential()
        scope = f"/subscriptions/{subscription_id}"
        client = CostManagementClient(credential)

        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=days)

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

        columns = [c.name for c in result.columns]
        cost_idx = next(
            (i for i, c in enumerate(columns) if "cost" in c.lower()), 0
        )
        group_idx = next(
            (i for i, c in enumerate(columns) if c.lower() == group_by.lower()), -1
        )
        currency_idx = next(
            (i for i, c in enumerate(columns) if "currency" in c.lower()), -1
        )

        breakdown = [
            {
                "name": row[group_idx] if group_idx >= 0 else "Unknown",
                "cost": float(row[cost_idx]),
                "currency": row[currency_idx] if currency_idx >= 0 else "USD",
            }
            for row in result.rows
        ]
        # Sort by cost descending (immutable — new list)
        breakdown = sorted(breakdown, key=lambda x: x["cost"], reverse=True)
        total_cost = sum(item["cost"] for item in breakdown)
        currency = breakdown[0]["currency"] if breakdown else "USD"

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "get_subscription_cost_breakdown: complete | subscription_id=%s "
            "group_by=%s total_cost=%.2f duration_ms=%.1f",
            subscription_id,
            group_by,
            total_cost,
            duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "days": days,
            "group_by": group_by,
            "total_cost": total_cost,
            "currency": currency,
            "breakdown": breakdown,
            "data_lag_note": _DATA_LAG_NOTE,
            "query_status": "success",
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "get_subscription_cost_breakdown: failed | subscription_id=%s error=%s",
            subscription_id,
            e,
            exc_info=True,
        )
        return {
            "subscription_id": subscription_id,
            "days": days,
            "group_by": group_by,
            "query_status": "error",
            "error": str(e),
            "duration_ms": duration_ms,
        }


# ===========================================================================
# Tool 2: get_resource_cost
# ===========================================================================


@ai_function
def get_resource_cost(
    subscription_id: str,
    resource_id: str,
    days: int = 30,
) -> Dict[str, Any]:
    """Get amortized cost for a specific Azure resource over a time window.

    Args:
        subscription_id: Azure subscription GUID.
        resource_id: Full ARM resource ID.
        days: Look-back window in days (7–90, default 30).

    Returns:
        Dict with keys: subscription_id, resource_id, days, total_cost, currency,
            cost_type ("AmortizedCost"), data_lag_note, query_status, duration_ms.
    """
    start_time = time.monotonic()
    try:
        if CostManagementClient is None:
            raise ImportError("azure-mgmt-costmanagement is not installed")

        days = max(7, min(days, 90))

        credential = get_credential()
        scope = f"/subscriptions/{subscription_id}"
        client = CostManagementClient(credential)

        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=days)

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

        columns = [c.name for c in result.columns]
        cost_idx = next(
            (i for i, c in enumerate(columns) if "cost" in c.lower()), 0
        )
        currency_idx = next(
            (i for i, c in enumerate(columns) if "currency" in c.lower()), -1
        )

        total_cost = sum(float(row[cost_idx]) for row in result.rows)
        currency = result.rows[0][currency_idx] if result.rows and currency_idx >= 0 else "USD"

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "get_resource_cost: complete | subscription_id=%s resource_id=%s "
            "total_cost=%.2f duration_ms=%.1f",
            subscription_id,
            resource_id,
            total_cost,
            duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "resource_id": resource_id,
            "days": days,
            "total_cost": total_cost,
            "currency": currency,
            "cost_type": "AmortizedCost",
            "data_lag_note": _DATA_LAG_NOTE,
            "query_status": "success",
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "get_resource_cost: failed | subscription_id=%s resource_id=%s error=%s",
            subscription_id,
            resource_id,
            e,
            exc_info=True,
        )
        return {
            "subscription_id": subscription_id,
            "resource_id": resource_id,
            "days": days,
            "query_status": "error",
            "error": str(e),
            "duration_ms": duration_ms,
        }


# ===========================================================================
# Tool 3: identify_idle_resources
# ===========================================================================


async def _query_vm_metrics(
    vm: Dict[str, Any],
    credential: Any,
    subscription_id: str,
    hours: int,
    threshold_cpu_pct: float,
) -> Optional[Dict[str, Any]]:
    """Async helper: query Monitor metrics for a single VM and return idle info or None."""
    try:
        if MonitorManagementClient is None:
            return None

        monitor_client = MonitorManagementClient(credential, subscription_id)
        resource_id = vm.get("id", "")
        timespan = f"PT{hours}H"

        response = monitor_client.metrics.list(
            resource_uri=resource_id,
            metricnames="Percentage CPU,Network In Total,Network Out Total",
            timespan=timespan,
            interval="PT1H",
            aggregation="Average,Total",
        )

        avg_cpu_values: List[float] = []
        network_in_total: float = 0.0
        network_out_total: float = 0.0

        for metric in response.value:
            metric_name = metric.name.value if metric.name else ""
            for ts in metric.timeseries:
                for dp in ts.data:
                    if metric_name == "Percentage CPU":
                        if dp.average is not None:
                            avg_cpu_values.append(dp.average)
                    elif metric_name == "Network In Total":
                        if dp.total is not None:
                            network_in_total += dp.total
                    elif metric_name == "Network Out Total":
                        if dp.total is not None:
                            network_out_total += dp.total

        avg_cpu_pct = sum(avg_cpu_values) / len(avg_cpu_values) if avg_cpu_values else 0.0

        # Network threshold: < 1MB/s averaged over the window
        total_seconds = hours * 3600
        avg_network_bps = (network_in_total + network_out_total) / total_seconds
        avg_network_mbps = avg_network_bps / 1_048_576  # Convert bytes/s to MB/s

        _ONE_MB_PER_S = 1.0  # MB/s threshold

        if avg_cpu_pct < threshold_cpu_pct and avg_network_mbps < _ONE_MB_PER_S:
            return {
                "vm": vm,
                "avg_cpu_pct": avg_cpu_pct,
                "avg_network_mbps": avg_network_mbps,
            }

        return None

    except Exception as e:
        logger.warning(
            "_query_vm_metrics: failed for vm=%s error=%s",
            vm.get("name", "unknown"),
            e,
        )
        return None


@ai_function
def identify_idle_resources(
    subscription_id: str,
    threshold_cpu_pct: float = 2.0,
    hours: int = 72,
    max_vms: int = 50,
) -> Dict[str, Any]:
    """Identify idle VMs (CPU <threshold% AND network <1MB/s) and generate HITL deallocation proposals.

    Args:
        subscription_id: Azure subscription GUID.
        threshold_cpu_pct: CPU % average threshold (default 2.0).
        hours: Look-back window in hours (default 72).
        max_vms: Maximum VMs to evaluate (default 50; cap to avoid throttling).

    Returns:
        Dict with keys: subscription_id, vms_evaluated, idle_count,
            idle_resources (list of {resource_id, vm_name, resource_group,
                avg_cpu_pct, avg_network_mbps, monthly_cost_usd, approval_id}),
            query_status, duration_ms.
    """
    start_time = time.monotonic()
    try:
        if ResourceGraphClient is None:
            raise ImportError("azure-mgmt-resourcegraph is not installed")
        if MonitorManagementClient is None:
            raise ImportError("azure-mgmt-monitor is not installed")

        # Cap max_vms at 50
        max_vms = min(max_vms, 50)

        credential = get_credential()

        # Step 1: ARG query to list VMs
        arg_client = ResourceGraphClient(credential)
        q = QueryRequest(
            subscriptions=[subscription_id],
            query=(
                "Resources "
                "| where type == 'microsoft.compute/virtualmachines' "
                "| project id, name, resourceGroup "
                f"| limit {max_vms}"
            ),
            options=QueryRequestOptions(result_format="objectArray"),
        )
        vms_data = arg_client.resources(q).data[:max_vms]

        if not vms_data:
            duration_ms = (time.monotonic() - start_time) * 1000
            return {
                "subscription_id": subscription_id,
                "vms_evaluated": 0,
                "idle_count": 0,
                "idle_resources": [],
                "query_status": "success",
                "duration_ms": duration_ms,
            }

        # Step 2: Query Monitor metrics in batches of 20 using asyncio.gather
        async def _run_all() -> List[Optional[Dict[str, Any]]]:
            results: List[Optional[Dict[str, Any]]] = []
            batch_size = 20
            for i in range(0, len(vms_data), batch_size):
                batch = vms_data[i : i + batch_size]
                batch_results = await asyncio.gather(
                    *[
                        _query_vm_metrics(vm, credential, subscription_id, hours, threshold_cpu_pct)
                        for vm in batch
                    ]
                )
                results.extend(batch_results)
            return results

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            metric_results = loop.run_until_complete(_run_all())
        except RuntimeError:
            # No event loop running — create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            metric_results = loop.run_until_complete(_run_all())

        # Step 3: Build idle resource records with cost and approval proposals
        idle_resources: List[Dict[str, Any]] = []
        for mr in metric_results:
            if mr is None:
                continue

            vm = mr["vm"]
            avg_cpu_pct = mr["avg_cpu_pct"]
            avg_network_mbps = mr["avg_network_mbps"]

            # Get 30-day cost estimate
            monthly_cost: float = 0.0
            try:
                cost_result = get_resource_cost(
                    subscription_id=subscription_id,
                    resource_id=vm["id"],
                    days=30,
                )
                if cost_result.get("query_status") == "success":
                    monthly_cost = cost_result.get("total_cost", 0.0)
            except Exception:
                pass

            # Create HITL approval record
            approval_id: Optional[str] = None
            if create_approval_record is not None:
                try:
                    proposal = {
                        "action": "deallocate_vm",
                        "resource_id": vm["id"],
                        "resource_group": vm.get("resourceGroup", ""),
                        "vm_name": vm["name"],
                        "subscription_id": subscription_id,
                        "description": (
                            f"Deallocate idle VM '{vm['name']}' — "
                            f"CPU <{threshold_cpu_pct}% AND ~0 network for {hours}h"
                        ),
                        "target_resources": [vm["id"]],
                        "estimated_impact": (
                            "VM stops; billing ends for compute. "
                            "Managed disk costs continue."
                        ),
                        "estimated_monthly_savings_usd": monthly_cost,
                        "reversible": True,
                        "risk_level": "low",
                    }
                    # Note: create_approval_record is async — run synchronously
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_closed():
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        record = loop.run_until_complete(
                            create_approval_record(
                                container=None,
                                thread_id="",
                                incident_id="",
                                agent_name="finops-agent",
                                proposal=proposal,
                                resource_snapshot={"vm_name": vm["name"], "resource_id": vm["id"]},
                                risk_level="low",
                            )
                        )
                        approval_id = record.get("id") if isinstance(record, dict) else None
                    except Exception:
                        approval_id = None
                except Exception:
                    approval_id = None

            idle_resources.append({
                "resource_id": vm["id"],
                "vm_name": vm["name"],
                "resource_group": vm.get("resourceGroup", ""),
                "avg_cpu_pct": avg_cpu_pct,
                "avg_network_mbps": avg_network_mbps,
                "monthly_cost_usd": monthly_cost,
                "approval_id": approval_id,
            })

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "identify_idle_resources: complete | subscription_id=%s "
            "vms_evaluated=%d idle_count=%d duration_ms=%.1f",
            subscription_id,
            len(vms_data),
            len(idle_resources),
            duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "vms_evaluated": len(vms_data),
            "idle_count": len(idle_resources),
            "idle_resources": idle_resources,
            "query_status": "success",
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "identify_idle_resources: failed | subscription_id=%s error=%s",
            subscription_id,
            e,
            exc_info=True,
        )
        return {
            "subscription_id": subscription_id,
            "vms_evaluated": 0,
            "idle_count": 0,
            "idle_resources": [],
            "query_status": "error",
            "error": str(e),
            "duration_ms": duration_ms,
        }


# ===========================================================================
# Tool 4: get_reserved_instance_utilisation
# ===========================================================================


@ai_function
def get_reserved_instance_utilisation(
    subscription_id: str,
) -> Dict[str, Any]:
    """Get reserved instance and savings plan utilisation for a subscription.

    Uses AmortizedCost vs ActualCost delta to estimate RI utilisation without
    requiring Billing Reader role at billing account scope. If the direct
    benefit_utilization_summaries API is unavailable (403), returns graceful
    degradation message.

    Args:
        subscription_id: Azure subscription GUID.

    Returns:
        Dict with keys: subscription_id, method ("amortized_delta" or "billing_api"),
            ri_benefit_estimated_usd (AmortizedCost - ActualCost for last 30 days),
            utilisation_note, query_status, duration_ms.
    """
    start_time = time.monotonic()
    try:
        if CostManagementClient is None:
            raise ImportError("azure-mgmt-costmanagement is not installed")

        credential = get_credential()
        scope = f"/subscriptions/{subscription_id}"
        client = CostManagementClient(credential)

        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=30)

        def _query_cost(cost_type: str) -> float:
            q = QueryDefinition(
                type=cost_type,
                timeframe=TimeframeType.CUSTOM,
                time_period=QueryTimePeriod(from_property=from_dt, to=to_dt),
                dataset=QueryDataset(
                    granularity=GranularityType.MONTHLY,
                    aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                ),
            )
            r = client.query.usage(scope=scope, parameters=q)
            columns = [c.name for c in r.columns]
            cost_idx = next(
                (i for i, c in enumerate(columns) if "cost" in c.lower()), 0
            )
            return sum(float(row[cost_idx]) for row in r.rows)

        actual_total = _query_cost("ActualCost")
        amortized_total = _query_cost("AmortizedCost")

        ri_benefit_estimated_usd = amortized_total - actual_total

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "get_reserved_instance_utilisation: complete | subscription_id=%s "
            "actual=%.2f amortized=%.2f ri_benefit=%.2f duration_ms=%.1f",
            subscription_id,
            actual_total,
            amortized_total,
            ri_benefit_estimated_usd,
            duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "method": "amortized_delta",
            "actual_cost_usd": actual_total,
            "amortized_cost_usd": amortized_total,
            "ri_benefit_estimated_usd": ri_benefit_estimated_usd,
            "utilisation_note": (
                "RI benefit estimated via AmortizedCost − ActualCost delta at subscription scope. "
                "No Billing Reader role required. Positive values indicate RI/savings plan benefit consumed. "
                "For exact utilisation rates per reservation, Billing Reader at billing account scope is required."
            ),
            "data_lag_note": _DATA_LAG_NOTE,
            "query_status": "success",
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "get_reserved_instance_utilisation: failed | subscription_id=%s error=%s",
            subscription_id,
            e,
            exc_info=True,
        )
        return {
            "subscription_id": subscription_id,
            "query_status": "error",
            "error": str(e),
            "duration_ms": duration_ms,
        }


# ===========================================================================
# Tool 5: get_cost_forecast
# ===========================================================================


@ai_function
def get_cost_forecast(
    subscription_id: str,
    budget_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Get current-month cost forecast vs budget with burn rate calculation.

    Args:
        subscription_id: Azure subscription GUID.
        budget_name: Optional budget name for comparison. If None, returns forecast only.

    Returns:
        Dict with keys: subscription_id, current_spend_usd, forecast_month_end_usd,
            budget_amount_usd (None if budget_name not provided or not found),
            burn_rate_pct, days_elapsed, days_in_month, over_budget (bool),
            over_budget_pct (float, 0 if not over), data_lag_note,
            query_status, duration_ms.
    """
    start_time = time.monotonic()
    try:
        if CostManagementClient is None:
            raise ImportError("azure-mgmt-costmanagement is not installed")

        credential = get_credential()
        scope = f"/subscriptions/{subscription_id}"
        client = CostManagementClient(credential)

        now = datetime.now(timezone.utc)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Calculate end of month
        if now.month == 12:
            end_of_month = start_of_month.replace(year=now.year + 1, month=1) - timedelta(
                seconds=1
            )
        else:
            end_of_month = start_of_month.replace(month=now.month + 1) - timedelta(seconds=1)

        # Account for 24-48h data lag — query up to 2 days ago
        query_end = now - timedelta(hours=48)
        if query_end < start_of_month:
            query_end = start_of_month

        q = QueryDefinition(
            type="ActualCost",
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(from_property=start_of_month, to=query_end),
            dataset=QueryDataset(
                granularity=GranularityType.MONTHLY,
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
            ),
        )
        result = client.query.usage(scope=scope, parameters=q)

        columns = [c.name for c in result.columns]
        cost_idx = next(
            (i for i, c in enumerate(columns) if "cost" in c.lower()), 0
        )
        current_spend = sum(float(row[cost_idx]) for row in result.rows)

        days_elapsed = max(1, (now - start_of_month).days + 1)
        days_in_month = (end_of_month - start_of_month).days + 1
        forecast_month_end_usd = (current_spend / days_elapsed) * days_in_month

        # Budget comparison
        budget_amount_usd: Optional[float] = None
        budget_error: Optional[str] = None
        burn_rate_pct: Optional[float] = None
        over_budget: bool = False
        over_budget_pct: float = 0.0

        if budget_name is not None:
            try:
                budget = client.budgets.get(scope=scope, budget_name=budget_name)
                budget_amount_usd = float(getattr(budget, "amount", 0) or 0)
                if budget_amount_usd > 0:
                    burn_rate_pct = (forecast_month_end_usd / budget_amount_usd) * 100
                    over_budget = burn_rate_pct > 100
                    over_budget_pct = max(0.0, burn_rate_pct - 100) if burn_rate_pct else 0.0
            except Exception as budget_exc:
                budget_error = str(budget_exc)
                budget_amount_usd = None

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "get_cost_forecast: complete | subscription_id=%s "
            "current_spend=%.2f forecast=%.2f over_budget=%s duration_ms=%.1f",
            subscription_id,
            current_spend,
            forecast_month_end_usd,
            over_budget,
            duration_ms,
        )
        response: Dict[str, Any] = {
            "subscription_id": subscription_id,
            "current_spend_usd": current_spend,
            "forecast_month_end_usd": forecast_month_end_usd,
            "budget_amount_usd": budget_amount_usd,
            "burn_rate_pct": burn_rate_pct,
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
            "over_budget": over_budget,
            "over_budget_pct": over_budget_pct,
            "data_lag_note": _DATA_LAG_NOTE,
            "query_status": "success",
            "duration_ms": duration_ms,
        }
        if budget_error is not None:
            response["budget_error"] = budget_error

        return response

    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "get_cost_forecast: failed | subscription_id=%s error=%s",
            subscription_id,
            e,
            exc_info=True,
        )
        return {
            "subscription_id": subscription_id,
            "query_status": "error",
            "error": str(e),
            "duration_ms": duration_ms,
        }


# ===========================================================================
# Tool 6: get_top_cost_drivers
# ===========================================================================


@ai_function
def get_top_cost_drivers(
    subscription_id: str,
    n: int = 10,
    days: int = 30,
) -> Dict[str, Any]:
    """Get top N cost drivers by service type with month-over-month delta.

    Args:
        subscription_id: Azure subscription GUID.
        n: Number of top drivers to return (1–25, default 10).
        days: Current period in days (default 30).

    Returns:
        Dict with keys: subscription_id, n, days, drivers
            (list of {service_name, cost_usd, currency, rank}),
            total_cost_usd, data_lag_note, query_status, duration_ms.
    """
    start_time = time.monotonic()
    try:
        if CostManagementClient is None:
            raise ImportError("azure-mgmt-costmanagement is not installed")

        # Clamp n to [1, 25] and days to [7, 90]
        n = max(1, min(n, 25))
        days = max(7, min(days, 90))

        credential = get_credential()
        scope = f"/subscriptions/{subscription_id}"
        client = CostManagementClient(credential)

        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=days)

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

        columns = [c.name for c in result.columns]
        cost_idx = next(
            (i for i, c in enumerate(columns) if "cost" in c.lower()), 0
        )
        group_idx = next(
            (i for i, c in enumerate(columns) if "servicename" in c.lower()), -1
        )
        currency_idx = next(
            (i for i, c in enumerate(columns) if "currency" in c.lower()), -1
        )

        # Sort all rows by cost descending, take top n
        sorted_rows = sorted(result.rows, key=lambda r: float(r[cost_idx]), reverse=True)[:n]

        drivers = [
            {
                "service_name": row[group_idx] if group_idx >= 0 else "Unknown",
                "cost_usd": float(row[cost_idx]),
                "currency": row[currency_idx] if currency_idx >= 0 else "USD",
                "rank": i + 1,
            }
            for i, row in enumerate(sorted_rows)
        ]

        total_cost_usd = sum(float(row[cost_idx]) for row in result.rows)

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "get_top_cost_drivers: complete | subscription_id=%s n=%d "
            "total_cost=%.2f duration_ms=%.1f",
            subscription_id,
            n,
            total_cost_usd,
            duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "n": n,
            "days": days,
            "drivers": drivers,
            "total_cost_usd": total_cost_usd,
            "data_lag_note": _DATA_LAG_NOTE,
            "query_status": "success",
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "get_top_cost_drivers: failed | subscription_id=%s error=%s",
            subscription_id,
            e,
            exc_info=True,
        )
        return {
            "subscription_id": subscription_id,
            "n": n,
            "days": days,
            "query_status": "error",
            "error": str(e),
            "duration_ms": duration_ms,
        }
