"""AAP API Gateway — incident ingestion and Foundry dispatch.

A minimal FastAPI service handling:
- POST /api/v1/incidents — ingest incident, create Foundry thread, dispatch to Orchestrator
- GET /api/v1/runbooks/search — semantic runbook search via pgvector (TRIAGE-005)
- GET /health — health check

No business logic; agents own the reasoning. The gateway is a thin
routing layer between external callers and the Foundry agent runtime.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from services.api_gateway.audit import query_audit_log
from services.api_gateway.audit_export import generate_remediation_report
from services.api_gateway.auth import verify_token
from services.api_gateway.chat import create_chat_thread, get_chat_result
from services.api_gateway.foundry import create_foundry_thread
from services.api_gateway.incidents_list import list_incidents
from services.api_gateway.models import (
    ApprovalAction,
    ApprovalRecord,
    ApprovalResponse,
    AuditEntry,
    AuditExportResponse,
    ChatRequest,
    ChatResponse,
    ChatResultResponse,
    HealthResponse,
    IncidentPayload,
    IncidentResponse,
    IncidentSummary,
    RunbookResult,
)
from services.api_gateway.approvals import (
    get_approval,
    list_approvals_by_status,
    list_approvals_for_thread,
    process_approval_decision,
)
from services.api_gateway.runbook_rag import generate_query_embedding, search_runbooks

logger = logging.getLogger(__name__)

# OpenTelemetry auto-instrumentation (D-05)
_appinsights_conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
if _appinsights_conn:
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(connection_string=_appinsights_conn)
    logger.info("Azure Monitor OpenTelemetry configured")
else:
    logger.warning("APPLICATIONINSIGHTS_CONNECTION_STRING not set — OTel disabled")

app = FastAPI(
    title="AAP API Gateway",
    description="Azure Agentic Platform — Incident ingestion and agent dispatch",
    version="1.0.0",
)

# CORS for Web UI (Phase 5) — tightened for prod via CORS_ALLOWED_ORIGINS env var (D-15)
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
_cors_origins = [o.strip() for o in CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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


@app.get(
    "/api/v1/runbooks/search",
    response_model=list[RunbookResult],
)
async def search_runbooks_endpoint(
    query: str,
    domain: Optional[str] = None,
    limit: int = 3,
    token: dict[str, Any] = Depends(verify_token),
) -> list[RunbookResult]:
    """Search runbooks by semantic similarity (TRIAGE-005).

    Args:
        query: Natural-language search query.
        domain: Optional domain filter (compute, network, storage, security, arc, sre).
        limit: Maximum results (default 3).

    Authentication: Entra ID Bearer token required.
    """
    embedding = await generate_query_embedding(query)
    results = await search_runbooks(embedding, domain=domain, limit=limit)
    return [RunbookResult(**r) for r in results]


@app.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_chat(
    payload: ChatRequest,
    token: dict[str, Any] = Depends(verify_token),
) -> ChatResponse:
    """Start an operator-initiated chat conversation.

    Creates a Foundry thread and dispatches the operator message
    to the Orchestrator agent.

    Authentication: Entra ID Bearer token required.
    """
    user_id = payload.user_id or token.get("sub", "unknown")
    logger.info("Chat request from user %s: %s", user_id, payload.message[:100])

    try:
        result = await create_chat_thread(payload, user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Foundry dispatch unavailable: {exc}",
        ) from exc

    return ChatResponse(thread_id=result["thread_id"], status="created")


@app.get(
    "/api/v1/chat/{thread_id}/result",
    response_model=ChatResultResponse,
)
async def get_chat_result_endpoint(
    thread_id: str,
    token: dict[str, Any] = Depends(verify_token),
) -> ChatResultResponse:
    """Poll for the result of a Foundry chat run.

    The web UI stream route calls this endpoint to check whether the
    Orchestrator agent has completed its run on a given thread.

    Returns run_status and the assistant reply once completed.
    """
    try:
        result = await get_chat_result(thread_id)
    except Exception as exc:
        logger.error("Failed to fetch chat result for thread %s: %s", thread_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Foundry polling error: {exc}",
        ) from exc

    return ChatResultResponse(
        thread_id=result["thread_id"],
        run_status=result["run_status"],
        reply=result.get("reply"),
    )


@app.post("/api/v1/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_proposal(
    approval_id: str,
    payload: ApprovalAction,
    thread_id: Optional[str] = None,
    token: dict[str, Any] = Depends(verify_token),
) -> ApprovalResponse:
    """Approve a pending remediation proposal (REMEDI-005, TEAMS-003).

    thread_id accepted from either query parameter (backward compat with Web UI)
    or request body (TEAMS-003 Action.Execute sends card data in body).
    """
    effective_thread_id = payload.thread_id or thread_id
    if not effective_thread_id:
        raise HTTPException(
            status_code=400, detail="thread_id required in query or body"
        )
    try:
        await process_approval_decision(
            approval_id=approval_id,
            thread_id=effective_thread_id,
            decision="approved",
            decided_by=payload.decided_by,
            scope_confirmed=payload.scope_confirmed,
        )
        return ApprovalResponse(approval_id=approval_id, status="approved")
    except ValueError as exc:
        error_msg = str(exc)
        if error_msg == "expired":
            raise HTTPException(status_code=410, detail="Approval has expired")
        if error_msg == "scope_confirmation_required":
            raise HTTPException(status_code=403, detail="Production scope confirmation required")
        raise HTTPException(status_code=400, detail=error_msg)


@app.post("/api/v1/approvals/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_proposal(
    approval_id: str,
    payload: ApprovalAction,
    thread_id: Optional[str] = None,
    token: dict[str, Any] = Depends(verify_token),
) -> ApprovalResponse:
    """Reject a pending remediation proposal (REMEDI-005, TEAMS-003).

    thread_id accepted from either query parameter (backward compat with Web UI)
    or request body (TEAMS-003 Action.Execute sends card data in body).
    """
    effective_thread_id = payload.thread_id or thread_id
    if not effective_thread_id:
        raise HTTPException(
            status_code=400, detail="thread_id required in query or body"
        )
    try:
        await process_approval_decision(
            approval_id=approval_id,
            thread_id=effective_thread_id,
            decision="rejected",
            decided_by=payload.decided_by,
        )
        return ApprovalResponse(approval_id=approval_id, status="rejected")
    except ValueError as exc:
        error_msg = str(exc)
        if error_msg == "expired":
            raise HTTPException(status_code=410, detail="Approval has expired")
        raise HTTPException(status_code=400, detail=error_msg)


@app.get("/api/v1/approvals", response_model=list[ApprovalRecord])
async def list_approvals(
    status: str = "pending",
    token: dict[str, Any] = Depends(verify_token),
) -> list[ApprovalRecord]:
    """List approvals by status (TEAMS-005 escalation support).

    Args:
        status: Filter by approval status (default: pending).

    Authentication: Entra ID Bearer token required.
    """
    results = await list_approvals_by_status(status_filter=status)
    return [
        ApprovalRecord(**{k: v for k, v in r.items() if not k.startswith("_")})
        for r in results
    ]


@app.get("/api/v1/approvals/{approval_id}", response_model=ApprovalRecord)
async def get_approval_status(
    approval_id: str,
    thread_id: str,
    token: dict[str, Any] = Depends(verify_token),
) -> ApprovalRecord:
    """Get the current status of an approval record."""
    record = await get_approval(approval_id, thread_id)
    return ApprovalRecord(**{k: v for k, v in record.items() if not k.startswith("_")})


@app.get("/api/v1/incidents", response_model=list[IncidentSummary])
async def list_incidents_endpoint(
    since: Optional[str] = None,
    subscription: Optional[str] = None,
    severity: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    token: dict[str, Any] = Depends(verify_token),
) -> list[IncidentSummary]:
    """List incidents for the alert feed (UI-006).

    Args:
        since: ISO 8601 timestamp; return only incidents created after this time.
        subscription: Comma-separated subscription IDs to filter by.
        severity: Filter by severity level (Sev0–Sev3).
        domain: Filter by domain (compute, network, storage, security, arc, sre).
        status: Filter by status (new, acknowledged, closed).
        limit: Maximum results to return (default 50).

    Authentication: Entra ID Bearer token required.
    """
    sub_ids = subscription.split(",") if subscription else None
    results = await list_incidents(
        since=since,
        subscription_ids=sub_ids,
        severity=severity,
        domain=domain,
        status=status,
        limit=limit,
    )
    return [
        IncidentSummary(**{k: v for k, v in r.items() if not k.startswith("_")})
        for r in results
    ]


@app.get("/api/v1/audit", response_model=list[AuditEntry])
async def get_audit_log(
    incident_id: Optional[str] = None,
    agent: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    limit: int = 50,
    token: dict[str, Any] = Depends(verify_token),
) -> list[AuditEntry]:
    """Query agent action history for the Audit Log tab (AUDIT-004).

    Args:
        incident_id: Filter by incident ID (matched against span properties).
        agent: Filter by agent name (e.g., compute, network, sre).
        action: Filter by action/tool name.
        resource: Filter by resource ID (matched against span properties).
        from_time: ISO 8601 start of time range.
        to_time: ISO 8601 end of time range.
        limit: Maximum results to return (default 50).

    Authentication: Entra ID Bearer token required.
    """
    results = await query_audit_log(
        incident_id=incident_id,
        agent=agent,
        action=action,
        resource=resource,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
    )
    return [AuditEntry(**r) for r in results]


@app.get("/api/v1/audit/export", response_model=AuditExportResponse)
async def export_audit_report(
    from_time: str,
    to_time: str,
    token: dict[str, Any] = Depends(verify_token),
) -> AuditExportResponse:
    """Export remediation activity report (AUDIT-006).

    Returns a structured JSON document with all remediation events in the
    given time range, including approval chains. Designed for SOC 2 auditors.

    Args:
        from_time: ISO 8601 start of period (required).
        to_time: ISO 8601 end of period (required).

    Authentication: Entra ID Bearer token required.
    """
    report = await generate_remediation_report(from_time=from_time, to_time=to_time)
    return AuditExportResponse(**report)
