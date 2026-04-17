from __future__ import annotations
"""Subscription management endpoints — Phase 68.

Provides enriched subscription management:
- GET  /api/v1/subscriptions/managed           — all subscriptions with metadata
- PATCH /api/v1/subscriptions/{subscription_id} — update label/monitoring/environment
- POST /api/v1/subscriptions/sync              — trigger immediate re-discovery
- GET  /api/v1/subscriptions/{subscription_id}/stats — per-subscription incident stats

All tool functions never raise — structured error dicts returned on failure.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.api_gateway.dependencies import get_credential, get_scoped_credential, get_optional_cosmos_client

router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])
logger = logging.getLogger(__name__)

COSMOS_DATABASE_NAME = "aap"
INCIDENTS_CONTAINER = "incidents"
SUBSCRIPTIONS_CONTAINER = "subscriptions"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SubscriptionPatchRequest(BaseModel):
    label: Optional[str] = Field(default=None, description="User-set display label")
    monitoring_enabled: Optional[bool] = Field(default=None, description="Toggle monitoring")
    environment: Optional[str] = Field(
        default=None, description="Environment tag: prod/staging/dev"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_subscriptions_container(cosmos_client: Any) -> Any:
    return (
        cosmos_client
        .get_database_client(COSMOS_DATABASE_NAME)
        .get_container_client(SUBSCRIPTIONS_CONTAINER)
    )


def _get_incidents_container(cosmos_client: Any) -> Any:
    return (
        cosmos_client
        .get_database_client(COSMOS_DATABASE_NAME)
        .get_container_client(INCIDENTS_CONTAINER)
    )


def _fetch_incident_counts(cosmos_client: Any, subscription_id: str) -> dict:
    """Query incidents container for counts. Returns safe zeros on failure."""
    result = {
        "incident_count_24h": 0,
        "open_incidents": 0,
        "sev0_count": 0,
        "sev1_count": 0,
        "resolved_count_24h": 0,
    }
    if cosmos_client is None:
        return result
    try:
        container = _get_incidents_container(cosmos_client)

        # Open incidents (not resolved)
        open_q = (
            "SELECT VALUE COUNT(1) FROM c "
            "WHERE c.subscription_id = @sub_id AND c.status != 'resolved'"
        )
        open_res = list(container.query_items(
            query=open_q,
            parameters=[{"name": "@sub_id", "value": subscription_id}],
            enable_cross_partition_query=True,
        ))
        result["open_incidents"] = open_res[0] if open_res else 0

        # All incidents in last 24h
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        all_24h_q = (
            "SELECT VALUE COUNT(1) FROM c "
            "WHERE c.subscription_id = @sub_id AND c.created_at >= @cutoff"
        )
        all_24h_res = list(container.query_items(
            query=all_24h_q,
            parameters=[
                {"name": "@sub_id", "value": subscription_id},
                {"name": "@cutoff", "value": cutoff},
            ],
            enable_cross_partition_query=True,
        ))
        result["incident_count_24h"] = all_24h_res[0] if all_24h_res else 0

        # Severity counts (open)
        sev_q = (
            "SELECT c.severity, COUNT(1) as cnt FROM c "
            "WHERE c.subscription_id = @sub_id AND c.status != 'resolved' "
            "GROUP BY c.severity"
        )
        for row in container.query_items(
            query=sev_q,
            parameters=[{"name": "@sub_id", "value": subscription_id}],
            enable_cross_partition_query=True,
        ):
            sev = (row.get("severity") or "").upper()
            cnt = row.get("cnt", 0)
            if sev in ("SEV0", "0"):
                result["sev0_count"] = cnt
            elif sev in ("SEV1", "1"):
                result["sev1_count"] = cnt

        # Resolved in last 24h
        resolved_q = (
            "SELECT VALUE COUNT(1) FROM c "
            "WHERE c.subscription_id = @sub_id AND c.status = 'resolved' "
            "AND c.resolved_at >= @cutoff"
        )
        resolved_res = list(container.query_items(
            query=resolved_q,
            parameters=[
                {"name": "@sub_id", "value": subscription_id},
                {"name": "@cutoff", "value": cutoff},
            ],
            enable_cross_partition_query=True,
        ))
        result["resolved_count_24h"] = resolved_res[0] if resolved_res else 0

    except Exception as exc:
        logger.warning(
            "subscription_endpoints: incident count query failed | sub=%s error=%s",
            subscription_id, exc,
        )
    return result


def _fetch_resource_counts(credential: Any, subscription_id: str) -> dict:
    """Query ARG for resource + VM counts. Returns nulls on failure."""
    result = {"resource_count": None, "vm_count": None}
    try:
        from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
        from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]

        client = ResourceGraphClient(credential)

        # Total resources
        res_q = "Resources | summarize total=count()"
        res_response = client.resources(
            QueryRequest(query=res_q, subscriptions=[subscription_id])
        )
        if res_response.data:
            result["resource_count"] = res_response.data[0].get("total")

        # VM count
        vm_q = (
            "Resources | where type =~ 'microsoft.compute/virtualmachines' "
            "| summarize vm_total=count()"
        )
        vm_response = client.resources(
            QueryRequest(query=vm_q, subscriptions=[subscription_id])
        )
        if vm_response.data:
            result["vm_count"] = vm_response.data[0].get("vm_total")

    except ImportError:
        logger.debug(
            "subscription_endpoints: azure-mgmt-resourcegraph not available; "
            "resource counts unavailable | sub=%s", subscription_id,
        )
    except Exception as exc:
        logger.warning(
            "subscription_endpoints: ARG resource count failed | sub=%s error=%s",
            subscription_id, exc,
        )
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/managed")
async def list_managed_subscriptions(
    cosmos_client: Any = Depends(get_optional_cosmos_client),
    credential: Any = Depends(get_credential),
) -> Any:
    """Return all managed subscriptions with enriched metadata.

    Falls back gracefully when Cosmos is unavailable — returns empty list.
    """
    start_time = time.monotonic()
    try:
        subscriptions = []

        if cosmos_client is None:
            logger.info("subscription_endpoints: managed list — cosmos unavailable, returning empty")
            return {
                "subscriptions": [],
                "total": 0,
                "generated_at": _now_iso(),
                "warning": "Cosmos DB unavailable; subscription metadata not loaded",
            }

        container = _get_subscriptions_container(cosmos_client)
        try:
            items = list(container.read_all_items())
        except Exception as exc:
            logger.warning(
                "subscription_endpoints: managed list cosmos read failed | error=%s", exc
            )
            return {
                "subscriptions": [],
                "total": 0,
                "generated_at": _now_iso(),
                "warning": f"Cosmos read error: {exc}",
            }

        for item in items:
            sub_id = item.get("subscription_id") or item.get("id", "")
            name = item.get("name", sub_id)
            counts = _fetch_incident_counts(cosmos_client, sub_id)
            subscriptions.append({
                "id": sub_id,
                "name": name,
                "label": item.get("label", name),
                "monitoring_enabled": item.get("monitoring_enabled", True),
                "environment": item.get("environment", "prod"),
                "incident_count_24h": counts["incident_count_24h"],
                "open_incidents": counts["open_incidents"],
                "last_synced": item.get("last_synced"),
            })

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "subscription_endpoints: managed list | count=%d duration_ms=%s",
            len(subscriptions), duration_ms,
        )
        return {
            "subscriptions": subscriptions,
            "total": len(subscriptions),
            "generated_at": _now_iso(),
        }

    except Exception as exc:
        logger.warning("subscription_endpoints: managed list error | error=%s", exc)
        return JSONResponse(
            {"error": str(exc), "subscriptions": [], "total": 0},
            status_code=500,
        )


@router.patch("/{subscription_id}")
async def patch_subscription(
    subscription_id: str,
    payload: SubscriptionPatchRequest,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Update subscription label, monitoring_enabled, or environment.

    Upserts to Cosmos `subscriptions` container. Returns 404 if subscription
    not found and Cosmos is available.
    """
    start_time = time.monotonic()
    try:
        if cosmos_client is None:
            return JSONResponse(
                {"error": "Cosmos DB unavailable; cannot persist subscription update"},
                status_code=503,
            )

        container = _get_subscriptions_container(cosmos_client)

        # Read existing doc
        existing: dict = {}
        try:
            existing = container.read_item(
                item=subscription_id, partition_key=subscription_id
            )
        except Exception:
            # Not found — check if it exists at all by querying
            q = "SELECT * FROM c WHERE c.id = @id"
            results = list(container.query_items(
                query=q,
                parameters=[{"name": "@id", "value": subscription_id}],
                enable_cross_partition_query=True,
            ))
            if not results:
                return JSONResponse(
                    {"error": f"Subscription {subscription_id!r} not found"},
                    status_code=404,
                )
            existing = results[0]

        # Apply patch fields (only non-None values)
        update = dict(existing)
        if payload.label is not None:
            update["label"] = payload.label
        if payload.monitoring_enabled is not None:
            update["monitoring_enabled"] = payload.monitoring_enabled
        if payload.environment is not None:
            update["environment"] = payload.environment
        update["updated_at"] = _now_iso()

        container.upsert_item(update)

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "subscription_endpoints: patch | sub=%s duration_ms=%s",
            subscription_id, duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "label": update.get("label"),
            "monitoring_enabled": update.get("monitoring_enabled"),
            "environment": update.get("environment"),
            "updated_at": update["updated_at"],
        }

    except Exception as exc:
        logger.warning(
            "subscription_endpoints: patch error | sub=%s error=%s", subscription_id, exc
        )
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/sync")
async def sync_subscriptions(
    request: Request,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Trigger immediate re-sync of subscription discovery.

    Delegates to SubscriptionRegistry.full_sync() stored on app.state.
    Falls back to creating a fresh registry instance if not on app.state.
    """
    start_time = time.monotonic()
    try:
        from services.api_gateway.subscription_registry import SubscriptionRegistry

        registry: Optional[SubscriptionRegistry] = getattr(
            request.app.state, "subscription_registry", None
        )
        if registry is None:
            registry = SubscriptionRegistry(
                credential=credential,
                cosmos_client=cosmos_client,
            )

        await registry.full_sync()
        synced = len(registry.get_all())
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)

        logger.info(
            "subscription_endpoints: sync complete | synced=%d duration_ms=%s",
            synced, duration_ms,
        )
        return {
            "synced": synced,
            "duration_ms": duration_ms,
            "synced_at": _now_iso(),
        }

    except Exception as exc:
        logger.warning("subscription_endpoints: sync error | error=%s", exc)
        return JSONResponse({"error": str(exc), "synced": 0}, status_code=500)


@router.get("/{subscription_id}/stats")
async def get_subscription_stats(
    subscription_id: str,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
    credential: Any = Depends(get_scoped_credential),
) -> Any:
    """Return per-subscription incident and resource stats.

    Resource counts via ARG are optional — graceful fallback to null.
    """
    start_time = time.monotonic()
    try:
        # Fetch name from Cosmos (best-effort)
        name = subscription_id
        if cosmos_client is not None:
            try:
                container = _get_subscriptions_container(cosmos_client)
                doc = container.read_item(
                    item=subscription_id, partition_key=subscription_id
                )
                name = doc.get("name", subscription_id)
            except Exception:
                pass

        # Incident counts
        counts = _fetch_incident_counts(cosmos_client, subscription_id)

        # Resource counts (ARG — optional)
        resource_info = _fetch_resource_counts(credential, subscription_id)

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "subscription_endpoints: stats | sub=%s open=%d duration_ms=%s",
            subscription_id, counts["open_incidents"], duration_ms,
        )
        return {
            "subscription_id": subscription_id,
            "name": name,
            "incident_count_24h": counts["incident_count_24h"],
            "open_incidents": counts["open_incidents"],
            "sev0_count": counts["sev0_count"],
            "sev1_count": counts["sev1_count"],
            "resolved_count_24h": counts["resolved_count_24h"],
            "resource_count": resource_info["resource_count"],
            "vm_count": resource_info["vm_count"],
            "generated_at": _now_iso(),
        }

    except Exception as exc:
        logger.warning(
            "subscription_endpoints: stats error | sub=%s error=%s", subscription_id, exc
        )
        return JSONResponse({"error": str(exc)}, status_code=500)
