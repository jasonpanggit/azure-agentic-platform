"""VM cost summary endpoint.

GET /api/v1/vms/cost-summary — returns top-N underutilized VMs by cost with
Azure Advisor rightsizing recommendations for display in the CostTab.

Design notes:
- Queries Azure Advisor for all Cost category recommendations in all in-scope subscriptions
- Returns the top-N VMs sorted by highest estimated monthly savings opportunity
- 24-48h data lag for Cost Management data is documented in response
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

# Lazy import — may not be available in all environments
try:
    from azure.mgmt.advisor import AdvisorManagementClient
except ImportError:
    AdvisorManagementClient = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vms", tags=["vm-cost"])


@router.get("/cost-summary")
async def get_vm_cost_summary(
    subscription_id: str = Query(..., description="Azure subscription ID to query"),
    top: int = Query(10, ge=1, le=50, description="Maximum number of VMs to return"),
    _token: str = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return top-N underutilized VMs by estimated savings from Azure Advisor.

    Queries Azure Advisor Cost recommendations for the subscription and returns
    the VMs with the highest rightsizing savings opportunity, sorted descending
    by estimated monthly savings.

    Returns:
        {
          "subscription_id": str,
          "total_recommendations": int,
          "vms": [{
            "vm_name": str,
            "resource_group": str,
            "resource_id": str,
            "current_sku": str,          # from extended_properties if available
            "target_sku": str,
            "estimated_monthly_savings": float,
            "annual_savings": float,
            "savings_currency": str,
            "impact": str,               # "High" | "Medium" | "Low"
            "description": str,
            "last_updated": str,
          }],
          "data_lag_note": str
        }
    """
    if AdvisorManagementClient is None:
        return {
            "error": "azure-mgmt-advisor not installed",
            "vms": [],
            "total_recommendations": 0,
        }

    try:
        client = AdvisorManagementClient(credential, subscription_id)

        vms: List[Dict[str, Any]] = []
        for rec in client.recommendations.list():
            if rec.category != "Cost":
                continue
            if not rec.impacted_field or "virtualmachines" not in rec.impacted_field.lower():
                continue

            ext = rec.extended_properties or {}
            resource_id = ""
            resource_group = ""
            if rec.resource_metadata and rec.resource_metadata.resource_id:
                resource_id = rec.resource_metadata.resource_id
                # Extract resource group from ARM resource ID
                parts = resource_id.split("/")
                try:
                    rg_idx = [p.lower() for p in parts].index("resourcegroups")
                    resource_group = parts[rg_idx + 1]
                except (ValueError, IndexError):
                    pass

            vms.append({
                "vm_name": rec.impacted_value or "",
                "resource_group": resource_group,
                "resource_id": resource_id,
                "current_sku": ext.get("currentSku", ext.get("currentSkuName", "")),
                "target_sku": ext.get("recommendedSkuName", ""),
                "estimated_monthly_savings": float(ext.get("savingsAmount", 0) or 0),
                "annual_savings": float(ext.get("annualSavingsAmount", 0) or 0),
                "savings_currency": ext.get("savingsCurrency", "USD"),
                "impact": rec.impact or "Medium",
                "description": (rec.short_description.solution if rec.short_description else ""),
                "last_updated": rec.last_updated.isoformat() if rec.last_updated else "",
            })

        # Sort by highest monthly savings, take top-N
        vms.sort(key=lambda v: v["estimated_monthly_savings"], reverse=True)
        total_recommendations = len(vms)
        vms = vms[:top]

        return {
            "subscription_id": subscription_id,
            "total_recommendations": total_recommendations,
            "vms": vms,
            "data_lag_note": "Advisor recommendations are refreshed every 24 hours.",
        }

    except Exception as exc:
        logger.warning("get_vm_cost_summary error: %s", exc)
        return {
            "error": str(exc),
            "vms": [],
            "total_recommendations": 0,
            "subscription_id": subscription_id,
        }
