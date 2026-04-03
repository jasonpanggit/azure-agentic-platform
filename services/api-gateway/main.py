"""AAP API Gateway — incident ingestion and Foundry dispatch.

A minimal FastAPI service handling:
- POST /api/v1/incidents — ingest incident, create Foundry thread, dispatch to Orchestrator
- GET /api/v1/runbooks/search — semantic runbook search via pgvector (TRIAGE-005)
- GET /health — health check

No business logic; agents own the reasoning. The gateway is a thin
routing layer between external callers and the Foundry agent runtime.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.api_gateway.http_rate_limiter import (
    chat_rate_limiter,
    incidents_rate_limiter,
)

from services.api_gateway.audit import query_audit_log
from services.api_gateway.dependencies import get_cosmos_client, get_credential, get_optional_cosmos_client
from services.api_gateway.audit_export import generate_remediation_report
from services.api_gateway.auth import verify_token
from services.api_gateway.chat import (
    _approve_pending_subrun_mcp_calls,
    create_chat_thread,
    get_chat_result,
)
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
from services.api_gateway.azure_tools import AzureToolRequest, AzureToolResponse, call_azure_tool
from services.api_gateway.diagnostic_pipeline import run_diagnostic_pipeline
from services.api_gateway.health import router as health_router
from services.api_gateway.patch_endpoints import router as patch_router
from services.api_gateway.vm_inventory import router as vm_inventory_router
from services.api_gateway.vm_detail import router as vm_detail_router
from services.api_gateway.vm_chat import router as vm_chat_router
from services.api_gateway.topology_endpoints import router as topology_router
from services.api_gateway.topology import TopologyClient, run_topology_sync_loop

# Configure root logger so all INFO+ messages appear in Container Apps log stream.
# Override level with LOG_LEVEL env var (e.g. LOG_LEVEL=DEBUG for verbose mode).
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


async def _run_startup_migrations() -> None:
    """Run database migrations on startup if postgres is configured.

    Enables pgvector extension and creates the runbooks table if they don't
    exist. Runs silently if postgres env vars are not set (dev/test mode).
    """
    try:
        import asyncpg
        from services.api_gateway.runbook_rag import (
            RunbookSearchUnavailableError,
            resolve_postgres_dsn,
        )

        try:
            dsn = resolve_postgres_dsn()
        except RunbookSearchUnavailableError:
            logger.info("Runbook DB not configured — skipping startup migrations")
            return

        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS runbooks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    title TEXT UNIQUE NOT NULL,
                    domain TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(1536),
                    version TEXT NOT NULL DEFAULT '1',
                    tags TEXT[] DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            # Idempotent schema migrations: harmonise legacy columns if table pre-existed.
            await conn.execute(
                "ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}'"
            )
            await conn.execute(
                "ALTER TABLE runbooks ALTER COLUMN version TYPE TEXT USING version::TEXT"
            )
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conrelid = 'runbooks'::regclass AND conname = 'runbooks_title_key'
                    ) THEN
                        ALTER TABLE runbooks ADD CONSTRAINT runbooks_title_key UNIQUE (title);
                    END IF;
                END
                $$
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS runbooks_embedding_idx "
                "ON runbooks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
            )
            # EOL cache table (Phase 12) — 24h TTL lifecycle cache
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS eol_cache (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    product         TEXT NOT NULL,
                    version         TEXT NOT NULL,
                    eol_date        DATE,
                    is_eol          BOOLEAN NOT NULL,
                    lts             BOOLEAN,
                    latest_version  TEXT,
                    support_end     DATE,
                    source          TEXT NOT NULL,
                    raw_response    JSONB,
                    cached_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                    expires_at      TIMESTAMPTZ NOT NULL,
                    UNIQUE (product, version, source)
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_eol_cache_lookup "
                "ON eol_cache (product, version, expires_at);"
            )
            logger.info("Startup migrations complete (pgvector + runbooks table + eol_cache table)")
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Startup migrations skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialize shared clients, run migrations, then yield."""
    logger.info("startup: api-gateway starting | version=1.0.0")
    logger.info("startup: COSMOS_ENDPOINT=%s", "set" if os.environ.get("COSMOS_ENDPOINT") else "not_set")
    logger.info("startup: APPLICATIONINSIGHTS_CONNECTION_STRING=%s", "set" if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING") else "not_set")
    logger.info("startup: DIAGNOSTIC_LA_WORKSPACE_ID=%s", "set" if os.environ.get("DIAGNOSTIC_LA_WORKSPACE_ID") else "not_set (log_analytics step will be skipped)")
    logger.info("startup: LOG_LEVEL=%s", os.environ.get("LOG_LEVEL", "INFO"))
    logger.info("startup: CORS_ALLOWED_ORIGINS=%s", os.environ.get("CORS_ALLOWED_ORIGINS", "*"))
    # Initialize shared credential and Cosmos client singletons (CONCERNS 4.4)
    app.state.credential = DefaultAzureCredential()
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "")
    if cosmos_endpoint:
        app.state.cosmos_client = CosmosClient(
            url=cosmos_endpoint, credential=app.state.credential
        )
    else:
        app.state.cosmos_client = None
        logger.warning("COSMOS_ENDPOINT not set — CosmosClient singleton not initialized")

    # Initialize TopologyClient and run bootstrap if Cosmos is configured (TOPO-001)
    _topology_sync_task = None
    subscription_ids_raw = os.environ.get("SUBSCRIPTION_IDS", "")
    _subscription_ids = [s.strip() for s in subscription_ids_raw.split(",") if s.strip()]
    if app.state.cosmos_client is not None and _subscription_ids:
        app.state.topology_client = TopologyClient(
            cosmos_client=app.state.cosmos_client,
            credential=app.state.credential,
            subscription_ids=_subscription_ids,
        )
        # Bootstrap synchronously in startup (blocks until complete — acceptable for
        # Container App startup; large estates may take 30–60s but remain within
        # Container Apps' 240s startup grace period)
        loop = asyncio.get_running_loop()
        try:
            bootstrap_result = await loop.run_in_executor(
                None, app.state.topology_client.bootstrap
            )
            logger.info(
                "startup: topology bootstrap complete | upserted=%d errors=%d",
                bootstrap_result.get("upserted", 0),
                bootstrap_result.get("errors", 0),
            )
        except Exception as exc:
            logger.warning("startup: topology bootstrap failed (non-fatal) | error=%s", exc)
        # Launch background sync loop (TOPO-003: <15 min freshness lag)
        _topology_sync_task = asyncio.create_task(
            run_topology_sync_loop(app.state.topology_client)
        )
        logger.info("startup: topology sync loop started | interval=900s")
    else:
        app.state.topology_client = None
        logger.warning(
            "startup: topology_client not initialized "
            "(COSMOS_ENDPOINT=%s, SUBSCRIPTION_IDS=%s)",
            "set" if app.state.cosmos_client else "not_set",
            "set" if _subscription_ids else "not_set",
        )

    await _run_startup_migrations()
    yield
    # Teardown: close Cosmos client if initialized
    if app.state.cosmos_client is not None:
        app.state.cosmos_client.close()
    # Cancel topology sync loop on shutdown
    if _topology_sync_task is not None and not _topology_sync_task.done():
        _topology_sync_task.cancel()
        try:
            await _topology_sync_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: topology sync loop cancelled")

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
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(patch_router)
app.include_router(vm_inventory_router)
app.include_router(vm_detail_router)
app.include_router(vm_chat_router)
app.include_router(topology_router)

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


@app.middleware("http")
async def apply_http_rate_limit(request: Request, call_next):
    """Apply per-IP rate limits to chat and incidents endpoints (CONCERNS 1.5)."""
    ip = request.client.host if request.client else "unknown"
    path = request.url.path

    if path == "/api/v1/chat" and request.method == "POST":
        if not chat_rate_limiter.check(ip):
            retry = chat_rate_limiter.retry_after(ip)
            return JSONResponse(
                {"detail": "Rate limit exceeded", "retry_after": retry},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
    elif path == "/api/v1/incidents" and request.method == "GET":
        # GET (list) is rate-limited to protect the UI dashboard from polling abuse.
        # POST (ingest) is deliberately NOT rate-limited here — it is called by the
        # Fabric Activator webhook (trusted machine-to-machine) and must not be
        # throttled. POST /api/v1/incidents also requires a valid Entra Bearer token
        # (Depends(verify_token)), which provides its own access control.
        if not incidents_rate_limiter.check(ip):
            retry = incidents_rate_limiter.retry_after(ip)
            return JSONResponse(
                {"detail": "Rate limit exceeded", "retry_after": retry},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )

    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with method, path, status, and duration."""
    start = time.monotonic()
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "http: %s %s | status=%d correlation_id=%s duration_ms=%.0f",
        request.method,
        request.url.path,
        response.status_code,
        correlation_id,
        duration_ms,
    )
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
    background_tasks: BackgroundTasks,
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> IncidentResponse:
    """Ingest an incident and dispatch to the Orchestrator agent.

    Accepts the DETECT-004 incident payload, creates a Foundry
    conversation thread, and returns 202 Accepted with the thread ID.
    Queues the diagnostic pipeline as a BackgroundTask.

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

    # Queue diagnostic pipeline as background task (never blocks 202 response)
    if payload.affected_resources:
        primary_resource = payload.affected_resources[0].resource_id
        background_tasks.add_task(
            run_diagnostic_pipeline,
            incident_id=payload.incident_id,
            resource_id=primary_resource,
            domain=payload.domain,
            credential=credential,
            cosmos_client=cosmos,
        )
        logger.info(
            "pipeline: queued | incident_id=%s resource=%s",
            payload.incident_id, primary_resource,
        )

    return IncidentResponse(
        thread_id=result["thread_id"],
        status="dispatched",
    )


@app.get("/api/v1/incidents/{incident_id}/evidence")
async def get_incident_evidence(
    incident_id: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> dict:
    """Get pre-fetched diagnostic evidence for an incident.

    Returns 202 with retry_after=5 if pipeline is still running.
    Returns 404 if no evidence document exists yet.
    Returns 200 with full evidence document when available.

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Evidence store not configured")
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("evidence")
        doc = container.read_item(incident_id, partition_key=incident_id)
        return doc
    except Exception as e:
        if "404" in str(e) or "NotFound" in type(e).__name__:
            # Evidence not yet written — pipeline may still be running
            return JSONResponse(
                content={"incident_id": incident_id, "pipeline_status": "pending"},
                status_code=202,
                headers={"Retry-After": "5"},
            )
        logger.error(
            "get_incident_evidence: error | incident_id=%s error=%s", incident_id, e, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Evidence retrieval failed")


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
    from services.api_gateway.runbook_rag import RunbookSearchUnavailableError

    try:
        embedding = await generate_query_embedding(query)
        results = await search_runbooks(embedding, domain=domain, limit=limit)
    except RunbookSearchUnavailableError as exc:
        logger.error("Runbook search unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

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

    return ChatResponse(
        thread_id=result["thread_id"],
        run_id=result["run_id"],
        status="created",
    )


@app.get(
    "/api/v1/chat/{thread_id}/result",
    response_model=ChatResultResponse,
)
async def get_chat_result_endpoint(
    thread_id: str,
    background_tasks: BackgroundTasks,
    run_id: Optional[str] = None,
    token: dict[str, Any] = Depends(verify_token),
) -> ChatResultResponse:
    """Poll for the result of a Foundry chat run.

    Returns run_status immediately (non-blocking). When the run is still
    in_progress, schedules a background task to approve any pending MCP
    tool approval gates on connected_agent sub-runs.

    The SSE stream route polls this endpoint every 2s; the approval fires
    after each poll response, keeping the sub-run unblocked.
    """
    try:
        result = await get_chat_result(thread_id, run_id=run_id)
    except Exception as exc:
        logger.error("Failed to fetch chat result for thread %s: %s", thread_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Foundry polling error: {exc}",
        ) from exc

    # Schedule sub-run approval AFTER the response is sent (never blocks caller)
    if result["run_status"] not in ("completed", "failed", "cancelled", "expired") and run_id:
        import os as _os
        _endpoint = _os.environ.get("AZURE_PROJECT_ENDPOINT") or _os.environ.get(
            "FOUNDRY_ACCOUNT_ENDPOINT", ""
        )
        from services.api_gateway.foundry import _get_foundry_client as _gfc
        background_tasks.add_task(
            _approve_pending_subrun_mcp_calls,
            _gfc(), _endpoint, thread_id, run_id,
        )

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
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
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
            cosmos_client=cosmos_client,
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
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
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
            cosmos_client=cosmos_client,
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
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> list[ApprovalRecord]:
    """List approvals by status (TEAMS-005 escalation support).

    Args:
        status: Filter by approval status (default: pending).

    Authentication: Entra ID Bearer token required.
    """
    results = await list_approvals_by_status(status_filter=status, cosmos_client=cosmos_client)
    return [
        ApprovalRecord(**{k: v for k, v in r.items() if not k.startswith("_")})
        for r in results
    ]


@app.get("/api/v1/approvals/{approval_id}", response_model=ApprovalRecord)
async def get_approval_status(
    approval_id: str,
    thread_id: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> ApprovalRecord:
    """Get the current status of an approval record."""
    record = await get_approval(approval_id, thread_id, cosmos_client=cosmos_client)
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
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
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
        cosmos_client=cosmos_client,
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
    try:
        results = await query_audit_log(
            incident_id=incident_id,
            agent=agent,
            action=action,
            resource=resource,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@app.post("/api/v1/azure-tools", response_model=AzureToolResponse)
async def azure_tools(
    request: AzureToolRequest,
    token: dict[str, Any] = Depends(verify_token),
) -> AzureToolResponse:
    """Call an Azure MCP tool via stdio subprocess.

    Provides the Foundry orchestrator with a regular OpenAI function tool
    that calls @azure/mcp via stdio — bypassing Foundry's HTTP MCP client
    which has an AssertionError protocol incompatibility with @azure/mcp.

    Args:
        request: tool_name and arguments.

    Returns:
        AzureToolResponse with success, content, is_error fields.
    """
    return await call_azure_tool(request)
