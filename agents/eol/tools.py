"""EOL Agent tool functions — endoflife.date client, MS Lifecycle client,
PostgreSQL cache helpers, ARG OS/software inventory, proactive estate scan,
Activity Log wrapper, Resource Health wrapper, and runbook search wrapper.

Provides @ai_function functions for querying EOL status from two external sources
(endoflife.date API and Microsoft Product Lifecycle API), caching results
in PostgreSQL (24h TTL), and discovering software inventory via ARG and
Log Analytics ConfigurationData.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from agent_framework import ai_function

from shared.auth import get_agent_identity, get_credential
from shared.otel import instrument_tool_call, setup_telemetry
from shared.runbook_tool import retrieve_runbooks

# Lazy import — asyncpg may not be installed in all envs
try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

# Lazy import — azure-mgmt-resourcegraph may not be installed in all envs
try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-monitor
try:
    from azure.mgmt.monitor import MonitorManagementClient
except ImportError:
    MonitorManagementClient = None  # type: ignore[assignment,misc]

# Lazy import — azure-monitor-query
try:
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:
    LogsQueryClient = None  # type: ignore[assignment,misc]
    LogsQueryStatus = None  # type: ignore[assignment,misc]

# Lazy import — azure-mgmt-resourcehealth
try:
    from azure.mgmt.resourcehealth import MicrosoftResourceHealth
except ImportError:
    MicrosoftResourceHealth = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-eol-agent")
logger = logging.getLogger(__name__)

# Explicit MCP tool allowlist — no wildcards permitted (AGENT-001).
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
]

# EOL cache TTL in hours
CACHE_TTL_HOURS = 24

# Product slug normalization map (ARG/ConfigurationData name -> (source, slug))
# Source: "ms-lifecycle" for Microsoft products, "endoflife.date" for others
PRODUCT_SLUG_MAP: Dict[str, Tuple[str, str]] = {
    # Windows Server — endoflife.date uses "windows-server" with year as cycle
    "windows server 2012": ("endoflife.date", "windows-server"),
    "windows server 2016": ("endoflife.date", "windows-server"),
    "windows server 2019": ("endoflife.date", "windows-server"),
    "windows server 2022": ("endoflife.date", "windows-server"),
    "windows server 2025": ("endoflife.date", "windows-server"),
    # SQL Server — endoflife.date uses "mssqlserver" with year as cycle
    "sql server 2016": ("endoflife.date", "mssqlserver"),
    "sql server 2019": ("endoflife.date", "mssqlserver"),
    "sql server 2022": ("endoflife.date", "mssqlserver"),
    # .NET — endoflife.date uses "dotnet" with major version as cycle
    "dotnet 6": ("endoflife.date", "dotnet"),
    "dotnet 7": ("endoflife.date", "dotnet"),
    "dotnet 8": ("endoflife.date", "dotnet"),
    "dotnet 9": ("endoflife.date", "dotnet"),
    ".net 6": ("endoflife.date", "dotnet"),
    ".net 7": ("endoflife.date", "dotnet"),
    ".net 8": ("endoflife.date", "dotnet"),
    ".net 9": ("endoflife.date", "dotnet"),
    # Linux
    "ubuntu": ("endoflife.date", "ubuntu"),
    "rhel": ("endoflife.date", "rhel"),
    "red hat enterprise linux": ("endoflife.date", "rhel"),
    # Runtimes
    "python": ("endoflife.date", "python"),
    "nodejs": ("endoflife.date", "nodejs"),
    "node.js": ("endoflife.date", "nodejs"),
    # Databases
    "postgresql": ("endoflife.date", "postgresql"),
    "mysql": ("endoflife.date", "mysql"),
    "mssqlserver": ("endoflife.date", "mssqlserver"),
    # Kubernetes
    "kubernetes": ("endoflife.date", "azure-kubernetes-service"),
}

# MS products for source routing (D-02): these go to MS Lifecycle API first
MS_PRODUCTS = frozenset([
    "windows server", "sql server", "dotnet", ".net", "exchange", "iis",
])


# ---------------------------------------------------------------------------
# PostgreSQL DSN resolver
# ---------------------------------------------------------------------------


def resolve_postgres_dsn() -> str:
    """Resolve PostgreSQL DSN from environment variables.

    Resolution order (same as runbook_rag.py):
    1. PGVECTOR_CONNECTION_STRING
    2. POSTGRES_DSN
    3. POSTGRES_HOST + POSTGRES_PORT + POSTGRES_DB + POSTGRES_USER + POSTGRES_PASSWORD
    """
    pgvector_dsn = os.environ.get("PGVECTOR_CONNECTION_STRING", "").strip()
    if pgvector_dsn:
        return pgvector_dsn
    postgres_dsn = os.environ.get("POSTGRES_DSN", "").strip()
    if postgres_dsn:
        return postgres_dsn
    host = os.environ.get("POSTGRES_HOST", "").strip()
    if host:
        port = os.environ.get("POSTGRES_PORT", "5432").strip()
        db = os.environ.get("POSTGRES_DB", "aap").strip()
        user = os.environ.get("POSTGRES_USER", "").strip()
        password = os.environ.get("POSTGRES_PASSWORD", "").strip()
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    raise RuntimeError(
        "No PostgreSQL DSN configured "
        "(PGVECTOR_CONNECTION_STRING, POSTGRES_DSN, or POSTGRES_HOST)"
    )


# ---------------------------------------------------------------------------
# Cache helper functions
# ---------------------------------------------------------------------------


async def get_cached_eol(product: str, version: str) -> Optional[Dict[str, Any]]:
    """Return cached EOL record if not expired, else None."""
    if asyncpg is None:
        return None
    try:
        dsn = resolve_postgres_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                """SELECT product, version, eol_date, is_eol, lts, latest_version,
                          support_end, source, raw_response, cached_at, expires_at
                   FROM eol_cache
                   WHERE product = $1 AND version = $2 AND expires_at > now()
                   ORDER BY cached_at DESC LIMIT 1""",
                product,
                version,
            )
            return dict(row) if row else None
        finally:
            await conn.close()
    except Exception:
        return None


async def set_cached_eol(
    product: str,
    version: str,
    source: str,
    eol_date: Optional[date],
    is_eol: bool,
    lts: Optional[bool],
    latest_version: Optional[str],
    support_end: Optional[date],
    raw_response: Optional[dict],
) -> None:
    """Upsert EOL cache record with 24h TTL."""
    if asyncpg is None:
        return
    try:
        dsn = resolve_postgres_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            raw_json = json.dumps(raw_response) if raw_response else None
            await conn.execute(
                """INSERT INTO eol_cache
                       (product, version, eol_date, is_eol, lts, latest_version,
                        support_end, source, raw_response, cached_at, expires_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, now(),
                           now() + INTERVAL '24 hours')
                   ON CONFLICT (product, version, source)
                   DO UPDATE SET eol_date = EXCLUDED.eol_date,
                                 is_eol = EXCLUDED.is_eol,
                                 lts = EXCLUDED.lts,
                                 latest_version = EXCLUDED.latest_version,
                                 support_end = EXCLUDED.support_end,
                                 raw_response = EXCLUDED.raw_response,
                                 cached_at = now(),
                                 expires_at = now() + INTERVAL '24 hours'""",
                product,
                version,
                eol_date,
                is_eol,
                lts,
                latest_version,
                support_end,
                source,
                raw_json,
            )
        finally:
            await conn.close()
    except Exception:
        pass  # Cache write failure is non-fatal


# ---------------------------------------------------------------------------
# HTTP fetch with retry
# ---------------------------------------------------------------------------


def _fetch_with_retry(
    url: str,
    params: Optional[dict] = None,
    max_retries: int = 3,
    timeout: float = 10.0,
) -> Optional[dict]:
    """Fetch JSON from URL with retry on 429/5xx."""
    for attempt in range(max_retries):
        try:
            response = httpx.get(url, params=params, timeout=timeout)
            if response.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            if attempt == max_retries - 1:
                return None
            time.sleep(1)
        except httpx.RequestError:
            if attempt == max_retries - 1:
                return None
            time.sleep(1)
    return None


# ---------------------------------------------------------------------------
# Slug normalization and EOL classification helpers
# ---------------------------------------------------------------------------


def normalize_product_slug(product_name: str, version: str = "") -> Tuple[str, str, str]:
    """Normalize ARG/ConfigurationData product name to (source, slug, cycle).

    For products in PRODUCT_SLUG_MAP, extracts the year/version from the
    product name itself to use as the cycle (e.g., "Windows Server 2025
    Datacenter Azure Edition" -> slug="windows-server", cycle="2025").

    Returns:
        (source, product_slug, version_cycle) tuple.
        source is "ms-lifecycle" or "endoflife.date".
    """
    lower = product_name.lower().strip()

    # Try exact match in slug map (with version suffix)
    for key in [f"{lower} {version}".strip(), lower]:
        if key in PRODUCT_SLUG_MAP:
            source, slug = PRODUCT_SLUG_MAP[key]
            # Extract year from the key for use as cycle
            cycle = _extract_version_cycle(key, version)
            return (source, slug, cycle)

    # Try prefix matching — check if any slug map key is a prefix of lower
    for key, (source, slug) in PRODUCT_SLUG_MAP.items():
        if lower.startswith(key):
            cycle = _extract_version_cycle(key, version)
            return (source, slug, cycle)

    # Try prefix matching for MS products
    for ms_prefix in MS_PRODUCTS:
        if lower.startswith(ms_prefix):
            # Build MS lifecycle slug: lowercase, hyphenated, with version
            slug = lower.replace(" ", "-")
            return ("ms-lifecycle", slug, version)

    # Default to endoflife.date with lowered product name
    slug = lower.replace(" ", "-")
    return ("endoflife.date", slug, version)


def _extract_version_cycle(slug_map_key: str, fallback_version: str) -> str:
    """Extract a version/year cycle from a slug map key.

    For "windows server 2025" -> "2025"
    For "sql server 2019" -> "2019"
    For "ubuntu" -> fallback_version
    """
    import re as _re
    # Look for a 4-digit year at the end of the key
    m = _re.search(r"(\d{4}(?:\s*r\d)?)$", slug_map_key)
    if m:
        return m.group(1).replace(" ", "-")
    # Look for a version number pattern (e.g., "6", "8.0")
    m = _re.search(r"(\d+(?:\.\d+)?)$", slug_map_key)
    if m:
        return m.group(1)
    return fallback_version


def classify_eol_status(eol_date: Optional[date], is_eol: bool) -> Dict[str, Any]:
    """Classify EOL status and risk level per D-18."""
    today = date.today()

    if is_eol or (eol_date and eol_date < today):
        return {"status": "already_eol", "risk_level": "high", "days_remaining": 0}

    if eol_date is None:
        return {"status": "not_eol", "risk_level": "none", "days_remaining": None}

    days_remaining = (eol_date - today).days

    if days_remaining <= 30:
        return {
            "status": "within_30_days",
            "risk_level": "high",
            "days_remaining": days_remaining,
        }
    elif days_remaining <= 60:
        return {
            "status": "within_60_days",
            "risk_level": "medium",
            "days_remaining": days_remaining,
        }
    elif days_remaining <= 90:
        return {
            "status": "within_90_days",
            "risk_level": "medium",
            "days_remaining": days_remaining,
        }
    else:
        return {
            "status": "not_eol",
            "risk_level": "none",
            "days_remaining": days_remaining,
        }


def _parse_eol_field(eol_value: Any) -> Tuple[Optional[date], bool]:
    """Parse the polymorphic `eol` field from endoflife.date API.

    Returns (eol_date, is_eol):
    - date string "2028-10-31" -> (date(2028,10,31), False)
    - True -> (None, True) — already EOL, no fixed date
    - False -> (None, False) — no planned EOL
    """
    if isinstance(eol_value, bool):
        return (None, eol_value)
    if isinstance(eol_value, str):
        try:
            return (date.fromisoformat(eol_value), False)
        except ValueError:
            return (None, False)
    return (None, False)


# ---------------------------------------------------------------------------
# Async-to-sync bridge helper (same pattern as search_runbooks in patch agent)
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously, bridging event loop contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


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
# @ai_function functions
# ---------------------------------------------------------------------------


@ai_function
def query_activity_log(
    resource_ids: List[str],
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query the Azure Activity Log for changes on the given resources.

    This is the mandatory first-pass RCA step (TRIAGE-003). Always call
    this tool BEFORE running any ARG or metric queries. Checks for recent
    changes, configuration updates, or extension installations that may
    relate to EOL status changes or compliance drift.

    Args:
        resource_ids: List of Azure resource IDs to query.
        timespan_hours: Look-back window in hours (default: 2, per TRIAGE-003).

    Returns:
        Dict with keys:
            resource_ids (list): Resources queried.
            timespan_hours (int): Look-back window.
            entries (list): Activity Log entries found.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_ids": resource_ids, "timespan_hours": timespan_hours}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="query_activity_log",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MonitorManagementClient is None:
                raise ImportError("azure-mgmt-monitor is not installed")

            credential = get_credential()
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
                    all_entries.append(
                        {
                            "eventTimestamp": (
                                event.event_timestamp.isoformat()
                                if event.event_timestamp
                                else None
                            ),
                            "operationName": (
                                event.operation_name.value
                                if event.operation_name
                                else None
                            ),
                            "caller": event.caller,
                            "status": (
                                event.status.value if event.status else None
                            ),
                            "resourceId": event.resource_id,
                            "level": (
                                event.level.value if event.level else None
                            ),
                            "description": event.description,
                        }
                    )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "query_activity_log: complete | resources=%d entries=%d duration_ms=%d",
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
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "query_activity_log: failed | resources=%s error=%s duration_ms=%d",
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


@ai_function
def query_os_inventory(
    subscription_ids: List[str],
    resource_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Query ARG for OS version inventory across Azure VMs and Arc-enabled servers.

    Discovers OS versions for all virtual machines (microsoft.compute/virtualmachines)
    and Arc-enabled servers (microsoft.hybridcompute/machines) across the specified
    subscriptions. Used as the first ARG step in the mandatory triage workflow (D-27).

    Args:
        subscription_ids: List of Azure subscription IDs to query.
        resource_ids: Optional list of resource IDs to filter results.

    Returns:
        Dict with keys:
            subscription_ids (list): Subscriptions queried.
            machines (list): OS inventory results per machine.
            total_count (int): Total machines returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_ids": subscription_ids,
        "resource_ids": resource_ids,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="query_os_inventory",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            credential = get_credential()
            client = ResourceGraphClient(credential)

            # Azure VMs — use instanceView osName and imageReference sku as fallback
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

            # Arc-enabled servers — use properties.osName and properties.osSku
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
                    # Insert resource filter before final project
                    kql_lines = kql.rstrip("\n").split("\n")
                    project_line = kql_lines.pop()
                    kql = (
                        "\n".join(kql_lines)
                        + f"\n| where id in~ ({ids_str})\n"
                        + project_line
                    )

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

            return {
                "subscription_ids": subscription_ids,
                "machines": all_machines,
                "total_count": len(all_machines),
                "query_status": "success",
            }
        except Exception as e:
            return {
                "subscription_ids": subscription_ids,
                "machines": [],
                "total_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_software_inventory(
    workspace_id: str,
    computer_names: Optional[List[str]] = None,
    timespan: str = "P7D",
) -> Dict[str, Any]:
    """Query Log Analytics ConfigurationData for installed runtime and database inventory.

    Retrieves installed software inventory (runtimes, databases) for machines
    reporting to the specified Log Analytics workspace. Filters to EOL-relevant
    software: Python, Node.js, .NET, PostgreSQL, MySQL, SQL Server (D-06).

    Args:
        workspace_id: Log Analytics workspace resource ID.
        computer_names: Optional list of computer names to filter.
        timespan: ISO 8601 duration string (default: "P7D").

    Returns:
        Dict with keys:
            workspace_id (str): Workspace queried.
            computer_names (list or None): Computer filter applied.
            timespan (str): Time range applied.
            rows (list): Query result rows.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "workspace_id": workspace_id,
        "computer_names": computer_names,
        "timespan": timespan,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="query_software_inventory",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()

        if not workspace_id:
            logger.warning("query_software_inventory: no_workspace | workspace_id is empty")
            return {
                "workspace_id": workspace_id,
                "computer_names": computer_names,
                "timespan": timespan,
                "rows": [],
                "query_status": "no_workspace",
            }

        try:
            if LogsQueryClient is None:
                raise ImportError("azure-monitor-query is not installed")

            kql_lines = [
                "ConfigurationData",
                '| where ConfigDataType == "Software"',
                '| where SoftwareType in ("Application", "Package")',
                '| where SoftwareName has_any ("python", "nodejs", "node.js", "dotnet", ".net",',
                '                              "postgresql", "mysql", "sql server")',
                "| project Computer, SoftwareName, CurrentVersion, Publisher,",
                "         TimeGenerated, _ResourceId",
                "| order by TimeGenerated desc",
            ]

            if computer_names:
                names_str = ", ".join(f'"{n}"' for n in computer_names)
                kql_lines.insert(1, f"| where Computer in~ ({names_str})")

            kql_query = "\n".join(kql_lines)

            credential = get_credential()
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
                            dict(zip(col_names, [str(v) if v is not None else None for v in row]))
                        )
                duration_ms = int((time.monotonic() - start_time) * 1000)
                logger.info(
                    "query_software_inventory: complete | workspace=%s rows=%d duration_ms=%d",
                    workspace_id,
                    len(rows),
                    duration_ms,
                )
                return {
                    "workspace_id": workspace_id,
                    "computer_names": computer_names,
                    "timespan": timespan,
                    "rows": rows,
                    "query_status": "success",
                }
            else:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                logger.warning(
                    "query_software_inventory: partial | workspace=%s duration_ms=%d",
                    workspace_id,
                    duration_ms,
                )
                return {
                    "workspace_id": workspace_id,
                    "computer_names": computer_names,
                    "timespan": timespan,
                    "rows": [],
                    "query_status": "partial",
                    "partial_error": str(response.partial_error),
                }

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "query_software_inventory: failed | workspace=%s error=%s duration_ms=%d",
                workspace_id,
                e,
                duration_ms,
                exc_info=True,
            )
            return {
                "workspace_id": workspace_id,
                "computer_names": computer_names,
                "timespan": timespan,
                "rows": [],
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_k8s_versions(
    subscription_ids: List[str],
) -> Dict[str, Any]:
    """Query ARG for Kubernetes version inventory across Arc-enabled Kubernetes clusters.

    Discovers Kubernetes versions for all Arc-connected clusters
    (microsoft.kubernetes/connectedclusters) across the specified subscriptions.
    Used to identify clusters running EOL Kubernetes versions (D-07).

    Args:
        subscription_ids: List of Azure subscription IDs to query.

    Returns:
        Dict with keys:
            subscription_ids (list): Subscriptions queried.
            clusters (list): K8s version inventory per cluster.
            total_count (int): Total clusters returned.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_ids": subscription_ids}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="query_k8s_versions",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            credential = get_credential()
            client = ResourceGraphClient(credential)

            kql = (
                "resources\n"
                '| where type == "microsoft.kubernetes/connectedclusters"\n'
                "| extend kubernetesVersion = tostring(properties.kubernetesVersion),\n"
                "         distribution = tostring(properties.distribution),\n"
                "         totalNodeCount = toint(properties.totalNodeCount),\n"
                "         connectivityStatus = tostring(properties.connectivityStatus)\n"
                "| project id, name, resourceGroup, subscriptionId, kubernetesVersion,\n"
                "          distribution, totalNodeCount, connectivityStatus"
            )

            all_clusters: List[Dict[str, Any]] = []
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
                all_clusters.extend(response.data)

                skip_token = response.skip_token
                if not skip_token:
                    break

            return {
                "subscription_ids": subscription_ids,
                "clusters": all_clusters,
                "total_count": len(all_clusters),
                "query_status": "success",
            }
        except Exception as e:
            return {
                "subscription_ids": subscription_ids,
                "clusters": [],
                "total_count": 0,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_endoflife_date(
    product: str,
    version: str,
) -> Dict[str, Any]:
    """Query the endoflife.date API for EOL lifecycle status of a product version.

    Checks the PostgreSQL cache first (24h TTL). On cache miss, fetches from
    the endoflife.date public API (no auth required), parses the polymorphic
    `eol` field, and stores the result in cache.

    Covers: Ubuntu, RHEL, Python, Node.js, PostgreSQL, MySQL, Kubernetes (AKS),
    Windows Server (fallback), SQL Server (fallback), and 200+ other products.

    Args:
        product: endoflife.date product slug (e.g., "ubuntu", "python", "nodejs",
                 "postgresql", "azure-kubernetes-service", "mssqlserver").
        version: Version cycle (e.g., "22.04", "3.12", "1.28").

    Returns:
        Dict with keys:
            product (str): Product slug queried.
            version (str): Version cycle queried.
            eol_date (str or None): EOL date in ISO format, or None.
            is_eol (bool): Whether the version is already EOL.
            lts (bool or None): Whether this is an LTS release.
            latest_version (str): Most recent patch version in this cycle.
            source (str): "endoflife.date".
            classification (dict): EOL status classification (status, risk_level, days_remaining).
            query_status (str): "success", "not_found", or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"product": product, "version": version}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="query_endoflife_date",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            # Check cache first
            cached = _run_async(get_cached_eol(product, version))
            if cached:
                eol_date_val = cached.get("eol_date")
                is_eol_val = bool(cached.get("is_eol", False))
                eol_date_obj = (
                    eol_date_val if isinstance(eol_date_val, date) else None
                )
                classification = classify_eol_status(eol_date_obj, is_eol_val)
                return {
                    "product": product,
                    "version": version,
                    "eol_date": eol_date_obj.isoformat() if eol_date_obj else None,
                    "is_eol": is_eol_val,
                    "lts": cached.get("lts"),
                    "latest_version": cached.get("latest_version", ""),
                    "source": "endoflife.date",
                    "classification": classification,
                    "query_status": "success",
                    "cache_hit": True,
                }

            # Fetch from endoflife.date API
            url = f"https://endoflife.date/api/{product}/{version}.json"
            data = _fetch_with_retry(url, timeout=10.0)

            if data is None:
                return {
                    "product": product,
                    "version": version,
                    "eol_date": None,
                    "is_eol": False,
                    "lts": None,
                    "latest_version": "",
                    "source": "endoflife.date",
                    "classification": classify_eol_status(None, False),
                    "query_status": "not_found",
                }

            # Parse polymorphic eol field
            eol_date_obj, is_eol_val = _parse_eol_field(data.get("eol", False))

            # Extract additional fields
            latest_version = str(data.get("latest", ""))
            lts_raw = data.get("lts", False)
            lts_val = isinstance(lts_raw, bool) and lts_raw

            support_raw = data.get("support")
            support_end: Optional[date] = None
            if isinstance(support_raw, str):
                try:
                    support_end = date.fromisoformat(support_raw)
                except ValueError:
                    pass

            # Store in cache (non-fatal if DB unavailable)
            _run_async(
                set_cached_eol(
                    product=product,
                    version=version,
                    source="endoflife.date",
                    eol_date=eol_date_obj,
                    is_eol=is_eol_val,
                    lts=lts_val,
                    latest_version=latest_version,
                    support_end=support_end,
                    raw_response=data,
                )
            )

            classification = classify_eol_status(eol_date_obj, is_eol_val)

            return {
                "product": product,
                "version": version,
                "eol_date": eol_date_obj.isoformat() if eol_date_obj else None,
                "is_eol": is_eol_val,
                "lts": lts_val,
                "latest_version": latest_version,
                "source": "endoflife.date",
                "classification": classification,
                "query_status": "success",
                "cache_hit": False,
            }

        except Exception as e:
            return {
                "product": product,
                "version": version,
                "eol_date": None,
                "is_eol": False,
                "lts": None,
                "latest_version": "",
                "source": "endoflife.date",
                "classification": classify_eol_status(None, False),
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_ms_lifecycle(
    product: str,
    version: str = "",
) -> Dict[str, Any]:
    """Query the Microsoft Product Lifecycle API for EOL lifecycle status.

    Checks the PostgreSQL cache first (24h TTL). On cache miss, fetches from
    the Microsoft Product Lifecycle API (no auth required, 1 req/s limit).
    If no result is found in the MS API, silently falls through to
    endoflife.date (D-02 source routing fallback).

    Covers: Windows Server, SQL Server, .NET, Exchange, IIS, and other
    Microsoft products.

    Args:
        product: Microsoft product name (e.g., "Windows Server 2022",
                 "SQL Server 2019", ".NET 8").
        version: Optional version string for disambiguation.

    Returns:
        Dict with keys:
            product (str): Product name queried.
            version (str): Version string queried.
            eol_date (str or None): EOL date in ISO format, or None.
            support_end (str or None): Extended support end date, or None.
            is_eol (bool): Whether the product is already EOL.
            source (str): "ms-lifecycle" or "endoflife.date" (on fallback).
            lifecycle_link (str): Link to Microsoft lifecycle page.
            classification (dict): EOL status classification.
            query_status (str): "success", "not_found", or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"product": product, "version": version}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="query_ms_lifecycle",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            # Check cache first (use product+version as cache key)
            cache_key_product = product.lower().replace(" ", "-")
            cached = _run_async(get_cached_eol(cache_key_product, version))
            if cached and cached.get("source") == "ms-lifecycle":
                eol_date_val = cached.get("eol_date")
                is_eol_val = bool(cached.get("is_eol", False))
                eol_date_obj = (
                    eol_date_val if isinstance(eol_date_val, date) else None
                )
                support_end_val = cached.get("support_end")
                classification = classify_eol_status(eol_date_obj, is_eol_val)
                return {
                    "product": product,
                    "version": version,
                    "eol_date": eol_date_obj.isoformat() if eol_date_obj else None,
                    "support_end": (
                        support_end_val.isoformat()
                        if isinstance(support_end_val, date)
                        else None
                    ),
                    "is_eol": is_eol_val,
                    "source": "ms-lifecycle",
                    "lifecycle_link": "",
                    "classification": classification,
                    "query_status": "success",
                    "cache_hit": True,
                }

            # Fetch from MS Lifecycle API
            url = "https://learn.microsoft.com/api/lifecycle/products"
            params = {
                "$filter": f"contains(productName,'{product}')",
                "$expand": "releases",
            }
            data = _fetch_with_retry(url, params=params, timeout=15.0)

            if data is None or not data.get("products"):
                # D-02 fallback: try endoflife.date
                _, slug, cycle = normalize_product_slug(product, version)
                fallback_result = query_endoflife_date(slug, cycle)
                fallback_result["source"] = fallback_result.get("source", "endoflife.date")
                return fallback_result

            # Find the best matching product in the response
            products = data["products"]
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

            if best_match is None:
                # Fallback to endoflife.date
                _, slug, cycle = normalize_product_slug(product, version)
                fallback_result = query_endoflife_date(slug, cycle)
                return fallback_result

            # Parse MS Lifecycle date fields (ISO datetime strings)
            def _parse_ms_date(val: Any) -> Optional[date]:
                if not val:
                    return None
                try:
                    return datetime.fromisoformat(
                        str(val).replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    return None

            eol_date_obj = _parse_ms_date(best_match.get("eolDate"))
            support_end_obj = _parse_ms_date(best_match.get("eosDate"))
            lifecycle_link = best_match.get("link", "")

            today = date.today()
            is_eol_val = bool(eol_date_obj and eol_date_obj < today)

            # Store in cache
            _run_async(
                set_cached_eol(
                    product=cache_key_product,
                    version=version,
                    source="ms-lifecycle",
                    eol_date=eol_date_obj,
                    is_eol=is_eol_val,
                    lts=None,
                    latest_version=None,
                    support_end=support_end_obj,
                    raw_response=best_match,
                )
            )

            classification = classify_eol_status(eol_date_obj, is_eol_val)

            return {
                "product": product,
                "version": version,
                "eol_date": eol_date_obj.isoformat() if eol_date_obj else None,
                "support_end": (
                    support_end_obj.isoformat() if support_end_obj else None
                ),
                "is_eol": is_eol_val,
                "source": "ms-lifecycle",
                "lifecycle_link": lifecycle_link,
                "classification": classification,
                "query_status": "success",
                "cache_hit": False,
            }

        except Exception as e:
            return {
                "product": product,
                "version": version,
                "eol_date": None,
                "support_end": None,
                "is_eol": False,
                "source": "ms-lifecycle",
                "lifecycle_link": "",
                "classification": classify_eol_status(None, False),
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_resource_health(
    resource_id: str,
) -> Dict[str, Any]:
    """Get Azure Resource Health availability status for a resource.

    MANDATORY before finalising any diagnosis (TRIAGE-002). Determines
    whether the issue is a platform-side failure or a configuration/
    application issue. Diagnosis is INVALID without this signal.

    Args:
        resource_id: Azure resource ID to check.

    Returns:
        Dict with keys:
            resource_id (str): Resource checked.
            availability_state (str): "Available", "Degraded", or "Unavailable".
            summary (str): Human-readable health summary.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"resource_id": resource_id}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="query_resource_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        start_time = time.monotonic()
        try:
            if MicrosoftResourceHealth is None:
                raise ImportError("azure-mgmt-resourcehealth is not installed")

            credential = get_credential()
            sub_id = _extract_subscription_id(resource_id)
            client = MicrosoftResourceHealth(credential, sub_id)
            status = client.availability_statuses.get_by_resource(
                resource_uri=resource_id,
                expand="recommendedActions",
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            availability_state = (
                status.properties.availability_state.value
                if status.properties.availability_state
                else "Unknown"
            )
            logger.info(
                "query_resource_health: complete | resource=%s state=%s duration_ms=%d",
                resource_id,
                availability_state,
                duration_ms,
            )
            return {
                "resource_id": resource_id,
                "availability_state": availability_state,
                "summary": status.properties.summary,
                "reason_type": status.properties.reason_type,
                "occurred_time": (
                    status.properties.occurred_time.isoformat()
                    if status.properties.occurred_time
                    else None
                ),
                "query_status": "success",
            }
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "query_resource_health: failed | resource=%s error=%s duration_ms=%d",
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


@ai_function
def search_runbooks(
    query: str,
    domain: str = "eol",
    limit: int = 3,
) -> Dict[str, Any]:
    """Search operational runbooks for triage citation (TRIAGE-005).

    Retrieves the top runbooks by semantic similarity for the given query,
    filtered to the eol domain by default. Results are cited in triage responses.

    This is a sync @ai_function wrapper around the async retrieve_runbooks
    from shared.runbook_tool. The shared retrieve_runbooks is an
    async def without @ai_function — it cannot be registered directly in
    Agent(tools=[...]). This wrapper bridges the gap.

    Args:
        query: Natural-language description of the incident or hypothesis.
        domain: Domain filter (default: "eol").
        limit: Max runbooks to return (default: 3).

    Returns:
        Dict with keys: query, domain, runbooks (list), runbook_count, query_status.
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="search_runbooks",
        tool_parameters={"query": query, "domain": domain, "limit": limit},
        correlation_id="",
        thread_id="",
    ):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    runbooks = pool.submit(
                        asyncio.run,
                        retrieve_runbooks(query=query, domain=domain, limit=limit),
                    ).result()
            else:
                runbooks = loop.run_until_complete(
                    retrieve_runbooks(query=query, domain=domain, limit=limit)
                )
        except Exception:
            runbooks = asyncio.run(
                retrieve_runbooks(query=query, domain=domain, limit=limit)
            )

        return {
            "query": query,
            "domain": domain,
            "runbooks": runbooks,
            "runbook_count": len(runbooks),
            "query_status": "success" if runbooks else "empty",
        }


@ai_function
def scan_estate_eol(
    subscription_ids: List[str],
) -> Dict[str, Any]:
    """Proactive estate-wide EOL scan across all VMs, Arc servers, and Arc K8s clusters.

    Discovers all machines and clusters across the specified subscriptions,
    checks EOL status for each product/version combination found, and returns
    a scan report with findings classified by EOL risk. Intended for daily
    timer invocation (Fabric Activator or Logic App) and for ad-hoc "scan my
    estate for EOL software" requests.

    Each finding includes resource ID, product, version, EOL date, status
    classification, risk level, and recommended upgrade version. Dedup
    logic uses deterministic finding IDs to prevent duplicate incidents if
    run multiple times.

    Args:
        subscription_ids: List of Azure subscription IDs to scan.

    Returns:
        Dict with keys:
            subscription_ids (list): Subscriptions scanned.
            scan_summary (dict): total_resources, eol_findings, at_risk_findings counts.
            findings (list): EOL findings per resource/product, sorted by risk.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {"subscription_ids": subscription_ids}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="eol-agent",
        agent_id=agent_id,
        tool_name="scan_estate_eol",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            # Step 1: Discover OS inventory from VMs and Arc servers
            os_result = query_os_inventory(subscription_ids)
            machines = os_result.get("machines", [])

            # Step 2: Discover K8s cluster versions
            k8s_result = query_k8s_versions(subscription_ids)
            clusters = k8s_result.get("clusters", [])

            total_resources = len(machines) + len(clusters)
            findings: List[Dict[str, Any]] = []

            # Track already-checked product+version combos to avoid redundant API calls
            eol_cache_local: Dict[str, Dict[str, Any]] = {}

            def _get_eol_status(product_name: str, version_str: str) -> Dict[str, Any]:
                source, slug, cycle = normalize_product_slug(product_name, version_str)
                cache_key = f"{slug}:{cycle}"
                if cache_key in eol_cache_local:
                    return eol_cache_local[cache_key]

                if source == "ms-lifecycle":
                    result = query_ms_lifecycle(product_name, version_str)
                else:
                    result = query_endoflife_date(slug, cycle)

                eol_cache_local[cache_key] = result
                return result

            # Step 3: Assess each machine's OS EOL status
            for machine in machines:
                resource_id = machine.get("id", "")
                os_name = (
                    machine.get("osName")
                    or machine.get("osSku")
                    or machine.get("offer", "")
                )
                os_version = machine.get("osVersion", "")

                if not os_name:
                    continue

                # Normalize: extract major version if needed (e.g., "ubuntu 22.04")
                eol_info = _get_eol_status(os_name, os_version)
                classification = eol_info.get(
                    "classification", classify_eol_status(None, False)
                )

                status = classification.get("status", "not_eol")
                risk_level = classification.get("risk_level", "none")

                # Only report at-risk findings (90d threshold or already EOL)
                if status in ("already_eol", "within_30_days", "within_60_days", "within_90_days"):
                    resource_id_hash = hashlib.sha256(resource_id.encode()).hexdigest()[:8]
                    finding_id = f"eol-{slug if 'slug' in dir() else os_name.lower().replace(' ', '-')}-{resource_id_hash}-{status}"
                    findings.append({
                        "finding_id": finding_id,
                        "resource_id": resource_id,
                        "resource_name": machine.get("name", ""),
                        "resource_group": machine.get("resourceGroup", ""),
                        "subscription_id": machine.get("subscriptionId", ""),
                        "product": os_name,
                        "version": os_version,
                        "eol_date": eol_info.get("eol_date"),
                        "is_eol": eol_info.get("is_eol", False),
                        "status": status,
                        "risk_level": risk_level,
                        "days_remaining": classification.get("days_remaining"),
                        "recommended_version": eol_info.get("latest_version", ""),
                        "source": eol_info.get("source", ""),
                    })

            # Step 4: Assess each K8s cluster's version EOL status
            for cluster in clusters:
                resource_id = cluster.get("id", "")
                k8s_version = cluster.get("kubernetesVersion", "")

                if not k8s_version:
                    continue

                # Extract major.minor (e.g., "1.28" from "1.28.5")
                parts = k8s_version.split(".")
                cycle = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else k8s_version

                eol_info = query_endoflife_date("azure-kubernetes-service", cycle)
                classification = eol_info.get(
                    "classification", classify_eol_status(None, False)
                )

                status = classification.get("status", "not_eol")
                risk_level = classification.get("risk_level", "none")

                if status in ("already_eol", "within_30_days", "within_60_days", "within_90_days"):
                    resource_id_hash = hashlib.sha256(resource_id.encode()).hexdigest()[:8]
                    finding_id = f"eol-kubernetes-{cycle}-{resource_id_hash}-{status}"
                    findings.append({
                        "finding_id": finding_id,
                        "resource_id": resource_id,
                        "resource_name": cluster.get("name", ""),
                        "resource_group": cluster.get("resourceGroup", ""),
                        "subscription_id": cluster.get("subscriptionId", ""),
                        "product": "kubernetes",
                        "version": k8s_version,
                        "eol_date": eol_info.get("eol_date"),
                        "is_eol": eol_info.get("is_eol", False),
                        "status": status,
                        "risk_level": risk_level,
                        "days_remaining": classification.get("days_remaining"),
                        "recommended_version": eol_info.get("latest_version", ""),
                        "source": "endoflife.date",
                    })

            # Sort findings: already_eol and within_30_days (high risk) first
            risk_order = {
                "already_eol": 0,
                "within_30_days": 1,
                "within_60_days": 2,
                "within_90_days": 3,
                "not_eol": 4,
            }
            findings.sort(key=lambda f: risk_order.get(f.get("status", "not_eol"), 5))

            eol_count = sum(1 for f in findings if f["status"] == "already_eol")
            at_risk_count = sum(
                1 for f in findings
                if f["status"] in ("within_30_days", "within_60_days", "within_90_days")
            )

            return {
                "subscription_ids": subscription_ids,
                "scan_summary": {
                    "total_resources": total_resources,
                    "eol_findings": eol_count,
                    "at_risk_findings": at_risk_count,
                },
                "findings": findings,
                "query_status": "success",
            }

        except Exception as e:
            return {
                "subscription_ids": subscription_ids,
                "scan_summary": {
                    "total_resources": 0,
                    "eol_findings": 0,
                    "at_risk_findings": 0,
                },
                "findings": [],
                "query_status": "error",
                "error": str(e),
            }
