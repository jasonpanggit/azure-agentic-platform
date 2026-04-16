"""Quota management endpoints — subscription-wide quota browser (Phase 67).

Extends CapacityPlannerClient to provide:
- GET /api/v1/quotas          — paginated list of ALL quotas with optional filters
- GET /api/v1/quotas/summary  — aggregate counts (total, critical, warning, healthy, top-10)
- GET /api/v1/quotas/request-history — quota increase request history from Azure
- POST /api/v1/quotas/request-increase — submit quota increase request

All tool functions never raise — structured error dicts returned on failure.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client
from services.api_gateway.capacity_planner import (
    CapacityPlannerClient,
    CAPACITY_DEFAULT_LOCATION,
)

router = APIRouter(prefix="/api/v1/quotas", tags=["quotas"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class QuotaIncreaseRequest(BaseModel):
    subscription_id: str = Field(..., description="Azure subscription ID")
    location: str = Field(..., description="Azure region")
    quota_name: str = Field(..., description="Quota identifier (e.g. cores)")
    resource_type: str = Field(default="compute", description="Resource type category")
    current_limit: int = Field(..., description="Current quota limit")
    requested_limit: int = Field(..., description="Requested new limit")
    justification: str = Field(..., min_length=10, description="Business justification")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RESOURCE_TYPE_MAP = {
    "compute": "compute",
    "network": "network",
    "storage": "storage",
}


def _filter_by_resource_type(
    quotas: List[dict], resource_type: Optional[str]
) -> List[dict]:
    """Return quotas filtered by resource_type category. None = return all."""
    if not resource_type or resource_type.lower() == "all":
        return quotas
    target = resource_type.lower()
    return [q for q in quotas if q.get("category", "").lower() == target]


def _paginate(items: List[Any], page: int, page_size: int) -> tuple[List[Any], int]:
    """Return a page slice and total count."""
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], total


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_quotas(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    location: str = Query(default=CAPACITY_DEFAULT_LOCATION, description="Azure region"),
    resource_type: Optional[str] = Query(default=None, description="Filter: compute|network|storage|all"),
    search: Optional[str] = Query(default=None, description="Search quota name (case-insensitive)"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Items per page"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return ALL quotas for a subscription + location, paginated.

    Sorted by usage_pct DESC (most constrained first).
    Supports optional resource_type and name search filters.
    """
    start_time = time.monotonic()
    try:
        planner = CapacityPlannerClient(cosmos_client, credential, subscription_id, location)
        result = planner.get_subscription_quota_headroom(location)
        quotas = result.get("quotas", [])

        # Filter out zero-limit quotas
        quotas = [q for q in quotas if q.get("limit", 0) > 0]

        # Resource type filter
        quotas = _filter_by_resource_type(quotas, resource_type)

        # Name search
        if search:
            search_lower = search.lower()
            quotas = [
                q for q in quotas
                if search_lower in q.get("display_name", "").lower()
                or search_lower in q.get("quota_name", "").lower()
            ]

        # Sort by usage_pct DESC
        quotas.sort(key=lambda q: q.get("usage_pct", 0.0), reverse=True)

        page_items, total = _paginate(quotas, page, page_size)
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)

        logger.info(
            "quota_list: subscription=%s location=%s total=%d page=%d page_size=%d duration_ms=%s",
            subscription_id, location, total, page, page_size, duration_ms,
        )

        return {
            "subscription_id": subscription_id,
            "location": location,
            "quotas": page_items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int(duration_ms),
            "warnings": result.get("warnings", []),
        }

    except Exception as exc:
        logger.warning("quota_list: error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc), "quotas": []}, status_code=500)


@router.get("/summary")
async def get_quota_summary(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    location: str = Query(default=CAPACITY_DEFAULT_LOCATION, description="Azure region"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return summary stats: total, critical, warning, healthy, and top 10 most constrained.

    Top-10 sorted by usage_pct DESC.
    """
    start_time = time.monotonic()
    try:
        planner = CapacityPlannerClient(cosmos_client, credential, subscription_id, location)
        result = planner.get_subscription_quota_headroom(location)
        quotas = [q for q in result.get("quotas", []) if q.get("limit", 0) > 0]

        total = len(quotas)
        critical = sum(1 for q in quotas if q.get("traffic_light") == "red")
        warning = sum(1 for q in quotas if q.get("traffic_light") == "yellow")
        healthy = sum(1 for q in quotas if q.get("traffic_light") == "green")

        # Top 10 most constrained by usage_pct
        top10 = sorted(quotas, key=lambda q: q.get("usage_pct", 0.0), reverse=True)[:10]

        # Category breakdown
        categories: dict = {}
        for q in quotas:
            cat = q.get("category", "unknown")
            if cat not in categories:
                categories[cat] = {"total": 0, "critical": 0, "warning": 0, "healthy": 0}
            categories[cat]["total"] += 1
            light = q.get("traffic_light", "green")
            if light == "red":
                categories[cat]["critical"] += 1
            elif light == "yellow":
                categories[cat]["warning"] += 1
            else:
                categories[cat]["healthy"] += 1

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "quota_summary: subscription=%s total=%d critical=%d warning=%d duration_ms=%s",
            subscription_id, total, critical, warning, duration_ms,
        )

        return {
            "subscription_id": subscription_id,
            "location": location,
            "total": total,
            "critical": critical,
            "warning": warning,
            "healthy": healthy,
            "top_constrained": top10,
            "categories": categories,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int(duration_ms),
        }

    except Exception as exc:
        logger.warning("quota_summary: error | subscription=%s error=%s", subscription_id, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/request-history")
async def get_quota_request_history(
    subscription_id: str = Query(..., description="Azure subscription ID"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return quota increase request history via Azure Support API.

    Returns empty list gracefully when Azure Support API is unavailable
    or no history exists.
    """
    start_time = time.monotonic()
    try:
        # Attempt to fetch from Azure Support API (azure-mgmt-support)
        requests_list: List[dict] = []
        warning: Optional[str] = None

        try:
            from azure.mgmt.support import MicrosoftSupport  # type: ignore[import]
            support_client = MicrosoftSupport(credential, subscription_id)
            tickets = list(support_client.support_tickets.list(
                filter="ServiceId eq 'quota_service'"
            ))
            for ticket in tickets:
                requests_list.append({
                    "ticket_id": ticket.name,
                    "title": ticket.title,
                    "status": ticket.status,
                    "severity": ticket.severity,
                    "created_date": ticket.created_date.isoformat() if ticket.created_date else None,
                    "modified_date": ticket.modified_date.isoformat() if ticket.modified_date else None,
                    "service_display_name": getattr(ticket, "service_display_name", "Quota"),
                    "problem_classification_display_name": getattr(
                        ticket, "problem_classification_display_name", ""
                    ),
                })
        except ImportError:
            warning = "azure-mgmt-support SDK not available; quota request history unavailable"
            logger.debug("quota_request_history: %s", warning)
        except Exception as sdk_exc:
            warning = f"Azure Support API error: {sdk_exc}"
            logger.debug("quota_request_history: SDK error | error=%s", sdk_exc)

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        response: dict = {
            "subscription_id": subscription_id,
            "requests": requests_list,
            "total": len(requests_list),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int(duration_ms),
        }
        if warning:
            response["warning"] = warning
        return response

    except Exception as exc:
        logger.warning(
            "quota_request_history: error | subscription=%s error=%s", subscription_id, exc
        )
        return JSONResponse({"error": str(exc), "requests": []}, status_code=500)


@router.post("/request-increase")
async def request_quota_increase(
    payload: QuotaIncreaseRequest,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Submit a quota increase request via Azure Support API.

    Returns a request_id and status. Falls back gracefully when Support SDK
    is unavailable — returns a simulated pending request for dev/test environments.
    """
    start_time = time.monotonic()
    try:
        if payload.requested_limit <= payload.current_limit:
            return JSONResponse(
                {
                    "error": "requested_limit must be greater than current_limit",
                    "current_limit": payload.current_limit,
                    "requested_limit": payload.requested_limit,
                },
                status_code=400,
            )

        request_id: Optional[str] = None
        status_val = "pending"
        warning: Optional[str] = None

        try:
            from azure.mgmt.support import MicrosoftSupport  # type: ignore[import]
            from azure.mgmt.support.models import (  # type: ignore[import]
                CreateSupportTicketParameters,
                ServiceLevelAgreement,
                ContactProfile,
                TechnicalTicketDetails,
            )
            support_client = MicrosoftSupport(credential, payload.subscription_id)

            import uuid as _uuid
            ticket_name = f"quota-{payload.quota_name}-{_uuid.uuid4().hex[:8]}"

            ticket = support_client.support_tickets.begin_create(
                support_ticket_name=ticket_name,
                create_support_ticket_parameters=CreateSupportTicketParameters(
                    description=(
                        f"Quota increase request for {payload.quota_name} in "
                        f"{payload.location}. "
                        f"Current limit: {payload.current_limit}. "
                        f"Requested limit: {payload.requested_limit}. "
                        f"Justification: {payload.justification}"
                    ),
                    problem_classification_id=(
                        "/providers/Microsoft.Support/services/quota_service"
                        "/problemClassifications/CoresQuotaIncrease"
                    ),
                    severity="minimal",
                    contact_details=ContactProfile(
                        first_name="Operator",
                        last_name="AAP",
                        preferred_contact_method="email",
                        primary_email_address="noreply@aap.local",
                        preferred_time_zone="UTC",
                        country="USA",
                        preferred_support_language="en-US",
                    ),
                    title=(
                        f"Quota increase: {payload.quota_name} → {payload.requested_limit}"
                    ),
                    service_id="/providers/Microsoft.Support/services/quota_service",
                ),
            ).result()
            request_id = ticket.name
            status_val = ticket.status or "pending"
        except ImportError:
            import uuid as _uuid
            request_id = f"sim-{_uuid.uuid4().hex[:12]}"
            status_val = "pending"
            warning = (
                "azure-mgmt-support SDK not available; "
                "request simulated (not submitted to Azure)"
            )
            logger.debug("quota_request_increase: simulated | quota=%s", payload.quota_name)
        except Exception as sdk_exc:
            import uuid as _uuid
            request_id = f"err-{_uuid.uuid4().hex[:8]}"
            status_val = "error"
            warning = f"Azure Support API error: {sdk_exc}"
            logger.warning(
                "quota_request_increase: SDK error | quota=%s error=%s",
                payload.quota_name, sdk_exc,
            )

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        response: dict = {
            "request_id": request_id,
            "status": status_val,
            "quota_name": payload.quota_name,
            "location": payload.location,
            "subscription_id": payload.subscription_id,
            "current_limit": payload.current_limit,
            "requested_limit": payload.requested_limit,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int(duration_ms),
        }
        if warning:
            response["warning"] = warning
        return response

    except Exception as exc:
        logger.warning(
            "quota_request_increase: error | quota=%s error=%s",
            payload.quota_name, exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=500)
