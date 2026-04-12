"""VM detail and metrics endpoints.

GET  /api/v1/vms/{resource_id_base64}                        — full VM profile
GET  /api/v1/vms/{resource_id_base64}/metrics                — time-series metric data
GET  /api/v1/vms/{resource_id_base64}/diagnostic-settings    — check if diag settings exist
POST /api/v1/vms/{resource_id_base64}/diagnostic-settings    — enable diag settings → LA workspace

resource_id_base64: ARM resource ID base64url-encoded (no padding).
Decode with: base64.urlsafe_b64decode(pad(resource_id_base64)).decode()
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.os_normalizer import normalize_os

try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:  # pragma: no cover
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.loganalytics import LogAnalyticsManagementClient
except ImportError:  # pragma: no cover
    LogAnalyticsManagementClient = None  # type: ignore[assignment,misc]

# ARM resource ID of the Log Analytics workspace to send diagnostics to.
# Set LOG_ANALYTICS_WORKSPACE_RESOURCE_ID on the API gateway container app.
# Falls back to constructing it from the customer ID if only that is available.
_LA_WORKSPACE_RESOURCE_ID = os.environ.get("LOG_ANALYTICS_WORKSPACE_RESOURCE_ID", "")

# Module-level cache: workspace ARM resource ID -> customer GUID.
_workspace_guid_cache: Dict[str, str] = {}

# Module-level cache: Arc VM resource ID -> workspace customer GUID (Perf data).
# Populated lazily by _discover_arc_vm_workspace(); valid for process lifetime.
_arc_workspace_cache: Dict[str, str] = {}

# DCR and association names we manage (stable names so we can detect / overwrite)
_DCR_NAME = "aap-dcr"
_DCR_ASSOC_NAME = "aap-dcr-assoc"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vms", tags=["vm-detail"])

DEFAULT_METRICS = [
    "Percentage CPU",
    "Available Memory Bytes",
    "Disk Read Bytes",
    "Disk Write Bytes",
    "Disk Read Operations/Sec",
    "Disk Write Operations/Sec",
    "Network In Total",
    "Network Out Total",
]


def _decode_resource_id(encoded: str) -> str:
    """Decode a base64url-encoded ARM resource ID.

    Adds padding if necessary (base64url omits = padding).
    Raises ValueError if decoding fails.
    """
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    try:
        return base64.urlsafe_b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Invalid base64url resource ID: {exc}") from exc


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription_id from ARM resource ID."""
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return resource_id.split("/")[idx + 1]
    except (ValueError, IndexError):
        raise ValueError(f"Cannot extract subscription_id from: {resource_id}")


def _get_vm_details_from_arg(
    credential: Any,
    subscription_ids: List[str],
    resource_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch detailed VM info from ARG for a single resource ID.

    Handles both Azure VMs (microsoft.compute/virtualmachines) and
    Arc-enabled servers (microsoft.hybridcompute/machines).
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest

    name = resource_id.rstrip("/").split("/")[-1]
    safe_name = name.replace("'", "''")
    safe_id = resource_id.replace("'", "''")

    kql = f"""
Resources
| where type in~ ('microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
| where name =~ '{safe_name}'
| where id =~ '{safe_id}'
| extend powerState = iff(
    type =~ 'microsoft.compute/virtualmachines',
    tostring(properties.extended.instanceView.powerState.displayStatus),
    tostring(properties.status.powerState)
  )
| extend osType = iff(
    type =~ 'microsoft.compute/virtualmachines',
    tostring(properties.storageProfile.osDisk.osType),
    tostring(properties.osType)
  )
| extend osName = iff(
    type =~ 'microsoft.hybridcompute/machines',
    tostring(properties.osSku),
    iff(
        isnotempty(tostring(properties.osSku)),
        tostring(properties.osSku),
        iff(
            isnotempty(tostring(properties.extended.instanceView.osName)),
            tostring(properties.extended.instanceView.osName),
            iff(
                isnotempty(tostring(properties.storageProfile.imageReference.offer)),
                strcat(
                    tostring(properties.storageProfile.imageReference.offer),
                    ' ',
                    tostring(properties.storageProfile.imageReference.sku)
                ),
                tostring(properties.osType)
            )
        )
    )
  )
| extend vmSize = iff(
    type =~ 'microsoft.compute/virtualmachines',
    tostring(properties.hardwareProfile.vmSize),
    ''
  )
| extend vmType = iff(type =~ 'microsoft.compute/virtualmachines', 'Azure VM', 'Arc VM')
| extend availabilityZones = properties.zones
| project id, name, resourceGroup, subscriptionId, location,
    vmSize, osType, osName, powerState, tags,
    availabilityZones, vmType
| limit 1
"""

    client = ResourceGraphClient(credential)
    req = QueryRequest(subscriptions=subscription_ids, query=kql.strip())
    resp = client.resources(req)
    if resp.data:
        return resp.data[0]
    return None


def _get_resource_health(credential: Any, resource_id: str) -> Dict[str, Any]:
    """Fetch resource health state and summary for a VM."""
    try:
        sub_id = _extract_subscription_id(resource_id)
        # Class renamed MicrosoftResourceHealth → ResourceHealthMgmtClient in v1.0.0b6
        try:
            from azure.mgmt.resourcehealth import ResourceHealthMgmtClient as _RHClient
        except ImportError:
            from azure.mgmt.resourcehealth import MicrosoftResourceHealth as _RHClient  # type: ignore[no-redef]
        client = _RHClient(credential, sub_id)
        status = client.availability_statuses.get_by_resource(
            resource_uri=resource_id, expand="recommendedActions"
        )
        props = status.properties
        raw_state = props.availability_state if props and props.availability_state else None
        # SDK returns a plain str in v1.0.0b6+; older versions returned an enum
        if raw_state is None:
            health_state = "Unknown"
        elif hasattr(raw_state, "value"):
            health_state = raw_state.value
        else:
            health_state = str(raw_state)
        return {
            "health_state": health_state,
            "summary": props.summary if props else None,
            "reason_type": props.reason_type if props else None,
        }
    except Exception as exc:
        logger.warning("vm_detail: resource_health failed | error=%s", exc)
        return {"health_state": "Unknown", "summary": None, "reason_type": None}


def _get_active_incidents(cosmos_client: Any, resource_id: str) -> List[Dict[str, Any]]:
    """Fetch active incidents for a VM from Cosmos."""
    import os
    try:
        db_name = os.environ.get("COSMOS_DATABASE", "aap")
        container = cosmos_client.get_database_client(db_name).get_container_client("incidents")
        query = """
            SELECT c.incident_id, c.severity, c.title, c.created_at, c.status, c.investigation_status
            FROM c
            WHERE c.resource_id = @resource_id
            AND c.status IN ('open', 'dispatched', 'investigating')
            ORDER BY c.created_at DESC
            OFFSET 0 LIMIT 10
        """
        items = list(container.query_items(
            query=query,
            parameters=[{"name": "@resource_id", "value": resource_id}],
            enable_cross_partition_query=True,
        ))
        return items
    except Exception as exc:
        logger.warning("vm_detail: active_incidents failed | error=%s", exc)
        return []


def _normalize_power_state(raw: str) -> str:
    raw_lower = raw.lower()
    if "running" in raw_lower:
        return "running"
    if "deallocated" in raw_lower:
        return "deallocated"
    if "stopped" in raw_lower:
        return "stopped"
    return "unknown"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{resource_id_base64}")
async def get_vm_detail(
    resource_id_base64: str,
    credential=Depends(get_credential),
    cosmos_client=Depends(get_optional_cosmos_client),
    _user=Depends(verify_token),
) -> Dict[str, Any]:
    """Return full profile for a single VM."""
    start = time.monotonic()

    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info("vm_detail: request | resource=%s", resource_id[-60:])

    # Extract subscription for ARG scope
    try:
        sub_id = _extract_subscription_id(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    import asyncio

    # Parallel: ARG details + resource health
    loop = asyncio.get_event_loop()

    arg_task = loop.run_in_executor(None, _get_vm_details_from_arg, credential, [sub_id], resource_id)
    health_task = loop.run_in_executor(None, _get_resource_health, credential, resource_id)

    arg_row, health = await asyncio.gather(arg_task, health_task)

    if arg_row is None:
        raise HTTPException(status_code=404, detail=f"VM not found: {resource_id}")

    # Active incidents (needs Cosmos, optional)
    active_incidents: List[Dict[str, Any]] = []
    if cosmos_client:
        active_incidents = await loop.run_in_executor(
            None, _get_active_incidents, cosmos_client, resource_id
        )

    duration_ms = (time.monotonic() - start) * 1000
    logger.info("vm_detail: complete | resource=%s duration_ms=%.0f", resource_id[-60:], duration_ms)

    os_raw = arg_row.get("osName", "")
    os_type = arg_row.get("osType", "")
    os_display = normalize_os(os_raw, os_type)

    return {
        "id": resource_id,
        "name": arg_row.get("name", ""),
        "resource_group": arg_row.get("resourceGroup", ""),
        "subscription_id": arg_row.get("subscriptionId", ""),
        "location": arg_row.get("location", ""),
        "size": arg_row.get("vmSize", ""),
        "os_type": os_type,
        "os_name": os_display,
        "power_state": _normalize_power_state(arg_row.get("powerState", "")),
        "health_state": health["health_state"],
        "health_summary": health.get("summary"),
        "vm_type": arg_row.get("vmType", "Azure VM"),
        "ama_status": "unknown",
        "tags": arg_row.get("tags") or {},
        "active_incidents": active_incidents,
    }


def _fetch_single_metric(
    client: Any,
    resource_id: str,
    metric_name: str,
    timespan: str,
    interval: str,
) -> Optional[Dict[str, Any]]:
    """Fetch a single metric from Azure Monitor.

    Returns a parsed metric dict ``{name, unit, timeseries}`` or ``None`` when
    the metric is unsupported for this VM SKU or returns no data.  Exceptions
    are caught per-metric so one unsupported metric cannot poison the whole
    batch.
    """
    try:
        response = client.metrics.list(
            resource_uri=resource_id,
            metricnames=metric_name,
            timespan=timespan,
            interval=interval,
            aggregation="Average,Maximum,Minimum",
        )
        for metric in response.value:
            timeseries = []
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.time_stamp:
                        timeseries.append({
                            "timestamp": dp.time_stamp.isoformat(),
                            "average": dp.average,
                            "maximum": dp.maximum,
                            "minimum": dp.minimum,
                        })
            name_val = (
                metric.name.value if hasattr(metric.name, "value")
                else str(metric.name) if metric.name else None
            )
            unit_val = (
                metric.unit.value if hasattr(metric.unit, "value")
                else str(metric.unit) if metric.unit else None
            )
            return {"name": name_val, "unit": unit_val, "timeseries": timeseries}
        # response.value was empty — metric unsupported for this SKU
        return None
    except Exception as exc:
        logger.warning(
            "vm_metrics: skipping metric=%r | error=%s", metric_name, exc
        )
        return None


# ---------------------------------------------------------------------------
# Arc VM metrics via Log Analytics (Perf table)
# ---------------------------------------------------------------------------

# Map Perf table counter names to the same metric names used in METRIC_CATALOG
# so the frontend can render them identically.
_PERF_COUNTER_MAP: Dict[str, Dict[str, str]] = {
    "% Processor Time": {"name": "Percentage CPU", "unit": "Percent"},
    "Available MBytes": {"name": "Available Memory Bytes", "unit": "Bytes"},
    "Available Bytes": {"name": "Available Memory Bytes", "unit": "Bytes"},
    "Disk Read Bytes/sec": {"name": "Disk Read Bytes", "unit": "BytesPerSecond"},
    "Disk Write Bytes/sec": {"name": "Disk Write Bytes", "unit": "BytesPerSecond"},
    "Bytes Received/sec": {"name": "Network In Total", "unit": "BytesPerSecond"},
    "Bytes Sent/sec": {"name": "Network Out Total", "unit": "BytesPerSecond"},
    "Total Bytes Received": {"name": "Network In Total", "unit": "Bytes"},
    "Total Bytes Transmitted": {"name": "Network Out Total", "unit": "Bytes"},
}

# Default Perf counters to query when no specific metrics are requested.
_ARC_DEFAULT_COUNTERS = [
    "% Processor Time",
    "Available MBytes",
    "Available Bytes",
    "Disk Read Bytes/sec",
    "Disk Write Bytes/sec",
    "Bytes Received/sec",
    "Bytes Sent/sec",
]


def _discover_arc_vm_workspace(credential: Any, resource_id: str) -> str:
    """Discover the Log Analytics workspace GUID for an Arc VM's Perf data.

    Arc VMs enrolled in Azure Monitor Agent send Perf counters to a Log
    Analytics workspace specified in their Data Collection Rule (DCR).  This
    function discovers that workspace automatically so no manual env-var
    configuration is required.

    Discovery strategy (in order):
    1. Check module-level cache keyed by resource_id.
    2. List DCR associations on the Arc VM via ARM REST.
    3. Fetch each DCR (skip configurationAccessEndpoint which has no DCR ID).
    4. Extract ``destinations.logAnalytics[*].workspaceId`` — this is already
       the customer GUID that LogsQueryClient expects, so no further ARM call.
    5. Fall back to _resolve_workspace_guid() using LOG_ANALYTICS_WORKSPACE_RESOURCE_ID
       env var if no DCR-based workspace is found.

    Returns the workspace GUID string; returns empty string on failure (never raises).
    """
    cached = _arc_workspace_cache.get(resource_id)
    if cached is not None:
        return cached

    try:
        token = credential.get_token("https://management.azure.com/.default").token
        headers = {"Authorization": f"Bearer {token}"}

        # Step 1: list DCR associations
        assoc_url = (
            f"{_ARM_BASE}{resource_id}"
            "/providers/Microsoft.Insights/dataCollectionRuleAssociations"
        )
        resp = requests.get(
            assoc_url,
            params={"api-version": "2022-06-01"},
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(
                "vm_metrics: DCR association list failed for %s status=%d",
                resource_id[-60:], resp.status_code,
            )
        else:
            for assoc in resp.json().get("value", []):
                dcr_id: Optional[str] = assoc.get("properties", {}).get("dataCollectionRuleId")
                if not dcr_id:
                    continue  # configurationAccessEndpoint has no DCR

                # Step 2: fetch DCR and extract workspace GUID
                dcr_resp = requests.get(
                    f"{_ARM_BASE}{dcr_id}",
                    params={"api-version": "2022-06-01"},
                    headers=headers,
                    timeout=15,
                )
                if dcr_resp.status_code != 200:
                    continue

                la_dests = (
                    dcr_resp.json()
                    .get("properties", {})
                    .get("destinations", {})
                    .get("logAnalytics", [])
                )
                for dest in la_dests:
                    ws_guid = dest.get("workspaceId", "")
                    if ws_guid:
                        logger.info(
                            "vm_metrics: discovered workspace %s for Arc VM %s via DCR %s",
                            ws_guid, resource_id[-60:], dcr_id[-60:],
                        )
                        _arc_workspace_cache[resource_id] = ws_guid
                        return ws_guid

    except Exception as exc:
        logger.warning(
            "vm_metrics: workspace discovery via DCR failed for %s: %s",
            resource_id[-60:], exc,
        )

    # Step 3: fall back to env-var configured workspace
    fallback_resource_id = _LA_WORKSPACE_RESOURCE_ID
    if fallback_resource_id:
        fallback_guid = _resolve_workspace_guid(credential, fallback_resource_id)
        _arc_workspace_cache[resource_id] = fallback_guid
        return fallback_guid

    logger.warning(
        "vm_metrics: no workspace found for Arc VM %s — "
        "set LOG_ANALYTICS_WORKSPACE_RESOURCE_ID or attach a DCR with a Log Analytics destination",
        resource_id[-60:],
    )
    _arc_workspace_cache[resource_id] = ""
    return ""


def _resolve_workspace_guid(credential: Any, workspace_resource_id: str) -> str:
    """Resolve a Log Analytics workspace ARM resource ID to its customerId (GUID).

    Uses a module-level cache so repeated calls for the same workspace
    do not hit ARM again.  Returns empty string on failure (never raises).
    """
    if not workspace_resource_id:
        return ""

    cached = _workspace_guid_cache.get(workspace_resource_id)
    if cached is not None:
        return cached

    parts = workspace_resource_id.split("/")
    try:
        sub_idx = next(i for i, p in enumerate(parts) if p.lower() == "subscriptions")
        ws_sub = parts[sub_idx + 1]
        rg_idx = next(i for i, p in enumerate(parts) if p.lower() == "resourcegroups")
        ws_rg = parts[rg_idx + 1]
        ws_name = parts[-1]
    except (StopIteration, IndexError):
        logger.warning(
            "vm_metrics: cannot parse workspace ARM ID %r", workspace_resource_id
        )
        _workspace_guid_cache[workspace_resource_id] = ""
        return ""

    try:
        if LogAnalyticsManagementClient is None:
            logger.warning("vm_metrics: azure-mgmt-loganalytics not installed")
            _workspace_guid_cache[workspace_resource_id] = ""
            return ""
        client = LogAnalyticsManagementClient(credential, ws_sub)
        workspace = client.workspaces.get(ws_rg, ws_name)
        customer_id: str = workspace.customer_id or ""
        _workspace_guid_cache[workspace_resource_id] = customer_id
        return customer_id
    except Exception as exc:
        logger.warning(
            "vm_metrics: failed to resolve workspace GUID for %r: %s",
            workspace_resource_id, exc,
        )
        _workspace_guid_cache[workspace_resource_id] = ""
        return ""


_ISO_TO_KQL_TIMESPAN: Dict[str, str] = {
    "PT1H": "1h",
    "PT6H": "6h",
    "PT24H": "24h",
    "P7D": "7d",
    "P30D": "30d",
}

_ISO_TO_KQL_INTERVAL: Dict[str, str] = {
    "PT1M": "1m",
    "PT5M": "5m",
    "PT15M": "15m",
    "PT30M": "30m",
    "PT1H": "1h",
    "PT6H": "6h",
    "PT12H": "12h",
    "P1D": "1d",
}


def _iso_to_kql_duration(iso: str, mapping: Dict[str, str], fallback: str) -> str:
    """Convert an ISO 8601 duration string to a KQL timespan literal.

    KQL's ago() and bin() only accept KQL literals like ``7d``, ``1h``,
    ``5m`` — not ISO 8601 strings like ``P7D`` or ``PT5M``.
    Falls back to ``fallback`` for any unrecognised value.
    """
    return mapping.get(iso, fallback)


def _build_arc_metrics_kql(resource_id: str, counters: List[str], timespan: str, interval: str) -> str:
    """Build a KQL query against the Perf table for Arc VM metrics.

    Groups results into time bins matching the requested interval so the
    frontend receives evenly-spaced time-series data.

    ``timespan`` and ``interval`` are ISO 8601 durations (e.g. ``P7D``,
    ``PT5M``) and are converted to KQL literals before embedding.
    """
    safe_rid = resource_id.replace("'", "''").lower()
    counter_list = ", ".join(f"'{c}'" for c in counters)
    kql_timespan = _iso_to_kql_duration(timespan, _ISO_TO_KQL_TIMESPAN, "24h")
    kql_interval = _iso_to_kql_duration(interval, _ISO_TO_KQL_INTERVAL, "5m")

    return (
        f"Perf\n"
        f"| where TimeGenerated > ago({kql_timespan})\n"
        f"| where _ResourceId =~ '{safe_rid}'\n"
        f"| where CounterName in ({counter_list})\n"
        f"| summarize avg(CounterValue) by bin(TimeGenerated, {kql_interval}), CounterName\n"
        f"| order by CounterName asc, TimeGenerated asc"
    )


def _parse_arc_metrics_response(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse KQL Perf table rows into the same format as Azure Monitor metrics.

    Returns a list of ``{name, unit, timeseries}`` dicts compatible with the
    platform metrics response format.
    """
    # Group rows by CounterName
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        counter = row.get("CounterName", "")
        if counter not in grouped:
            grouped[counter] = []
        grouped[counter].append(row)

    metrics_out: List[Dict[str, Any]] = []
    for counter_name, data_points in grouped.items():
        mapping = _PERF_COUNTER_MAP.get(counter_name)
        if not mapping:
            # Use the raw counter name if no mapping exists
            metric_name = counter_name
            unit = ""
        else:
            metric_name = mapping["name"]
            unit = mapping["unit"]

        timeseries = []
        for dp in data_points:
            ts = dp.get("TimeGenerated", "")
            avg_val = dp.get("avg_CounterValue")
            if avg_val is not None:
                try:
                    avg_val = float(avg_val)
                except (ValueError, TypeError):
                    avg_val = None
            timeseries.append({
                "timestamp": ts,
                "average": avg_val,
                "maximum": avg_val,  # KQL summarize only has avg; reuse
                "minimum": avg_val,
            })

        # Deduplicate: if multiple counters map to the same metric name
        # (e.g. "Available MBytes" and "Available Bytes" both -> "Available Memory Bytes"),
        # keep the one with more data points.
        existing = next((m for m in metrics_out if m["name"] == metric_name), None)
        if existing:
            if len(timeseries) > len(existing["timeseries"]):
                existing["timeseries"] = timeseries
                existing["unit"] = unit
        else:
            metrics_out.append({
                "name": metric_name,
                "unit": unit,
                "timeseries": timeseries,
            })

    return metrics_out


def _fetch_arc_vm_metrics_sync(
    credential: Any,
    workspace_guid: str,
    resource_id: str,
    metric_names: List[str],
    timespan: str,
    interval: str,
) -> List[Dict[str, Any]]:
    """Query Log Analytics Perf table for Arc VM metrics (synchronous).

    Maps requested metric names (frontend METRIC_CATALOG names) back to
    Perf counter names, queries, and returns results in platform format.
    """
    if LogsQueryClient is None:
        logger.warning("vm_metrics: azure-monitor-query not installed — cannot query LA for Arc")
        return []

    # Reverse-map: metric catalog name -> Perf counter names
    reverse_map: Dict[str, List[str]] = {}
    for counter, mapping in _PERF_COUNTER_MAP.items():
        reverse_map.setdefault(mapping["name"], []).append(counter)

    # Determine which Perf counters to query based on requested metric names
    counters_to_query: List[str] = []
    for metric_name in metric_names:
        if metric_name in reverse_map:
            counters_to_query.extend(reverse_map[metric_name])
        # Also check if it's a raw counter name
        elif metric_name in _PERF_COUNTER_MAP:
            counters_to_query.append(metric_name)

    if not counters_to_query:
        # Fall back to default counters
        counters_to_query = list(_ARC_DEFAULT_COUNTERS)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_counters: List[str] = []
    for c in counters_to_query:
        if c not in seen:
            seen.add(c)
            unique_counters.append(c)

    kql = _build_arc_metrics_kql(resource_id, unique_counters, timespan, interval)

    try:
        client = LogsQueryClient(credential)
        response = client.query_workspace(
            workspace_id=workspace_guid,
            query=kql,
            timespan=timespan,
        )

        if response.status == LogsQueryStatus.SUCCESS:
            rows: List[Dict[str, Any]] = []
            for table in response.tables:
                col_names = [col.name for col in table.columns]
                for row in table.rows:
                    rows.append(
                        dict(zip(col_names, [str(v) if v is not None else None for v in row]))
                    )
            return _parse_arc_metrics_response(rows)
        else:
            logger.warning(
                "vm_metrics: arc LA query partial/failed | status=%s error=%s",
                response.status, getattr(response, "partial_error", ""),
            )
            return []
    except Exception as exc:
        logger.error(
            "vm_metrics: arc LA query failed | error=%s", exc, exc_info=True
        )
        return []


@router.get("/{resource_id_base64}/metrics")
async def get_vm_metrics(
    resource_id_base64: str,
    metrics: str = Query(
        ",".join(DEFAULT_METRICS[:4]),
        description="Comma-separated metric names",
    ),
    timespan: str = Query("PT24H", description="ISO 8601 duration"),
    interval: str = Query("PT5M", description="ISO 8601 interval"),
    credential=Depends(get_credential),
    _user=Depends(verify_token),
) -> Dict[str, Any]:
    """Return time-series metric data for a VM.

    Each metric is fetched in a separate Azure Monitor call executed
    concurrently.  This isolates SKU-specific metrics (e.g. CPU Credits,
    OS Disk Bandwidth) that would otherwise poison an entire batched request
    and cause all metrics to return empty.
    """
    start = time.monotonic()

    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        sub_id = _extract_subscription_id(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    metric_names = [m.strip() for m in metrics.split(",") if m.strip()]
    logger.info(
        "vm_metrics: request | resource=%s metrics=%d timespan=%s arc=%s",
        resource_id[-60:], len(metric_names), timespan, _is_arc_vm(resource_id),
    )

    # -------------------------------------------------------------------
    # Arc VMs: query Log Analytics Perf table instead of platform metrics
    # -------------------------------------------------------------------
    if _is_arc_vm(resource_id):
        import asyncio

        loop = asyncio.get_event_loop()

        # Auto-discover the workspace from the VM's DCR associations.
        # Falls back to LOG_ANALYTICS_WORKSPACE_RESOURCE_ID env var if no DCR found.
        workspace_guid = await loop.run_in_executor(
            None, _discover_arc_vm_workspace, credential, resource_id,
        )
        if not workspace_guid:
            duration_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "vm_metrics: arc VM — no Log Analytics workspace discoverable | duration_ms=%.0f",
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "timespan": timespan,
                "interval": interval,
                "metrics": [],
                "source": "log_analytics",
            }

        metrics_out = await loop.run_in_executor(
            None,
            _fetch_arc_vm_metrics_sync,
            credential,
            workspace_guid,
            resource_id,
            metric_names,
            timespan,
            interval,
        )

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "vm_metrics: arc complete | resource=%s returned=%d duration_ms=%.0f",
            resource_id[-60:], len(metrics_out), duration_ms,
        )
        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "interval": interval,
            "metrics": metrics_out,
            "source": "log_analytics",
        }

    # -------------------------------------------------------------------
    # Azure VMs: use platform metrics (Azure Monitor)
    # -------------------------------------------------------------------
    try:
        import asyncio
        from azure.mgmt.monitor import MonitorManagementClient

        client = MonitorManagementClient(credential, sub_id)
        loop = asyncio.get_event_loop()

        # Fetch each metric concurrently — one unsupported metric cannot
        # poison the other results.
        tasks = [
            loop.run_in_executor(
                None,
                _fetch_single_metric,
                client,
                resource_id,
                name,
                timespan,
                interval,
            )
            for name in metric_names
        ]
        results = await asyncio.gather(*tasks)

        # Filter out None (unsupported / empty metrics)
        metrics_out = [r for r in results if r is not None]

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "vm_metrics: complete | resource=%s requested=%d returned=%d duration_ms=%.0f",
            resource_id[-60:], len(metric_names), len(metrics_out), duration_ms,
        )

        return {
            "resource_id": resource_id,
            "timespan": timespan,
            "interval": interval,
            "metrics": metrics_out,
            "source": "platform_metrics",
        }

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "vm_metrics: failed | resource=%s error=%s duration_ms=%.0f",
            resource_id[-60:], exc, duration_ms, exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Metrics unavailable: {exc}")


# ---------------------------------------------------------------------------
# AMA + DCR helpers — replaced deprecated microsoft.insights/diagnosticSettings
# (deprecated 2026-03-31) with Azure Monitor Agent + Data Collection Rules.
# ---------------------------------------------------------------------------

_ARM_BASE = "https://management.azure.com"


def _arm_token(credential: Any) -> str:
    """Acquire a bearer token for the ARM audience."""
    return credential.get_token("https://management.azure.com/.default").token


def _is_arc_vm(resource_id: str) -> bool:
    """Return True if the resource ID belongs to an Arc-enabled server."""
    return "microsoft.hybridcompute" in resource_id.lower()


def _check_ama_installed(credential: Any, resource_id: str, os_type: str) -> bool:
    """Check if a monitoring agent extension is installed on the VM.

    Detects both the modern Azure Monitor Agent (AMA) and legacy agents
    (MicrosoftMonitoringAgent / OmsAgentForLinux) so that VMs with
    VM Insights enabled via either path are correctly recognised.

    Handles both Azure VMs (Microsoft.Compute) and Arc-enabled servers
    (Microsoft.HybridCompute).  Lists all extensions and checks names
    rather than probing a single extension by name, avoiding false
    negatives when ``os_type`` is not yet known at call time.

    API versions:
    - Azure VMs:  ``2023-03-01``
    - Arc VMs:    ``2024-07-10``  (HybridCompute extensions API)
    """
    # Known monitoring agent extension names (case-insensitive match)
    _MONITORING_EXTENSIONS = {
        "azuremonitorlinuxagent",
        "azuremonitorwindowsagent",
        "microsoftmonitoringagent",       # Legacy MMA (Windows)
        "omsagentforlinux",               # Legacy OMS (Linux)
    }

    token = _arm_token(credential)
    api_version = "2024-07-10" if _is_arc_vm(resource_id) else "2023-03-01"
    url = f"{_ARM_BASE}{resource_id}/extensions"
    resp = requests.get(
        url,
        params={"api-version": api_version},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return False

    extensions = resp.json().get("value", [])
    for ext in extensions:
        ext_name = (ext.get("name") or "").lower()
        if ext_name in _MONITORING_EXTENSIONS:
            return True
    return False


def _list_dcr_associations(credential: Any, resource_id: str) -> List[Dict[str, Any]]:
    """List Data Collection Rule associations for a VM resource."""
    token = _arm_token(credential)
    url = f"{_ARM_BASE}{resource_id}/providers/Microsoft.Insights/dataCollectionRuleAssociations"
    resp = requests.get(
        url,
        params={"api-version": "2022-06-01"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json().get("value", [])
    return []


def _ensure_platform_dcr(
    credential: Any,
    workspace_resource_id: str,
    subscription_id: str,
    resource_group: str,
) -> str:
    """Create the platform DCR if it doesn't exist. Returns DCR resource ID."""
    token = _arm_token(credential)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Resolve LA workspace location from ARM
    ws_url = f"{_ARM_BASE}{workspace_resource_id}"
    ws_resp = requests.get(ws_url, params={"api-version": "2022-10-01"}, headers=headers, timeout=15)
    location = ws_resp.json().get("location", "eastasia") if ws_resp.status_code == 200 else "eastasia"

    dcr_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Insights/dataCollectionRules/{_DCR_NAME}"
    )

    body = {
        "location": location,
        "properties": {
            "dataSources": {
                "performanceCounters": [
                    {
                        "name": "aap-perf-windows",
                        "streams": ["Microsoft-Perf"],
                        "samplingFrequencyInSeconds": 60,
                        "counterSpecifiers": [
                            "\\Processor Information(_Total)\\% Processor Time",
                            "\\Memory\\Available Bytes",
                            "\\LogicalDisk(_Total)\\Disk Read Bytes/sec",
                            "\\LogicalDisk(_Total)\\Disk Write Bytes/sec",
                            "\\Network Interface(*)\\Bytes Received/sec",
                            "\\Network Interface(*)\\Bytes Sent/sec",
                        ],
                    },
                    {
                        "name": "aap-perf-linux",
                        "streams": ["Microsoft-Perf"],
                        "samplingFrequencyInSeconds": 60,
                        "counterSpecifiers": [
                            "Processor(*)\\% Processor Time",
                            "Memory(*)\\Available MBytes Memory",
                            "Logical Disk(*)\\Disk Read Bytes/sec",
                            "Logical Disk(*)\\Disk Write Bytes/sec",
                            "Network(*)\\Total Bytes Received",
                            "Network(*)\\Total Bytes Transmitted",
                        ],
                    },
                ],
                "syslog": [
                    {
                        "name": "aap-syslog",
                        "streams": ["Microsoft-Syslog"],
                        "facilityNames": ["auth", "cron", "daemon", "kern", "syslog"],
                        "logLevels": ["Warning", "Error", "Critical", "Alert", "Emergency"],
                    }
                ],
                "windowsEventLogs": [
                    {
                        "name": "aap-windows-events",
                        "streams": ["Microsoft-Event"],
                        "xPathQueries": [
                            "System!*[System[(Level=1 or Level=2 or Level=3)]]",
                            "Application!*[System[(Level=1 or Level=2)]]",
                        ],
                    }
                ],
            },
            "destinations": {
                "logAnalytics": [
                    {
                        "workspaceResourceId": workspace_resource_id,
                        "name": "aap-la-dest",
                    }
                ]
            },
            "dataFlows": [
                {"streams": ["Microsoft-Perf"], "destinations": ["aap-la-dest"]},
                {"streams": ["Microsoft-Syslog"], "destinations": ["aap-la-dest"]},
                {"streams": ["Microsoft-Event"], "destinations": ["aap-la-dest"]},
            ],
        },
    }

    put_url = f"{_ARM_BASE}{dcr_id}"
    put_resp = requests.put(
        put_url,
        params={"api-version": "2022-06-01"},
        headers=headers,
        json=body,
        timeout=30,
    )
    if not put_resp.ok:
        raise ValueError(f"Failed to create DCR: {put_resp.status_code}: {put_resp.text[:300]}")
    return dcr_id


def _create_dcr_association(credential: Any, resource_id: str, dcr_id: str) -> None:
    """Associate a Data Collection Rule with a VM."""
    token = _arm_token(credential)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = (
        f"{_ARM_BASE}{resource_id}/providers/Microsoft.Insights"
        f"/dataCollectionRuleAssociations/{_DCR_ASSOC_NAME}"
    )
    body = {"properties": {"dataCollectionRuleId": dcr_id}}
    resp = requests.put(
        url,
        params={"api-version": "2022-06-01"},
        headers=headers,
        json=body,
        timeout=30,
    )
    if not resp.ok:
        raise ValueError(f"Failed to create DCR association: {resp.status_code}: {resp.text[:300]}")


def _install_ama_extension(
    credential: Any, resource_id: str, os_type: str, location: str
) -> None:
    """Install the Azure Monitor Agent extension on the VM."""
    token = _arm_token(credential)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    is_windows = os_type.lower() == "windows"
    ext_name = "AzureMonitorWindowsAgent" if is_windows else "AzureMonitorLinuxAgent"
    ext_type = "AzureMonitorWindowsAgent" if is_windows else "AzureMonitorLinuxAgent"

    body = {
        "location": location,
        "properties": {
            "publisher": "Microsoft.Azure.Monitor",
            "type": ext_type,
            "typeHandlerVersion": "1.0",
            "autoUpgradeMinorVersion": True,
            "enableAutomaticUpgrade": True,
        },
    }

    url = f"{_ARM_BASE}{resource_id}/extensions/{ext_name}"
    resp = requests.put(
        url,
        params={"api-version": "2023-03-01"},
        headers=headers,
        json=body,
        timeout=60,
    )
    if not resp.ok and resp.status_code != 409:  # 409 = already exists
        raise ValueError(f"Failed to install AMA: {resp.status_code}: {resp.text[:300]}")


# ---------------------------------------------------------------------------
# Diagnostic settings routes (AMA + DCR)
# ---------------------------------------------------------------------------

@router.get("/{resource_id_base64}/diagnostic-settings")
async def get_diagnostic_settings(
    resource_id_base64: str,
    os_type: str = Query("windows", description="VM OS type: windows or linux"),
    credential=Depends(get_credential),
    _user=Depends(verify_token),
) -> Dict[str, Any]:
    """Check whether AMA is installed and a DCR association exists for this VM."""
    start_time = time.monotonic()

    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    import asyncio

    loop = asyncio.get_event_loop()

    ama_task = loop.run_in_executor(None, _check_ama_installed, credential, resource_id, os_type)
    dcr_task = loop.run_in_executor(None, _list_dcr_associations, credential, resource_id)

    ama_installed, dcr_list = await asyncio.gather(ama_task, dcr_task)
    dcr_associated = len(dcr_list) > 0

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "diag_settings: check | resource=%s ama=%s dcr=%s duration_ms=%.0f",
        resource_id[-60:], ama_installed, dcr_associated, duration_ms,
    )

    return {
        "ama_installed": ama_installed,
        "dcr_associated": dcr_associated,
        "configured": ama_installed and dcr_associated,
    }


@router.post("/{resource_id_base64}/diagnostic-settings")
async def enable_diagnostic_settings(
    resource_id_base64: str,
    os_type: str = Query("linux", description="VM OS type: windows or linux"),
    credential=Depends(get_credential),
    _user=Depends(verify_token),
) -> Dict[str, Any]:
    """Enable AMA monitoring: install Azure Monitor Agent, create platform DCR,
    and associate the DCR with the VM.
    """
    start_time = time.monotonic()

    try:
        resource_id = _decode_resource_id(resource_id_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Arc VMs: not supported via this API
    if _is_arc_vm(resource_id):
        raise HTTPException(
            status_code=400,
            detail="AMA installation via this API is not supported for Arc VMs. "
            "Use Azure Policy or Arc extension management.",
        )

    workspace_resource_id = _LA_WORKSPACE_RESOURCE_ID
    if not workspace_resource_id:
        raise HTTPException(
            status_code=503,
            detail="LOG_ANALYTICS_WORKSPACE_RESOURCE_ID is not configured on the API gateway.",
        )

    logger.info(
        "diag_settings: enable | resource=%s workspace=%s os_type=%s",
        resource_id[-60:], workspace_resource_id[-60:], os_type,
    )

    try:
        sub_id = _extract_subscription_id(resource_id)
        # Extract resource group from the ARM resource ID
        parts = resource_id.split("/")
        rg_idx = next(i for i, p in enumerate(parts) if p.lower() == "resourcegroups")
        resource_group = parts[rg_idx + 1]

        # Get the VM's own location (required for AMA extension install).
        # Do NOT use the workspace location — it may be in a different region.
        token = _arm_token(credential)
        vm_resp = requests.get(
            f"{_ARM_BASE}{resource_id}",
            params={"api-version": "2023-03-01"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        location = vm_resp.json().get("location", "eastus") if vm_resp.status_code == 200 else "eastus"
        logger.info("diag_settings: vm location=%s", location)

        import asyncio

        loop = asyncio.get_event_loop()

        # Step 1: Ensure platform DCR exists
        dcr_id = await loop.run_in_executor(
            None, _ensure_platform_dcr, credential, workspace_resource_id, sub_id, resource_group
        )

        # Step 2: Create DCR association + install AMA in parallel
        assoc_task = loop.run_in_executor(None, _create_dcr_association, credential, resource_id, dcr_id)
        ama_task = loop.run_in_executor(None, _install_ama_extension, credential, resource_id, os_type, location)
        await asyncio.gather(assoc_task, ama_task)

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "diag_settings: enabled | resource=%s dcr=%s duration_ms=%.0f",
            resource_id[-60:], dcr_id, duration_ms,
        )

        return {
            "status": "enabled",
            "ama_installed": True,
            "dcr_associated": True,
            "configured": True,
        }
    except HTTPException:
        raise
    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "diag_settings: failed | resource=%s error=%s duration_ms=%.0f",
            resource_id[-60:], exc, duration_ms, exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Failed to enable monitoring: {exc}")
