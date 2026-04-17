from __future__ import annotations
"""Deployment API endpoints — GitOps integration (Phase 60).

Routes:
  POST /api/v1/deployments          — ingest deployment event (GitHub webhook)
  GET  /api/v1/deployments          — list recent deployments
  GET  /api/v1/deployments/correlate — correlate deployments to an incident
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from services.api_gateway.dependencies import get_optional_cosmos_client
from services.api_gateway.deployment_tracker import (
    DeploymentEvent,
    DeploymentTracker,
    parse_github_deployment_payload,
)

router = APIRouter(prefix="/api/v1/deployments", tags=["deployments"])
logger = logging.getLogger(__name__)


def _get_tracker(cosmos_client: Any) -> DeploymentTracker:
    return DeploymentTracker(cosmos_client)


@router.post("", status_code=201)
async def ingest_deployment(
    request: Request,
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Ingest a deployment event from GitHub Actions or a direct POST.

    Accepts either:
    - A raw GitHub Actions deployment/deployment_status webhook payload
    - A DeploymentEvent JSON body directly

    The `X-GitHub-Event` header is used to detect GitHub payloads.
    """
    start_time = time.monotonic()
    try:
        body = await request.json()
        github_event = request.headers.get("X-GitHub-Event", "")

        event: Optional[DeploymentEvent] = None

        # Attempt GitHub webhook parsing first if header present
        if github_event in ("deployment", "deployment_status"):
            event = parse_github_deployment_payload(body)

        # Fall back to direct DeploymentEvent parsing
        if event is None:
            try:
                event = DeploymentEvent(**body)
            except Exception as validation_exc:
                logger.warning(
                    "deployment_endpoints: ingest_deployment validation error | error=%s",
                    validation_exc,
                )
                return JSONResponse(
                    {"error": f"Invalid deployment payload: {validation_exc}"},
                    status_code=422,
                )

        tracker = _get_tracker(cosmos_client)
        result = tracker.ingest_event(event)

        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        if "error" in result:
            logger.warning(
                "deployment_endpoints: ingest_deployment store_error | deployment_id=%s error=%s",
                result.get("deployment_id"),
                result.get("error"),
            )
            return JSONResponse(result, status_code=500)

        logger.info(
            "deployment_endpoints: ingest_deployment ok | deployment_id=%s duration_ms=%s",
            result.get("deployment_id"),
            duration_ms,
        )
        return JSONResponse(result, status_code=201)

    except Exception as exc:
        logger.warning("deployment_endpoints: ingest_deployment error | error=%s", exc)
        return JSONResponse(
            {"error": str(exc), "duration_ms": round((time.monotonic() - start_time) * 1000, 1)},
            status_code=500,
        )


@router.get("")
async def list_deployments(
    resource_group: Optional[str] = Query(default=None, description="Filter by Azure resource group"),
    limit: int = Query(default=20, ge=1, le=100),
    hours_back: int = Query(default=24, ge=1, le=168),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """List recent deployments with optional resource group filter."""
    start_time = time.monotonic()
    try:
        tracker = _get_tracker(cosmos_client)
        result = tracker.list_recent(
            resource_group=resource_group,
            limit=limit,
            hours_back=hours_back,
        )
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "deployment_endpoints: list_deployments | rg=%s hours_back=%d count=%d duration_ms=%s",
            resource_group,
            hours_back,
            result.get("total", 0),
            duration_ms,
        )
        return result
    except Exception as exc:
        logger.warning("deployment_endpoints: list_deployments error | error=%s", exc)
        return JSONResponse(
            {"deployments": [], "total": 0, "error": str(exc)},
            status_code=500,
        )


@router.get("/correlate")
async def correlate_deployments(
    incident_id: Optional[str] = Query(default=None, description="Incident ID to look up timestamp"),
    incident_timestamp: Optional[str] = Query(
        default=None, description="ISO 8601 incident timestamp (alternative to incident_id)"
    ),
    resource_group: Optional[str] = Query(default=None, description="Azure resource group"),
    before_min: int = Query(default=30, description="Minutes before incident to include"),
    after_min: int = Query(default=5, description="Minutes after incident to include"),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Find deployments correlated to an incident.

    Requires either incident_id (looks up incident in Cosmos) or incident_timestamp.
    """
    start_time = time.monotonic()
    try:
        # Resolve timestamp from incident_id if needed
        ts = incident_timestamp
        if ts is None and incident_id is not None and cosmos_client is not None:
            try:
                db = cosmos_client.get_database_client("aap")
                inc_container = db.get_container_client("incidents")
                items = list(
                    inc_container.query_items(
                        query="SELECT c.created_at FROM c WHERE c.id = @id",
                        parameters=[{"name": "@id", "value": incident_id}],
                        enable_cross_partition_query=True,
                        max_item_count=1,
                    )
                )
                if items:
                    ts = items[0].get("created_at")
            except Exception as lookup_exc:
                logger.warning(
                    "deployment_endpoints: correlate incident lookup failed | incident_id=%s error=%s",
                    incident_id,
                    lookup_exc,
                )

        if ts is None:
            ts = datetime.now(timezone.utc).isoformat()
            logger.warning(
                "deployment_endpoints: correlate — no timestamp resolved, using now | incident_id=%s",
                incident_id,
            )

        tracker = _get_tracker(cosmos_client)
        result = tracker.correlate(
            incident_timestamp=ts,
            resource_group=resource_group,
            before_min=before_min,
            after_min=after_min,
        )
        result["incident_id"] = incident_id
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.info(
            "deployment_endpoints: correlate | incident_id=%s rg=%s correlated=%d duration_ms=%s",
            incident_id,
            resource_group,
            len(result.get("correlated_deployments", [])),
            duration_ms,
        )
        return result

    except Exception as exc:
        logger.warning("deployment_endpoints: correlate error | error=%s", exc)
        return JSONResponse(
            {"correlated_deployments": [], "error": str(exc)},
            status_code=500,
        )
