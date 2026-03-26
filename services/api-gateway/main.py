"""AAP API Gateway — incident ingestion and Foundry dispatch.

A minimal FastAPI service handling:
- POST /api/v1/incidents — ingest incident, create Foundry thread, dispatch to Orchestrator
- GET /health — health check

No business logic; agents own the reasoning. The gateway is a thin
routing layer between external callers and the Foundry agent runtime.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from services.api_gateway.auth import verify_token
from services.api_gateway.foundry import create_foundry_thread
from services.api_gateway.models import (
    HealthResponse,
    IncidentPayload,
    IncidentResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AAP API Gateway",
    description="Azure Agentic Platform — Incident ingestion and agent dispatch",
    version="1.0.0",
)

# CORS for Web UI (Phase 5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tightened in production via env var
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Inject a correlation ID header into every request/response."""
    correlation_id = request.headers.get(
        "X-Correlation-ID", str(uuid.uuid4())
    )
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint — no authentication required."""
    return HealthResponse(status="ok", version="1.0.0")


@app.post(
    "/api/v1/incidents",
    response_model=IncidentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_incident(
    payload: IncidentPayload,
    token: dict[str, Any] = Depends(verify_token),
) -> IncidentResponse:
    """Ingest an incident and dispatch to the Orchestrator agent.

    Accepts the DETECT-004 incident payload, creates a Foundry
    conversation thread, and returns 202 Accepted with the thread ID.

    Authentication: Entra ID Bearer token required.
    """
    logger.info(
        "Ingesting incident %s (severity=%s, domain=%s)",
        payload.incident_id,
        payload.severity,
        payload.domain,
    )

    # Dedup check (DETECT-005) — before Foundry dispatch
    from services.api_gateway.dedup_integration import check_dedup

    dedup_result = await check_dedup(
        incident_id=payload.incident_id,
        resource_id=payload.affected_resources[0].resource_id,
        severity=payload.severity,
        domain=payload.domain,
        detection_rule=payload.detection_rule,
        affected_resources=[r.model_dump() for r in payload.affected_resources],
        kql_evidence=payload.kql_evidence,
        title=payload.title,
        description=payload.description,
    )

    if dedup_result is not None:
        return IncidentResponse(
            thread_id=dedup_result.get("thread_id", ""),
            status=dedup_result.get("status", "deduplicated"),
        )

    try:
        result = await create_foundry_thread(payload)
    except ValueError as exc:
        logger.error("Foundry dispatch failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Foundry dispatch unavailable: {exc}",
        ) from exc
    except Exception as exc:
        logger.error(
            "Unexpected error dispatching incident %s: %s",
            payload.incident_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error dispatching incident",
        ) from exc

    return IncidentResponse(
        thread_id=result["thread_id"],
        status="dispatched",
    )
