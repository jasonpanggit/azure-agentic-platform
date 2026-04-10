"""Gateway-side tool executor for domain agent function tool calls.

When a Foundry domain-agent sub-run enters ``requires_action`` /
``submit_tool_outputs``, the gateway must execute the requested function
tools locally and return the results to Foundry so the run can continue.

This module mirrors the tool functions defined in ``agents/compute/tools.py``
and ``agents/eol/tools.py`` but runs inside the API gateway process
(no agent container required).

Tool functions follow project conventions:
- ``start_time = time.monotonic()`` at entry; ``duration_ms`` recorded in
  both ``try`` and ``except`` blocks.
- Tool functions **never raise** --- they return structured error dicts.
- Lazy SDK imports at module level with ``= None`` fallback.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy SDK imports — packages may not be installed in all environments
# ---------------------------------------------------------------------------

try:
    from azure.identity import DefaultAzureCredential
except ImportError:
    DefaultAzureCredential = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.resourcehealth import ResourceHealthMgmtClient
except ImportError:
    try:
        from azure.mgmt.resourcehealth import MicrosoftResourceHealth as ResourceHealthMgmtClient  # type: ignore[assignment,no-redef]
    except ImportError:
        ResourceHealthMgmtClient = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]


def _log_sdk_availability() -> None:
    """Log which Azure SDK packages are available at import time."""
    packages = {
        "azure-identity": "azure.identity",
        "azure-mgmt-monitor": "azure.mgmt.monitor",
        "azure-monitor-query": "azure.monitor.query",
        "azure-mgmt-resourcehealth": "azure.mgmt.resourcehealth",
        "azure-mgmt-resourcegraph": "azure.mgmt.resourcegraph",
    }
    for pkg, module in packages.items():
        try:
            __import__(module)
            logger.info("tool_executor: sdk_available | package=%s", pkg)
        except ImportError:
            logger.warning(
                "tool_executor: sdk_missing | package=%s -- tool will return error", pkg
            )


_log_sdk_availability()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_credential() -> Any:
    """Return a DefaultAzureCredential instance."""
    if DefaultAzureCredential is None:
        raise ImportError("azure-identity is not installed")
    return DefaultAzureCredential()


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID."""
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot extract subscription_id from resource_id: {resource_id}"
        )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _exec_query_activity_log(args: dict) -> dict:
    """Query Azure Monitor Activity Logs for given resource_ids and timespan_hours.

    Args (from args dict):
        resource_ids: List of Azure resource IDs.
        timespan_hours: Look-back window in hours (default 2).

    Returns:
        Dict with resource_ids, timespan_hours, entries, query_status.
    """
    start_time = time.monotonic()
    resource_ids: List[str] = args.get("resource_ids", [])
    timespan_hours: int = int(args.get("timespan_hours", 2))

    try:
        if MonitorManagementClient is None:
            raise ImportError("azure-mgmt-monitor is not installed")

        credential = _get_credential()
        start = datetime.now(timezone.utc) - timedelta(hours=timespan_hours)
        all_entries: List[Dict[str, Any]] = []

        for resource_id in resource_ids:
            sub_id = _extract_subscription_id(resource_id)
            client = MonitorManagementClient(credential, sub_id)
            filter_str = (
                f"eventTimestamp ge '{start.isoformat()}' "
                f"and resourceId eq '{resource_id}'"
            )
            events = client.activity_logs.list(filter=filter_str)
            for event in events:
                # SDK v5+ returns plain str for localizable fields; older SDKs return
                # LocalizableString objects with a .value attribute. Guard both.
                def _str_val(obj: Any) -> Optional[str]:
                    if obj is None:
                        return None
                    return obj.value if hasattr(obj, "value") else str(obj)

                all_entries.append(
                    {
                        "eventTimestamp": (
                            event.event_timestamp.isoformat()
                            if event.event_timestamp
                            else None
                        ),
                        "operationName": _str_val(event.operation_name),
                        "caller": event.caller,
                        "status": _str_val(event.status),
                        "resourceId": event.resource_id,
                        "level": _str_val(event.level),
                        "description": event.description,
                    }
                )

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "tool_executor: query_activity_log complete | resources=%d entries=%d duration_ms=%.0f",
            len(resource_ids),
            len(all_entries),
            duration_ms,
        )
        return {
            "resource_ids": resource_ids,
            "timespan_hours": timespan_hours,
            "entries": all_entries,
            "query_status": "success",
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_activity_log failed | resources=%s error=%s duration_ms=%.0f",
            resource_ids,
            e,
            duration_ms,
            exc_info=True,
        )
        return {
            "resource_ids": resource_ids,
            "timespan_hours": timespan_hours,
            "entries": [],
            "query_status": "error",
            "error": str(e),
        }


def _exec_query_log_analytics(args: dict) -> dict:
    """Run a KQL query against a Log Analytics workspace.

    Workspace ID is resolved from args or environment variables:
    ``LOG_ANALYTICS_WORKSPACE_RESOURCE_ID`` or ``LOGS_WORKSPACE_ID``.

    Args (from args dict):
        workspace_id: Log Analytics workspace resource ID (optional if env set).
        kql_query: KQL query string.
        timespan: ISO 8601 duration (default "PT2H").

    Returns:
        Dict with workspace_id, kql_query, timespan, rows, query_status.
    """
    start_time = time.monotonic()
    workspace_id: str = args.get("workspace_id", "") or os.environ.get(
        "LOG_ANALYTICS_WORKSPACE_RESOURCE_ID",
        os.environ.get("LOGS_WORKSPACE_ID", ""),
    )
    kql_query: str = args.get("kql_query", "")
    timespan: str = args.get("timespan", "PT2H")

    if not workspace_id:
        logger.warning(
            "tool_executor: query_log_analytics skipped | workspace_id is empty"
        )
        return {
            "workspace_id": workspace_id,
            "kql_query": kql_query,
            "timespan": timespan,
            "rows": [],
            "query_status": "skipped",
        }

    try:
        if LogsQueryClient is None:
            raise ImportError("azure-monitor-query is not installed")

        credential = _get_credential()
        client = LogsQueryClient(credential)
        response = client.query_workspace(
            workspace_id=workspace_id,
            query=kql_query,
            timespan=timespan,
        )

        if response.status == LogsQueryStatus.SUCCESS:
            rows: List[Dict[str, Any]] = []
            for table in response.tables:
                col_names = [col.name for col in table.columns]
                for row in table.rows:
                    rows.append(
                        dict(
                            zip(
                                col_names,
                                [str(v) if v is not None else None for v in row],
                            )
                        )
                    )
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "tool_executor: query_log_analytics complete | workspace=%s rows=%d duration_ms=%.0f",
                workspace_id,
                len(rows),
                duration_ms,
            )
            return {
                "workspace_id": workspace_id,
                "kql_query": kql_query,
                "timespan": timespan,
                "rows": rows,
                "query_status": "success",
            }
        else:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.warning(
                "tool_executor: query_log_analytics partial | workspace=%s duration_ms=%.0f error=%s",
                workspace_id,
                duration_ms,
                response.partial_error,
            )
            return {
                "workspace_id": workspace_id,
                "kql_query": kql_query,
                "timespan": timespan,
                "rows": [],
                "query_status": "partial",
                "partial_error": str(response.partial_error),
            }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_log_analytics failed | workspace=%s error=%s duration_ms=%.0f",
            workspace_id,
            e,
            duration_ms,
            exc_info=True,
        )
        return {
            "workspace_id": workspace_id,
            "kql_query": kql_query,
            "timespan": timespan,
            "rows": [],
            "query_status": "error",
            "error": str(e),
        }


def _exec_query_resource_health(args: dict) -> dict:
    """Get availability state for a resource_id using ResourceHealthMgmtClient.

    Uses ``hasattr(raw_state, "value")`` guard because SDK v1.0.0b6+ returns
    plain str instead of enum for ``availability_state``.

    Args (from args dict):
        resource_id: Azure resource ID.

    Returns:
        Dict with resource_id, availability_state, summary, reason_type,
        occurred_time, query_status.
    """
    start_time = time.monotonic()
    resource_id: str = args.get("resource_id", "")

    try:
        if ResourceHealthMgmtClient is None:
            raise ImportError("azure-mgmt-resourcehealth is not installed")

        credential = _get_credential()
        sub_id = _extract_subscription_id(resource_id)
        client = ResourceHealthMgmtClient(credential, sub_id)
        status = client.availability_statuses.get_by_resource(
            resource_uri=resource_id,
            expand="recommendedActions",
        )

        raw_state = status.properties.availability_state
        if hasattr(raw_state, "value"):
            availability_state = raw_state.value
        elif raw_state is not None:
            availability_state = str(raw_state)
        else:
            availability_state = "Unknown"

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "tool_executor: query_resource_health complete | resource=%s state=%s duration_ms=%.0f",
            resource_id,
            availability_state,
            duration_ms,
        )
        # occurred_time was added in a later SDK version — guard with getattr
        occurred_time_raw = getattr(status.properties, "occurred_time", None)
        return {
            "resource_id": resource_id,
            "availability_state": availability_state,
            "summary": status.properties.summary,
            "reason_type": status.properties.reason_type,
            "occurred_time": (
                occurred_time_raw.isoformat()
                if occurred_time_raw
                else None
            ),
            "query_status": "success",
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_resource_health failed | resource=%s error=%s duration_ms=%.0f",
            resource_id,
            e,
            duration_ms,
            exc_info=True,
        )
        return {
            "resource_id": resource_id,
            "availability_state": "Unknown",
            "summary": None,
            "reason_type": None,
            "occurred_time": None,
            "query_status": "error",
            "error": str(e),
        }


def _exec_query_monitor_metrics(args: dict) -> dict:
    """Fetch Azure Monitor metrics for resource_id and metric_names list.

    Args (from args dict):
        resource_id: Azure resource ID.
        metric_names: List of metric names.
        timespan: ISO 8601 duration (default "PT2H").
        interval: Aggregation interval (default "PT5M").

    Returns:
        Dict with resource_id, metric_names, timespan, interval, metrics,
        query_status.
    """
    start_time = time.monotonic()
    resource_id: str = args.get("resource_id", "")
    metric_names: List[str] = args.get("metric_names", [])
    timespan: str = args.get("timespan", "PT2H")
    interval: str = args.get("interval", "PT5M")

    try:
        if MonitorManagementClient is None:
            raise ImportError("azure-mgmt-monitor is not installed")

        credential = _get_credential()
        sub_id = _extract_subscription_id(resource_id)
        client = MonitorManagementClient(credential, sub_id)
        response = client.metrics.list(
            resource_uri=resource_id,
            metricnames=",".join(metric_names),
            timespan=timespan,
            interval=interval,
            aggregation="Average,Maximum,Minimum",
        )

        metrics_out: List[Dict[str, Any]] = []
        for metric in response.value:
            timeseries: List[Dict[str, Any]] = []
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.time_stamp:
                        timeseries.append(
                            {
                                "timestamp": dp.time_stamp.isoformat(),
                                "average": dp.average,
                                "maximum": dp.maximum,
                                "minimum": dp.minimum,
                            }
                        )
            metrics_out.append(
                {
                    "name": metric.name.value if hasattr(metric.name, "value") else str(metric.name) if metric.name else None,
                    "unit": metric.unit.value if hasattr(metric.unit, "value") else str(metric.unit) if metric.unit else None,
                    "timeseries": timeseries,
                }
            )

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "tool_executor: query_monitor_metrics complete | resource=%s metrics=%d duration_ms=%.0f",
            resource_id,
            len(metrics_out),
            duration_ms,
        )
        return {
            "resource_id": resource_id,
            "metric_names": metric_names,
            "timespan": timespan,
            "interval": interval,
            "metrics": metrics_out,
            "query_status": "success",
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_monitor_metrics failed | resource=%s error=%s duration_ms=%.0f",
            resource_id,
            e,
            duration_ms,
            exc_info=True,
        )
        return {
            "resource_id": resource_id,
            "metric_names": metric_names,
            "timespan": timespan,
            "interval": interval,
            "metrics": [],
            "query_status": "error",
            "error": str(e),
        }


def _exec_query_os_version(args: dict) -> dict:
    """Run ARG query to get OS info for resource_id.

    Args (from args dict):
        resource_id: Single Azure resource ID (convenience -- wrapped to list).
        resource_ids: List of resource IDs (preferred).
        subscription_ids: List of subscription IDs.

    Returns:
        Dict with resource_ids, machines, total_count, query_status.
    """
    start_time = time.monotonic()

    resource_ids: List[str] = args.get("resource_ids", [])
    if not resource_ids and args.get("resource_id"):
        resource_ids = [args["resource_id"]]

    subscription_ids: List[str] = args.get("subscription_ids", [])
    if not subscription_ids:
        for rid in resource_ids:
            try:
                sub = _extract_subscription_id(rid)
                if sub not in subscription_ids:
                    subscription_ids.append(sub)
            except ValueError:
                pass

    try:
        if ResourceGraphClient is None:
            raise ImportError("azure-mgmt-resourcegraph is not installed")

        credential = _get_credential()
        client = ResourceGraphClient(credential)

        ids_str = ", ".join(f'"{rid}"' for rid in resource_ids)

        vm_kql = (
            'resources | where type == "microsoft.compute/virtualmachines"'
            " | extend osName = tostring(properties.extended.instanceView.osName),"
            " osVersion = tostring(properties.extended.instanceView.osVersion),"
            " osType = tostring(properties.storageProfile.osDisk.osType),"
            " publisher = tostring(properties.storageProfile.imageReference.publisher),"
            " offer = tostring(properties.storageProfile.imageReference.offer),"
            " imageReferenceSku = tostring(properties.storageProfile.imageReference.sku)"
            f" | where id in~ ({ids_str})"
            " | project id, name, resourceGroup, subscriptionId, osName, osVersion,"
            " osType, publisher, offer, imageReferenceSku"
            ' | extend resourceType = "vm"'
        )

        arc_kql = (
            'resources | where type == "microsoft.hybridcompute/machines"'
            " | extend osName = tostring(properties.osName),"
            " osVersion = tostring(properties.osVersion),"
            " osType = tostring(properties.osType),"
            " osSku = tostring(properties.osSku),"
            " status = tostring(properties.status)"
            f" | where id in~ ({ids_str})"
            " | project id, name, resourceGroup, subscriptionId, osName, osVersion,"
            " osType, osSku, status"
            ' | extend resourceType = "arc"'
        )

        all_machines: List[Dict[str, Any]] = []

        for kql in [vm_kql, arc_kql]:
            skip_token: Optional[str] = None
            while True:
                options = (
                    QueryRequestOptions(skip_token=skip_token) if skip_token else None
                )
                request = QueryRequest(
                    subscriptions=subscription_ids,
                    query=kql,
                    options=options,
                )
                response = client.resources(request)
                all_machines.extend(response.data)
                skip_token = response.skip_token
                if not skip_token:
                    break

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "tool_executor: query_os_version complete | machines=%d duration_ms=%.0f",
            len(all_machines),
            duration_ms,
        )
        return {
            "resource_ids": resource_ids,
            "machines": all_machines,
            "total_count": len(all_machines),
            "query_status": "success",
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_os_version failed | resources=%s error=%s duration_ms=%.0f",
            resource_ids,
            e,
            duration_ms,
            exc_info=True,
        )
        return {
            "resource_ids": resource_ids,
            "machines": [],
            "total_count": 0,
            "query_status": "error",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# EOL tool helpers — product slug normalization and HTTP fetch
# ---------------------------------------------------------------------------

# Windows Server year patterns for OS name parsing
_WINDOWS_SERVER_YEARS = ("2025", "2022", "2019", "2016", "2012 r2", "2012", "2008 r2", "2008")
_UBUNTU_RE = re.compile(r"ubuntu\s+(\d+\.\d+)", re.IGNORECASE)


def _normalize_eol_product(product: str, version: str = "") -> Tuple[str, str]:
    """Normalize a product name into (endoflife.date slug, cycle).

    Handles the common case where the LLM passes full OS display names
    like "Windows Server 2025 Datacenter Azure Edition" and needs them
    mapped to endoflife.date's (product=windows-server, cycle=2025).

    Returns:
        (product_slug, version_cycle) for endoflife.date API.
    """
    lower = product.lower().strip()

    # Windows Server: extract year as cycle, slug is always "windows-server"
    for year in _WINDOWS_SERVER_YEARS:
        if f"windows server {year}" in lower or lower == f"windows-server-{year.replace(' ', '-')}":
            return ("windows-server", year.replace(" ", "-"))

    # Ubuntu: extract version number as cycle
    m = _UBUNTU_RE.search(product)
    if m:
        return ("ubuntu", m.group(1))

    # SQL Server
    for sql_year in ("2022", "2019", "2016", "2014", "2012"):
        if f"sql server {sql_year}" in lower or f"sql-server-{sql_year}" in lower:
            return ("mssqlserver", sql_year)

    # Already a valid slug (e.g., "python", "nodejs", "postgresql")
    # Use version as-is for cycle
    slug = lower.replace(" ", "-")
    return (slug, version)


def _fetch_endoflife_date(product: str, cycle: str, timeout: float = 10.0) -> Optional[dict]:
    """Fetch from endoflife.date API with retry on 429/5xx."""
    if _httpx is None:
        return None

    url = f"https://endoflife.date/api/{product}/{cycle}.json"
    for attempt in range(3):
        try:
            response = _httpx.get(url, timeout=timeout)
            if response.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except (_httpx.HTTPStatusError, _httpx.RequestError):
            if attempt == 2:
                return None
            time.sleep(1)
    return None


def _parse_eol_field(eol_value: Any) -> Tuple[Optional[str], bool]:
    """Parse the polymorphic ``eol`` field from endoflife.date API.

    Returns (eol_date_iso, is_eol):
    - date string "2028-10-31" -> ("2028-10-31", False or True based on today)
    - True -> (None, True)
    - False -> (None, False)
    """
    if isinstance(eol_value, bool):
        return (None, eol_value)
    if isinstance(eol_value, str):
        try:
            eol_date = date.fromisoformat(eol_value)
            return (eol_date.isoformat(), eol_date < date.today())
        except ValueError:
            return (None, False)
    return (None, False)


def _classify_eol_status(
    eol_date_str: Optional[str], is_eol: bool
) -> Dict[str, Any]:
    """Classify EOL status and risk level."""
    today = date.today()

    if is_eol or (eol_date_str and date.fromisoformat(eol_date_str) < today):
        return {"status": "already_eol", "risk_level": "high", "days_remaining": 0}

    if eol_date_str is None:
        return {"status": "not_eol", "risk_level": "none", "days_remaining": None}

    days_remaining = (date.fromisoformat(eol_date_str) - today).days

    if days_remaining <= 30:
        return {"status": "within_30_days", "risk_level": "high", "days_remaining": days_remaining}
    elif days_remaining <= 60:
        return {"status": "within_60_days", "risk_level": "medium", "days_remaining": days_remaining}
    elif days_remaining <= 90:
        return {"status": "within_90_days", "risk_level": "medium", "days_remaining": days_remaining}
    else:
        return {"status": "not_eol", "risk_level": "none", "days_remaining": days_remaining}


# ---------------------------------------------------------------------------
# EOL tool implementations
# ---------------------------------------------------------------------------


def _exec_query_endoflife_date(args: dict) -> dict:
    """Query the endoflife.date API for EOL lifecycle status of a product version.

    Normalizes product names (e.g. "Windows Server 2025 Datacenter Azure Edition"
    -> product=windows-server, cycle=2025) before calling the API.

    Args (from args dict):
        product: Product slug or display name.
        version: Version cycle string.

    Returns:
        Dict with product, version, eol_date, is_eol, lts, latest_version,
        source, classification, query_status.
    """
    start_time = time.monotonic()
    raw_product: str = args.get("product", "")
    raw_version: str = args.get("version", "")

    # Normalize to endoflife.date slug and cycle
    product, cycle = _normalize_eol_product(raw_product, raw_version)

    try:
        if _httpx is None:
            raise ImportError("httpx is not installed")

        data = _fetch_endoflife_date(product, cycle)

        if data is None:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "tool_executor: query_endoflife_date not_found | product=%s cycle=%s duration_ms=%.0f",
                product, cycle, duration_ms,
            )
            return {
                "product": raw_product,
                "version": raw_version,
                "normalized_product": product,
                "normalized_cycle": cycle,
                "eol_date": None,
                "is_eol": False,
                "lts": None,
                "latest_version": "",
                "source": "endoflife.date",
                "classification": _classify_eol_status(None, False),
                "query_status": "not_found",
            }

        eol_date_str, is_eol = _parse_eol_field(data.get("eol", False))
        latest_version = str(data.get("latest", ""))
        lts_raw = data.get("lts", False)
        lts_val = isinstance(lts_raw, bool) and lts_raw
        classification = _classify_eol_status(eol_date_str, is_eol)

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "tool_executor: query_endoflife_date success | product=%s cycle=%s eol=%s duration_ms=%.0f",
            product, cycle, eol_date_str, duration_ms,
        )
        return {
            "product": raw_product,
            "version": raw_version,
            "normalized_product": product,
            "normalized_cycle": cycle,
            "eol_date": eol_date_str,
            "is_eol": is_eol,
            "lts": lts_val,
            "latest_version": latest_version,
            "source": "endoflife.date",
            "classification": classification,
            "query_status": "success",
            "cache_hit": False,
        }

    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_endoflife_date failed | product=%s error=%s duration_ms=%.0f",
            raw_product, e, duration_ms, exc_info=True,
        )
        return {
            "product": raw_product,
            "version": raw_version,
            "eol_date": None,
            "is_eol": False,
            "lts": None,
            "latest_version": "",
            "source": "endoflife.date",
            "classification": _classify_eol_status(None, False),
            "query_status": "error",
            "error": str(e),
        }


def _exec_query_ms_lifecycle(args: dict) -> dict:
    """Query the Microsoft Product Lifecycle API for EOL lifecycle status.

    Falls through to endoflife.date if MS API returns no result (D-02).

    Args (from args dict):
        product: Microsoft product name.
        version: Optional version string.

    Returns:
        Dict with product, version, eol_date, support_end, is_eol, source,
        lifecycle_link, classification, query_status.
    """
    start_time = time.monotonic()
    product: str = args.get("product", "")
    version: str = args.get("version", "")

    try:
        if _httpx is None:
            raise ImportError("httpx is not installed")

        # Try MS Lifecycle API first
        url = "https://learn.microsoft.com/api/lifecycle/products"
        params = {
            "$filter": f"contains(productName,'{product}')",
            "$expand": "releases",
        }

        ms_data = None
        for attempt in range(3):
            try:
                response = _httpx.get(url, params=params, timeout=15.0)
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                ms_data = response.json()
                break
            except (_httpx.HTTPStatusError, _httpx.RequestError):
                if attempt == 2:
                    ms_data = None
                time.sleep(1)

        if ms_data is not None and ms_data.get("products"):
            products = ms_data["products"]
            best_match = None
            search_name = product.lower()
            for p in products:
                p_name = p.get("productName", "").lower()
                if version and version in p_name:
                    best_match = p
                    break
                if p_name == search_name:
                    best_match = p
                    break
            if best_match is None and products:
                best_match = products[0]

            if best_match is not None:
                def _parse_ms_date(val: Any) -> Optional[str]:
                    if not val:
                        return None
                    try:
                        return datetime.fromisoformat(
                            str(val).replace("Z", "+00:00")
                        ).date().isoformat()
                    except ValueError:
                        return None

                eol_date_str = _parse_ms_date(best_match.get("eolDate"))
                support_end_str = _parse_ms_date(best_match.get("eosDate"))
                lifecycle_link = best_match.get("link", "")

                is_eol = bool(eol_date_str and date.fromisoformat(eol_date_str) < date.today())
                classification = _classify_eol_status(eol_date_str, is_eol)

                duration_ms = (time.monotonic() - start_time) * 1000
                logger.info(
                    "tool_executor: query_ms_lifecycle success | product=%s eol=%s duration_ms=%.0f",
                    product, eol_date_str, duration_ms,
                )
                return {
                    "product": product,
                    "version": version,
                    "eol_date": eol_date_str,
                    "support_end": support_end_str,
                    "is_eol": is_eol,
                    "source": "ms-lifecycle",
                    "lifecycle_link": lifecycle_link,
                    "classification": classification,
                    "query_status": "success",
                    "cache_hit": False,
                }

        # D-02 fallback: try endoflife.date
        logger.info(
            "tool_executor: query_ms_lifecycle falling through to endoflife.date | product=%s",
            product,
        )
        fallback_result = _exec_query_endoflife_date({"product": product, "version": version})
        fallback_result["source"] = fallback_result.get("source", "endoflife.date")
        return fallback_result

    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_ms_lifecycle failed | product=%s error=%s duration_ms=%.0f",
            product, e, duration_ms, exc_info=True,
        )
        return {
            "product": product,
            "version": version,
            "eol_date": None,
            "support_end": None,
            "is_eol": False,
            "source": "ms-lifecycle",
            "lifecycle_link": "",
            "classification": _classify_eol_status(None, False),
            "query_status": "error",
            "error": str(e),
        }


def _exec_query_os_inventory(args: dict) -> dict:
    """Query ARG for OS version inventory across Azure VMs and Arc-enabled servers.

    Args (from args dict):
        subscription_ids: List of Azure subscription IDs.
        resource_ids: Optional list of resource IDs to filter.

    Returns:
        Dict with subscription_ids, machines, total_count, query_status.
    """
    start_time = time.monotonic()
    subscription_ids: List[str] = args.get("subscription_ids", [])
    resource_ids: Optional[List[str]] = args.get("resource_ids")

    try:
        if ResourceGraphClient is None:
            raise ImportError("azure-mgmt-resourcegraph is not installed")

        credential = _get_credential()
        client = ResourceGraphClient(credential)

        vm_kql = (
            "resources\n"
            '| where type == "microsoft.compute/virtualmachines"\n'
            "| extend osName = tostring(properties.extended.instanceView.osName),\n"
            "         osVersion = tostring(properties.extended.instanceView.osVersion),\n"
            "         osType = tostring(properties.storageProfile.osDisk.osType),\n"
            "         publisher = tostring(properties.storageProfile.imageReference.publisher),\n"
            "         offer = tostring(properties.storageProfile.imageReference.offer),\n"
            "         sku = tostring(properties.storageProfile.imageReference.sku)\n"
            "| project id, name, resourceGroup, subscriptionId, osName, osVersion,\n"
            "          osType, publisher, offer, sku"
        )

        arc_kql = (
            "resources\n"
            '| where type == "microsoft.hybridcompute/machines"\n'
            "| extend osName = tostring(properties.osName),\n"
            "         osVersion = tostring(properties.osVersion),\n"
            "         osType = tostring(properties.osType),\n"
            "         osSku = tostring(properties.osSku),\n"
            "         status = tostring(properties.status)\n"
            "| project id, name, resourceGroup, subscriptionId, osName, osVersion,\n"
            "          osType, osSku, status"
        )

        all_machines: List[Dict[str, Any]] = []

        for kql in [vm_kql, arc_kql]:
            if resource_ids:
                ids_str = ", ".join(f'"{rid}"' for rid in resource_ids)
                kql_lines = kql.rstrip("\n").split("\n")
                project_line = kql_lines.pop()
                kql = "\n".join(kql_lines) + f"\n| where id in~ ({ids_str})\n" + project_line

            skip_token: Optional[str] = None
            while True:
                options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
                request = QueryRequest(subscriptions=subscription_ids, query=kql, options=options)
                response = client.resources(request)
                all_machines.extend(response.data)
                skip_token = response.skip_token
                if not skip_token:
                    break

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "tool_executor: query_os_inventory complete | machines=%d duration_ms=%.0f",
            len(all_machines), duration_ms,
        )
        return {
            "subscription_ids": subscription_ids,
            "machines": all_machines,
            "total_count": len(all_machines),
            "query_status": "success",
        }
    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "tool_executor: query_os_inventory failed | error=%s duration_ms=%.0f",
            e, duration_ms, exc_info=True,
        )
        return {
            "subscription_ids": subscription_ids,
            "machines": [],
            "total_count": 0,
            "query_status": "error",
            "error": str(e),
        }


def _exec_search_runbooks(args: dict) -> dict:
    """Search operational runbooks — thin proxy that returns empty results.

    The gateway does not have access to the pgvector runbook store directly.
    Returning an empty result is safe — the agent will still produce a
    triage response, just without runbook citations.

    Args (from args dict):
        query: Search query string.
        domain: Domain filter (default "eol").
        limit: Max results (default 3).

    Returns:
        Dict with query, domain, runbooks, runbook_count, query_status.
    """
    query: str = args.get("query", "")
    domain: str = args.get("domain", "eol")
    limit: int = int(args.get("limit", 3))
    return {
        "query": query,
        "domain": domain,
        "runbooks": [],
        "runbook_count": 0,
        "query_status": "empty",
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TOOL_MAP = {
    "query_activity_log": _exec_query_activity_log,
    "query_log_analytics": _exec_query_log_analytics,
    "query_resource_health": _exec_query_resource_health,
    "query_monitor_metrics": _exec_query_monitor_metrics,
    "query_os_version": _exec_query_os_version,
    "query_endoflife_date": _exec_query_endoflife_date,
    "query_ms_lifecycle": _exec_query_ms_lifecycle,
    "query_os_inventory": _exec_query_os_inventory,
    "search_runbooks": _exec_search_runbooks,
}


def execute_tool_call(tool_name: str, args_json: str) -> str:
    """Dispatch a tool call to the appropriate executor function.

    Args:
        tool_name: Name of the tool to execute (must be in TOOL_MAP).
        args_json: JSON string (or already-parsed dict) of tool arguments.

    Returns:
        JSON string of the tool result (always valid JSON, never raises).
    """
    fn = TOOL_MAP.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}", "tool_name": tool_name})
    try:
        args = json.loads(args_json) if isinstance(args_json, str) else args_json
    except Exception:
        args = {}
    result = fn(args)
    return json.dumps(result, default=str)
