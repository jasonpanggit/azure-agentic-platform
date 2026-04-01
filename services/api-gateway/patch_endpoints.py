"""Patch assessment and installation endpoints for the Web UI Patch tab.

Exposes ARG PatchAssessmentResources and PatchInstallationResources data
via two GET endpoints. The KQL queries are ported from agents/patch/tools.py
(query_patch_assessment and query_patch_installations) — the gateway serves
as the data layer for the UI, not the agent's LLM-callable tools.

Decisions: D-01, D-02 (from 13-CONTEXT.md)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

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


@router.get("/assessment")
async def get_patch_assessment(
    subscriptions: str,
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return per-machine patch compliance data from ARG.

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

    # KQL: join patchassessmentresources with resources to get machine name and OS version.
    # The patchassessmentresources `name` field is always "latest" and `id` is the assessment
    # resource path, so we extract the parent machine ID and join with the resources table
    # to get human-readable machine names and full OS version info.
    kql = (
        "patchassessmentresources\n"
        '| where type =~ "microsoft.compute/virtualmachines/patchassessmentresults"\n'
        '    or type =~ "microsoft.hybridcompute/machines/patchassessmentresults"\n'
        "| extend machineIdLower = tolower(tostring(split(id, '/patchAssessmentResults/')[0]))\n"
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
        "| join kind=leftouter (\n"
        "    resources\n"
        '    | where type =~ "microsoft.compute/virtualmachines"\n'
        '        or type =~ "microsoft.hybridcompute/machines"\n'
        "    | extend\n"
        "        osVersion = coalesce(\n"
        "            tostring(properties.extended.instanceView.osName),\n"
        "            strcat(tostring(properties.storageProfile.imageReference.offer),\n"
        '                   " ", tostring(properties.storageProfile.imageReference.sku)),\n'
        "            tostring(properties.osName),\n"
        "            tostring(properties.osSku)\n"
        "        )\n"
        "    | project machineIdLower = tolower(id), machineName = name, osVersion\n"
        "  ) on machineIdLower\n"
        "| extend machineName = coalesce(machineName, tostring(split(machineIdLower, '/')[-1]))\n"
        "| extend osVersion = iff(isempty(osVersion) or osVersion == ' ', osType, osVersion)\n"
        "| project id, name, machineName, resourceGroup, subscriptionId, osType, osVersion,\n"
        "          rebootPending, lastAssessment, criticalCount, securityCount,\n"
        "          updateRollupCount, featurePackCount, servicePackCount,\n"
        "          definitionCount, toolsCount, updatesCount"
    )

    try:
        machines = _run_arg_query(credential, subscription_ids, kql)
        return {
            "machines": machines,
            "total_count": len(machines),
            "query_status": "success",
        }
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
