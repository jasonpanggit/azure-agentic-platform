"""Patch assessment and installation endpoints for the Web UI Patch tab.

Exposes ARG PatchAssessmentResources and PatchInstallationResources data
via GET endpoints. Also enriches assessment data with ConfigurationData
from Log Analytics, and exposes a per-VM installed patch detail endpoint.

Decisions: D-01, D-02 (from 13-CONTEXT.md)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential
from services.api_gateway.os_normalizer import normalize_os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/patch", tags=["patch"])


def _run_arg_query(
    credential: Any,
    subscription_ids: List[str],
    kql: str,
) -> List[Dict[str, Any]]:
    """Execute an Azure Resource Graph query with pagination.

    Args:
        credential: Azure credential (DefaultAzureCredential).
        subscription_ids: Subscriptions to scope the query.
        kql: KQL query string.

    Returns:
        List of result rows from ARG.

    Raises:
        ImportError: If azure-mgmt-resourcegraph is not installed.
        Exception: On ARG query failure.
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    client = ResourceGraphClient(credential)
    all_rows: List[Dict[str, Any]] = []
    skip_token: Optional[str] = None

    while True:
        options = QueryRequestOptions(skip_token=skip_token) if skip_token else None
        request = QueryRequest(
            subscriptions=subscription_ids,
            query=kql,
            options=options,
        )
        response = client.resources(request)
        all_rows.extend(response.data)

        skip_token = response.skip_token
        if not skip_token:
            break

    return all_rows


# ---------------------------------------------------------------------------
# LAW (Log Analytics Workspace) helpers
# ---------------------------------------------------------------------------


def _query_law_installed_summary_sync(
    credential: Any,
    workspace_id: str,
    resource_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Query LAW for installed software summary per VM (synchronous).

    Returns dict keyed by lowercase resource_id with:
        { "installedCount": int, "lastInstalled": str | None }
    """
    if not workspace_id or not resource_ids:
        return {}

    from azure.monitor.query import LogsQueryClient, LogsQueryStatus

    # Build comma-separated, quoted, lowered resource ID list for KQL
    escaped_ids = ", ".join(
        f"'{rid.lower()}'" for rid in resource_ids
    )

    kql = (
        "ConfigurationData\n"
        "| where TimeGenerated > ago(90d)\n"
        f"| where tolower(_ResourceId) in~ ({escaped_ids})\n"
        '| where SoftwareType in ("Package", "WindowsFeatures", "WindowsPackages", "Hotfix", "Update")\n'
        "| summarize\n"
        "    InstalledCount = count(),\n"
        "    LastInstalled = max(TimeGenerated)\n"
        "  by ResourceId = tolower(_ResourceId)"
    )

    client = LogsQueryClient(credential)
    response = client.query_workspace(
        workspace_id=workspace_id,
        query=kql,
        timespan=timedelta(days=90),
    )

    result: Dict[str, Dict[str, Any]] = {}
    if response.status == LogsQueryStatus.SUCCESS and response.tables:
        for row in response.tables[0].rows:
            resource_id_lower = str(row[2]) if len(row) > 2 else ""
            installed_count = int(row[0]) if row[0] is not None else 0
            last_installed = str(row[1]) if row[1] is not None else None
            if resource_id_lower:
                result[resource_id_lower] = {
                    "installedCount": installed_count,
                    "lastInstalled": last_installed,
                }
    return result


async def _query_law_installed_summary(
    credential: Any,
    workspace_id: str,
    resource_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Async wrapper for LAW installed summary query.

    Returns empty dict on any failure (graceful degradation).
    """
    if not workspace_id or not resource_ids:
        return {}

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _query_law_installed_summary_sync,
            credential,
            workspace_id,
            resource_ids,
        )
    except Exception as exc:
        logger.warning("LAW installed summary query failed (degraded): %s", exc)
        return {}


def _query_law_installed_detail_sync(
    credential: Any,
    workspace_id: str,
    resource_id: str,
    days: int,
) -> List[Dict[str, Any]]:
    """Query LAW for per-VM installed patch detail (synchronous).

    Returns list of dicts with patch detail fields.
    """
    if not workspace_id or not resource_id:
        return []

    from azure.monitor.query import LogsQueryClient, LogsQueryStatus

    escaped_resource_id = resource_id.replace("'", "''")

    kql = (
        "ConfigurationData\n"
        f"| where TimeGenerated > ago({days}d)\n"
        f"| where _ResourceId =~ '{escaped_resource_id}'\n"
        '| where SoftwareType in ("Package", "WindowsFeatures", "WindowsPackages", "Hotfix", "Update")\n'
        "| project\n"
        "    SoftwareName,\n"
        "    SoftwareType,\n"
        "    CurrentVersion,\n"
        "    Publisher,\n"
        "    Category = SoftwareClassification,\n"
        "    InstalledDate = TimeGenerated\n"
        "| order by InstalledDate desc"
    )

    client = LogsQueryClient(credential)
    response = client.query_workspace(
        workspace_id=workspace_id,
        query=kql,
        timespan=timedelta(days=days),
    )

    results: List[Dict[str, Any]] = []
    if response.status == LogsQueryStatus.SUCCESS and response.tables:
        columns = [col.name for col in response.tables[0].columns]
        for row in response.tables[0].rows:
            record = dict(zip(columns, row))
            # Stringify datetime values
            for key in ("InstalledDate",):
                if record.get(key) is not None:
                    record[key] = str(record[key])
            results.append(record)
    return results


async def _query_law_installed_detail(
    credential: Any,
    workspace_id: str,
    resource_id: str,
    days: int,
) -> List[Dict[str, Any]]:
    """Async wrapper for LAW installed detail query.

    Returns empty list on any failure (graceful degradation).
    """
    if not workspace_id or not resource_id:
        return []

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _query_law_installed_detail_sync,
            credential,
            workspace_id,
            resource_id,
            days,
        )
    except Exception as exc:
        logger.warning("LAW installed detail query failed (degraded): %s", exc)
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/assessment")
async def get_patch_assessment(
    subscriptions: str,
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return per-machine patch compliance data from ARG.

    Enriches each machine with installed patch counts from Log Analytics
    (ConfigurationData table) when LOG_ANALYTICS_WORKSPACE_ID is configured.
    LAW enrichment is gracefully degraded — assessment data is always returned
    even if LAW is unavailable.

    Query param:
        subscriptions: Comma-separated subscription IDs.

    Returns:
        { machines: [...], total_count: int, query_status: str }
    """
    subscription_ids = [s.strip() for s in subscriptions.split(",") if s.strip()]
    if not subscription_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="subscriptions query parameter is required",
        )

    # KQL: Start from `resources` (the authoritative VM list) and left-join
    # `patchassessmentresources` onto it.  This guarantees that every Azure VM
    # and Arc-enabled server appears in the results regardless of whether Azure
    # Update Manager has ever run an assessment on it.
    #
    # Join key:
    #   resources.id = /subscriptions/.../virtualMachines/vm-name
    #   patchassessmentresources.id = .../virtualMachines/vm-name/patchAssessmentResults/latest
    #   → strip '/patchAssessmentResults/...' suffix to derive the parent machine ID.
    #
    # osVersion coalesce priority:
    #   1. properties.osSku  — Arc: "Windows Server 2016 Standard" (friendly, confirmed via ARG)
    #                          Azure VMs: raw SKU like "WindowsServer2022-datacenter-g2" (normalized in Python)
    #   2. properties.extended.instanceView.osName — Azure VMs with instance view populated
    #   3. imageReference offer+sku concat — Azure VMs marketplace image
    #   4. properties.osType — last resort ("Windows" / "Linux")
    kql = (
        "resources\n"
        '| where type =~ "microsoft.compute/virtualmachines"\n'
        '    or type =~ "microsoft.hybridcompute/machines"\n'
        "| extend machineIdLower = tolower(id)\n"
        "| extend machineName = name,\n"
        "         osType = tostring(properties.osType),\n"
        "         osVersion = coalesce(\n"
        "             // Arc machines: osSku has the friendly name e.g. 'Windows Server 2016 Standard'\n"
        "             tostring(properties.osSku),\n"
        "             // Azure VMs with instance view populated\n"
        "             tostring(properties.extended.instanceView.osName),\n"
        "             // Azure VMs: construct from marketplace image reference\n"
        "             iff(\n"
        "                 isnotempty(tostring(properties.storageProfile.imageReference.offer)),\n"
        "                 strcat(\n"
        "                     tostring(properties.storageProfile.imageReference.offer),\n"
        '                     " ",\n'
        "                     tostring(properties.storageProfile.imageReference.sku)\n"
        "                 ),\n"
        '                 ""\n'
        "             ),\n"
        "             tostring(properties.osType)\n"
        "         ),\n"
        '         vmType = iff(type =~ "microsoft.hybridcompute/machines", "Arc VM", "Azure VM")\n'
        "| join kind=leftouter (\n"
        "    patchassessmentresources\n"
        '    | where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"\n'
        '        or type =~ "microsoft.hybridcompute/machines/patchassessmentresults"\n'
        "    | extend patchMachineId = tostring(split(tolower(id), '/patchassessmentresults/')[0])\n"
        "    | extend\n"
        "        rebootPending = tobool(properties.rebootPending),\n"
        "        lastAssessment = todatetime(properties.lastModifiedDateTime),\n"
        # Arc VMs use lowercase keys (critical, security, updateRollup…);
        # Azure VMs use PascalCase (Critical, Security, UpdateRollup…).
        # coalesce() picks the first non-null so both resource types are covered.
        "        criticalCount = coalesce(toint(properties.availablePatchCountByClassification.critical), toint(properties.availablePatchCountByClassification.Critical), 0),\n"
        "        securityCount = coalesce(toint(properties.availablePatchCountByClassification.security), toint(properties.availablePatchCountByClassification.Security), 0),\n"
        "        updateRollupCount = coalesce(toint(properties.availablePatchCountByClassification.updateRollup), toint(properties.availablePatchCountByClassification.UpdateRollup), 0),\n"
        "        featurePackCount = coalesce(toint(properties.availablePatchCountByClassification.featurePack), toint(properties.availablePatchCountByClassification.FeaturePack), 0),\n"
        "        servicePackCount = coalesce(toint(properties.availablePatchCountByClassification.servicePack), toint(properties.availablePatchCountByClassification.ServicePack), 0),\n"
        "        definitionCount = coalesce(toint(properties.availablePatchCountByClassification.definition), toint(properties.availablePatchCountByClassification.Definition), 0),\n"
        "        toolsCount = coalesce(toint(properties.availablePatchCountByClassification.tools), toint(properties.availablePatchCountByClassification.Tools), 0),\n"
        "        updatesCount = coalesce(toint(properties.availablePatchCountByClassification.updates), toint(properties.availablePatchCountByClassification.Updates), 0)\n"
        "    | project patchMachineId, rebootPending, lastAssessment,\n"
        "              criticalCount, securityCount, updateRollupCount,\n"
        "              featurePackCount, servicePackCount, definitionCount,\n"
        "              toolsCount, updatesCount\n"
        "  ) on $left.machineIdLower == $right.patchMachineId\n"
        "| extend hasAssessmentData = isnotnull(patchMachineId)\n"
        "| extend rebootPending = iff(hasAssessmentData, rebootPending, false),\n"
        "         criticalCount = iff(hasAssessmentData, criticalCount, 0),\n"
        "         securityCount = iff(hasAssessmentData, securityCount, 0),\n"
        "         updateRollupCount = iff(hasAssessmentData, updateRollupCount, 0),\n"
        "         featurePackCount = iff(hasAssessmentData, featurePackCount, 0),\n"
        "         servicePackCount = iff(hasAssessmentData, servicePackCount, 0),\n"
        "         definitionCount = iff(hasAssessmentData, definitionCount, 0),\n"
        "         toolsCount = iff(hasAssessmentData, toolsCount, 0),\n"
        "         updatesCount = iff(hasAssessmentData, updatesCount, 0)\n"
        "| extend osVersion = iff(isempty(osVersion) or osVersion == ' ', osType, osVersion)\n"
        "| project id, machineName, resourceGroup, subscriptionId, osType, osVersion,\n"
        "          vmType, hasAssessmentData, rebootPending, lastAssessment, criticalCount,\n"
        "          securityCount, updateRollupCount, featurePackCount, servicePackCount,\n"
        "          definitionCount, toolsCount, updatesCount"
    )

    try:
        machines = _run_arg_query(credential, subscription_ids, kql)
    except ImportError:
        logger.error("azure-mgmt-resourcegraph is not installed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure Resource Graph SDK not available",
        )
    except Exception as exc:
        logger.error("ARG patch assessment query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ARG query failed: {exc}",
        )

    # Enrich with LAW ConfigurationData (gracefully degraded)
    resource_ids = [m["id"] for m in machines if m.get("id")]
    workspace_id = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")
    law_summary = await _query_law_installed_summary(
        credential, workspace_id, resource_ids
    )

    for m in machines:
        law_data = law_summary.get(m.get("id", "").lower(), {})
        m["installedCount"] = law_data.get("installedCount", 0)
        m["lastInstalled"] = law_data.get("lastInstalled")
        # Normalize raw OS SKU strings into human-readable names
        m["osVersion"] = normalize_os(m.get("osVersion"), m.get("osType"))

    return {
        "machines": machines,
        "total_count": len(machines),
        "query_status": "success",
    }


@router.get("/installations")
async def get_patch_installations(
    subscriptions: str,
    days: int = 7,
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return patch installation run history from ARG.

    Query params:
        subscriptions: Comma-separated subscription IDs.
        days: Look-back window in days (default: 7).

    Returns:
        { installations: [...], total_count: int, days: int, query_status: str }
    """
    subscription_ids = [s.strip() for s in subscriptions.split(",") if s.strip()]
    if not subscription_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="subscriptions query parameter is required",
        )

    # KQL ported from agents/patch/tools.py::query_patch_installations (lines 246-267)
    kql = (
        "patchinstallationresources\n"
        '| where type =~ "microsoft.compute/virtualmachines/patchinstallationresults"\n'
        '    or type =~ "microsoft.hybridcompute/machines/patchinstallationresults"\n'
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

    try:
        installations = _run_arg_query(credential, subscription_ids, kql)
        return {
            "installations": installations,
            "total_count": len(installations),
            "days": days,
            "query_status": "success",
        }
    except ImportError:
        logger.error("azure-mgmt-resourcegraph is not installed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Azure Resource Graph SDK not available",
        )
    except Exception as exc:
        logger.error("ARG patch installations query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ARG query failed: {exc}",
        )


@router.get("/installed")
async def get_installed_patches(
    resource_id: str = Query(...),
    days: int = Query(default=90, ge=1, le=365),
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return installed patch detail for a specific VM from Log Analytics.

    For Windows patches (SoftwareType Hotfix or Security category), enriches
    each entry with CVE identifiers from the MSRC API.

    Query params:
        resource_id: Full ARM resource ID of the VM.
        days: Look-back window in days (default: 90, max: 365).

    Returns:
        { patches: [...], total_count: int, resource_id: str, days: int }
    """
    workspace_id = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")
    if not workspace_id:
        logger.warning(
            "LOG_ANALYTICS_WORKSPACE_ID not configured — returning empty patches (degraded)"
        )
        return {
            "patches": [],
            "total_count": 0,
            "resource_id": resource_id,
            "days": days,
            "query_status": "degraded",
        }

    patches = await _query_law_installed_detail(
        credential, workspace_id, resource_id, days
    )

    # Extract KB IDs from Windows patches for MSRC enrichment
    kb_ids_to_lookup: list[str] = []
    patch_kb_map: dict[int, str] = {}  # patch index -> kb_id

    for idx, patch in enumerate(patches):
        software_type = patch.get("SoftwareType", "")
        software_name = patch.get("SoftwareName", "")
        category = patch.get("Category", "")

        # Only look up CVEs for Windows hotfixes and security patches
        if software_type == "Hotfix" or "Security" in (category or ""):
            # Try to extract KB ID from software name (e.g. "KB5034441" or "Update for KB5034441")
            import re
            kb_match = re.search(r"KB(\d+)", software_name, re.IGNORECASE)
            if kb_match:
                kb_id = f"KB{kb_match.group(1)}"
                kb_ids_to_lookup.append(kb_id)
                patch_kb_map[idx] = kb_id

    # Enrich with CVEs (gracefully degraded)
    cve_map: dict[str, list[str]] = {}
    if kb_ids_to_lookup:
        try:
            from services.api_gateway.msrc_client import get_cves_for_kbs
            cve_map = await get_cves_for_kbs(list(set(kb_ids_to_lookup)))
        except Exception as exc:
            logger.warning("MSRC CVE enrichment failed (degraded): %s", exc)

    # Attach CVEs to patches
    for idx, patch in enumerate(patches):
        kb_id = patch_kb_map.get(idx, "")
        patch["cves"] = cve_map.get(kb_id, [])

    return {
        "patches": patches,
        "total_count": len(patches),
        "resource_id": resource_id,
        "days": days,
    }


@router.get("/pending")
async def get_pending_patches(
    resource_id: str = Query(...),
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return pending (available, not yet installed) patches for a specific VM from ARG.

    Uses patchassessmentresources/softwarepatches table — no LAW dependency.

    Query params:
        resource_id: Full ARM resource ID of the VM.

    Returns:
        { patches: [...], total_count: int, resource_id: str }
    """
    # Derive subscription ID from resource_id
    parts = resource_id.split("/")
    try:
        sub_idx = next(i for i, p in enumerate(parts) if p.lower() == "subscriptions")
        subscription_id = parts[sub_idx + 1]
    except (StopIteration, IndexError):
        raise HTTPException(status_code=400, detail="Invalid resource_id — cannot extract subscription ID")

    # Determine resource type prefix for both Azure VMs and Arc machines
    resource_id_lower = resource_id.lower()
    if "microsoft.hybridcompute/machines" in resource_id_lower:
        type_filter = 'type == "microsoft.hybridcompute/machines/patchassessmentresults/softwarepatches"'
    else:
        type_filter = 'type == "microsoft.compute/virtualmachines/patchassessmentresults/softwarepatches"'

    kql = (
        "patchassessmentresources\n"
        f"| where {type_filter}\n"
        f"| where tolower(id) startswith tolower('{resource_id_lower}')\n"
        "| project\n"
        "    patchName = tostring(properties.patchName),\n"
        "    classifications = properties.classifications,\n"
        "    rebootRequired = properties.rebootRequired,\n"
        "    kbid = properties.kbId,\n"
        "    version = properties.version,\n"
        "    publishedDateTime = properties.publishedDateTime\n"
        "| order by tostring(classifications) asc, patchName asc"
    )

    try:
        rows = await asyncio.get_event_loop().run_in_executor(
            None,
            _run_arg_query,
            credential,
            [subscription_id],
            kql,
        )
    except Exception as exc:
        logger.error("ARG pending patches query failed for %s: %s", resource_id, exc)
        raise HTTPException(status_code=502, detail=f"ARG query failed: {exc}")

    patches = []
    for row in rows:
        # classifications may be a list or a single value
        raw_cls = row.get("classifications", [])
        if isinstance(raw_cls, list):
            classifications = [str(c) for c in raw_cls]
        elif raw_cls:
            classifications = [str(raw_cls)]
        else:
            classifications = []

        patches.append({
            "patchName": row.get("patchName") or "",
            "classifications": classifications,
            "rebootRequired": bool(row.get("rebootRequired", False)),
            "kbid": row.get("kbid") or "",
            "version": row.get("version") or "",
            "publishedDateTime": str(row.get("publishedDateTime") or "") or None,
        })

    return {
        "patches": patches,
        "total_count": len(patches),
        "resource_id": resource_id,
    }
