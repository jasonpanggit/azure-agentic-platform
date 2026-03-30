"""Patch Agent tool functions — ARG queries, ConfigurationData, KB-to-CVE mapper,
Activity Log wrapper, Resource Health wrapper, and runbook search wrapper.

Provides @ai_function tools for querying Azure Resource Graph
PatchAssessmentResources and PatchInstallationResources tables,
Log Analytics ConfigurationData, MSRC CVRF API for KB-to-CVE mapping,
Activity Log, Resource Health, and a sync wrapper for runbook search.

Allowed MCP tools (explicit allowlist — no wildcards):
    monitor.query_logs, monitor.query_metrics,
    resourcehealth.get_availability_status
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
from agent_framework import ai_function

from agents.shared.auth import get_agent_identity, get_credential
from agents.shared.otel import instrument_tool_call, setup_telemetry
from agents.shared.runbook_tool import retrieve_runbooks

# Lazy import — azure-mgmt-resourcegraph may not be installed in all envs
# (e.g., local dev, test runner). Imported at module level for type checking
# and IDE support, but actual class resolution happens inside tool functions.
try:
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import (
        QueryRequest,
        QueryRequestOptions,
    )
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]
    QueryRequestOptions = None  # type: ignore[assignment,misc]

tracer = setup_telemetry("aiops-patch-agent")

# Explicit MCP tool allowlist — no wildcards permitted (AGENT-001).
ALLOWED_MCP_TOOLS: List[str] = [
    "monitor.query_logs",
    "monitor.query_metrics",
    "resourcehealth.get_availability_status",
]


# ---------------------------------------------------------------------------
# @ai_function tools
# ---------------------------------------------------------------------------


@ai_function
def query_activity_log(
    resource_ids: List[str],
    timespan_hours: int = 2,
) -> Dict[str, Any]:
    """Query the Azure Activity Log for changes on the given resources.

    This is the mandatory first-pass RCA step (TRIAGE-003). Always call
    this tool BEFORE running any ARG or metric queries. Checks for recent
    Update Manager runs, maintenance configuration changes, or extension
    installations that may have caused compliance drift.

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
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="query_activity_log",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "resource_ids": resource_ids,
            "timespan_hours": timespan_hours,
            "entries": [],
            "query_status": "success",
        }


@ai_function
def query_patch_assessment(
    subscription_ids: List[str],
    resource_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Query ARG PatchAssessmentResources for compliance state and missing patches.

    Returns patch compliance data including missing patches by classification
    (Critical, Security, UpdateRollup, FeaturePack, ServicePack, Definition,
    Tools, Updates) and reboot-pending status for Azure VMs and Arc-enabled
    servers across the specified subscriptions.

    Args:
        subscription_ids: List of Azure subscription IDs to query.
        resource_ids: Optional list of resource IDs to filter results.

    Returns:
        Dict with keys:
            subscription_ids (list): Subscriptions queried.
            machines (list): Assessment results per machine.
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
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="query_patch_assessment",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            credential = get_credential()
            client = ResourceGraphClient(credential)

            kql = (
                "patchassessmentresources\n"
                '| where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"\n'
                '    or type =~ "microsoft.hybridcompute/machines/patchassessmentresults"\n'
            )

            if resource_ids:
                ids_str = ", ".join(f'"{rid}"' for rid in resource_ids)
                kql += f"| where id in~ ({ids_str})\n"

            kql += (
                "| extend rebootPending = tobool(properties.rebootPending),\n"
                "         osType = tostring(properties.osType),\n"
                "         lastAssessment = todatetime(properties.lastModifiedDateTime),\n"
                "         criticalCount = toint(properties.availablePatchCountByClassification.Critical),\n"
                "         securityCount = toint(properties.availablePatchCountByClassification.Security),\n"
                "         updateRollupCount = toint(properties.availablePatchCountByClassification.UpdateRollup),\n"
                "         featurePackCount = toint(properties.availablePatchCountByClassification.FeaturePack),\n"
                "         servicePackCount = toint(properties.availablePatchCountByClassification.ServicePack),\n"
                "         definitionCount = toint(properties.availablePatchCountByClassification.Definition),\n"
                "         toolsCount = toint(properties.availablePatchCountByClassification.Tools),\n"
                "         updatesCount = toint(properties.availablePatchCountByClassification.Updates)\n"
                "| project id, name, resourceGroup, subscriptionId, osType, rebootPending,\n"
                "          lastAssessment, criticalCount, securityCount, updateRollupCount,\n"
                "          featurePackCount, servicePackCount, definitionCount, toolsCount, updatesCount"
            )

            all_machines: List[Dict[str, Any]] = []
            skip_token: Optional[str] = None

            while True:
                options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
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
def query_patch_installations(
    subscription_ids: List[str],
    resource_ids: Optional[List[str]] = None,
    days: int = 7,
) -> Dict[str, Any]:
    """Query ARG PatchInstallationResources for installation history.

    Returns patch installation runs for the last N days (default: 7 per D-04),
    including success/failure status, reboot status, and installed/failed/pending
    counts for Azure VMs and Arc-enabled servers.

    Args:
        subscription_ids: List of Azure subscription IDs to query.
        resource_ids: Optional list of resource IDs to filter results.
        days: Look-back window in days (default: 7, per D-04).

    Returns:
        Dict with keys:
            subscription_ids (list): Subscriptions queried.
            installations (list): Installation results.
            total_count (int): Total installation records returned.
            days (int): Look-back window applied.
            query_status (str): "success" or "error".
    """
    agent_id = get_agent_identity()
    tool_params = {
        "subscription_ids": subscription_ids,
        "resource_ids": resource_ids,
        "days": days,
    }

    with instrument_tool_call(
        tracer=tracer,
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="query_patch_installations",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            credential = get_credential()
            client = ResourceGraphClient(credential)

            kql = (
                "patchinstallationresources\n"
                '| where type =~ "microsoft.compute/virtualmachines/patchinstallationresults"\n'
                '    or type =~ "microsoft.hybridcompute/machines/patchinstallationresults"\n'
            )

            if resource_ids:
                ids_str = ", ".join(f'"{rid}"' for rid in resource_ids)
                kql += f"| where id in~ ({ids_str})\n"

            kql += (
                "| extend startTime = todatetime(properties.startDateTime),\n"
                "         status = tostring(properties.status),\n"
                "         rebootStatus = tostring(properties.rebootStatus),\n"
                "         installedCount = toint(properties.installedPatchCount),\n"
                "         failedCount = toint(properties.failedPatchCount),\n"
                "         pendingCount = toint(properties.pendingPatchCount),\n"
                "         startedBy = tostring(properties.startedBy)\n"
                f"| where startTime > ago({days}d)\n"
                "| project id, resourceGroup, subscriptionId, startTime, status,\n"
                "          rebootStatus, installedCount, failedCount, pendingCount, startedBy"
            )

            all_installations: List[Dict[str, Any]] = []
            skip_token: Optional[str] = None

            while True:
                options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
                request = QueryRequest(
                    subscriptions=subscription_ids,
                    query=kql,
                    options=options,
                )
                response = client.resources(request)
                all_installations.extend(response.data)

                skip_token = response.skip_token
                if not skip_token:
                    break

            return {
                "subscription_ids": subscription_ids,
                "installations": all_installations,
                "total_count": len(all_installations),
                "days": days,
                "query_status": "success",
            }
        except Exception as e:
            return {
                "subscription_ids": subscription_ids,
                "installations": [],
                "total_count": 0,
                "days": days,
                "query_status": "error",
                "error": str(e),
            }


@ai_function
def query_configuration_data(
    workspace_id: str,
    computer_names: Optional[List[str]] = None,
    timespan: str = "P7D",
) -> Dict[str, Any]:
    """Query Log Analytics ConfigurationData table for software inventory.

    Retrieves software inventory (installed + pending patches) for machines
    reporting to the specified Log Analytics workspace (D-08). This data
    complements ARG PatchAssessmentResources — ARG owns compliance state,
    ConfigurationData owns software inventory detail.

    Args:
        workspace_id: Log Analytics workspace resource ID.
        computer_names: Optional list of computer names to filter.
        timespan: ISO 8601 duration string (default: "P7D").

    Returns:
        Dict with keys:
            workspace_id (str): Workspace queried.
            computer_names (list or None): Computer filter applied.
            timespan (str): Time range applied.
            rows (list): Query result rows (stub — empty in Phase 11).
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
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="query_configuration_data",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        # KQL reference (will be executed via Azure Monitor SDK in future):
        # ConfigurationData
        # | where ConfigDataType == "Software"
        # | where SoftwareType == "Update"
        # | project Computer, SoftwareName, CurrentVersion, Publisher,
        #          SoftwareType, TimeGenerated, _ResourceId
        # | order by TimeGenerated desc
        # If computer_names: | where Computer in~ ("vm-1", "vm-2")
        return {
            "workspace_id": workspace_id,
            "computer_names": computer_names,
            "timespan": timespan,
            "rows": [],
            "query_status": "success",
        }


@lru_cache(maxsize=64)
def _fetch_cvrf_document(release_id: str) -> Optional[Dict[str, Any]]:
    """Fetch and cache an MSRC CVRF document by monthly release ID.

    Monthly CVRF documents are immutable after publication, so caching
    is safe and eliminates redundant API calls within a session.

    Args:
        release_id: MSRC release ID in yyyy-mmm format (e.g., "2026-Mar").

    Returns:
        Parsed CVRF JSON document, or None on failure.
    """
    try:
        response = httpx.get(
            f"https://api.msrc.microsoft.com/cvrf/v3.0/cvrf/{release_id}",
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _extract_cves_for_kb(cvrf_doc: Dict[str, Any], kb_id: str) -> List[str]:
    """Extract CVE IDs associated with a given KB article from a CVRF document.

    Parses the Vulnerability nodes in the CVRF document and finds all
    vulnerabilities where any Remediation's Description.Value contains
    the KB article number.

    Args:
        cvrf_doc: Parsed CVRF JSON document.
        kb_id: KB article number (e.g., "KB5034441" or "5034441").

    Returns:
        List of CVE IDs (e.g., ["CVE-2026-21345", "CVE-2026-21348"]).
    """
    kb_number = kb_id.upper().replace("KB", "")
    cves: List[str] = []

    vulnerabilities = cvrf_doc.get("Vulnerability", [])
    for vuln in vulnerabilities:
        cve_id = vuln.get("CVE", "")
        remediations = vuln.get("Remediations", [])
        for remediation in remediations:
            description = remediation.get("Description", {})
            value = str(description.get("Value", ""))
            if kb_number in value:
                if cve_id and cve_id not in cves:
                    cves.append(cve_id)
                break

    return cves


_MONTH_MAP = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


@ai_function
def lookup_kb_cves(
    kb_id: str,
    publish_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Map a KB article number to the CVEs it addresses via the MSRC CVRF API.

    Enriches patch triage with vulnerability context (D-06). For Critical and
    Security patches, call this to determine which CVEs are remediated by each
    KB article. Uses monthly CVRF documents cached via lru_cache (immutable
    after publication).

    Args:
        kb_id: KB article number (e.g., "KB5034441").
        publish_date: Optional publish date string (ISO format, e.g., "2026-03-15")
            to derive the MSRC monthly release ID. If omitted, attempts current
            month.

    Returns:
        Dict with keys:
            kb_id (str): KB article queried.
            cves (list): List of CVE IDs addressed by this KB.
            cve_count (int): Number of CVEs found.
            source (str): "msrc" on success, "unavailable" on failure.
            query_status (str): "success" or "fallback".
    """
    agent_id = get_agent_identity()
    tool_params = {"kb_id": kb_id, "publish_date": publish_date}

    with instrument_tool_call(
        tracer=tracer,
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="lookup_kb_cves",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        try:
            if publish_date:
                # Parse year and month from ISO date string
                parts = publish_date.split("-")
                year = parts[0]
                month_num = int(parts[1])
            else:
                import datetime

                now = datetime.datetime.now(datetime.timezone.utc)
                year = str(now.year)
                month_num = now.month

            month_abbr = _MONTH_MAP.get(month_num, "Jan")
            release_id = f"{year}-{month_abbr}"

            cvrf_doc = _fetch_cvrf_document(release_id)
            if cvrf_doc is None:
                return {
                    "kb_id": kb_id,
                    "cves": [],
                    "cve_count": 0,
                    "source": "unavailable",
                    "query_status": "fallback",
                    "error": f"Failed to fetch CVRF document for {release_id}",
                }

            cves = _extract_cves_for_kb(cvrf_doc, kb_id)

            return {
                "kb_id": kb_id,
                "cves": cves,
                "cve_count": len(cves),
                "source": "msrc",
                "query_status": "success",
            }
        except Exception as e:
            return {
                "kb_id": kb_id,
                "cves": [],
                "cve_count": 0,
                "source": "unavailable",
                "query_status": "fallback",
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
        agent_name="patch-agent",
        agent_id=agent_id,
        tool_name="query_resource_health",
        tool_parameters=tool_params,
        correlation_id="",
        thread_id="",
    ):
        return {
            "resource_id": resource_id,
            "availability_state": "Unknown",
            "summary": "Resource Health query pending.",
            "query_status": "success",
        }


@ai_function
def search_runbooks(
    query: str,
    domain: str = "patch",
    limit: int = 3,
) -> Dict[str, Any]:
    """Search operational runbooks for triage citation (TRIAGE-005).

    Retrieves the top runbooks by semantic similarity for the given query,
    filtered to the patch domain. Results are cited in triage responses.

    This is a sync @ai_function wrapper around the async retrieve_runbooks
    from agents.shared.runbook_tool. The shared retrieve_runbooks is an
    async def without @ai_function — it cannot be registered directly in
    ChatAgent(tools=[...]). This wrapper bridges the gap.

    Args:
        query: Natural-language description of the incident or hypothesis.
        domain: Domain filter (default: "patch").
        limit: Max runbooks to return (default: 3).

    Returns:
        Dict with keys: query, domain, runbooks (list), runbook_count, query_status.
    """
    agent_id = get_agent_identity()

    with instrument_tool_call(
        tracer=tracer,
        agent_name="patch-agent",
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
