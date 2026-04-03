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
from pydantic import BaseModel, Field

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
    ChangeCorrelation,
    ChatRequest,
    ChatResponse,
    ChatResultResponse,
    HealthResponse,
    HistoricalMatch,
    IncidentPayload,
    IncidentResponse,
    IncidentSummary,
    RunbookResult,
    SLOCreateRequest,
    SLODefinition,
    SLOHealth,
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
from services.api_gateway.change_correlator import correlate_incident_changes
from services.api_gateway.incident_memory import search_incident_memory, store_incident_memory
from services.api_gateway.slo_tracker import (
    check_domain_burn_rate_alert,
    create_slo,
    get_slo_health,
    list_slos,
)
from services.api_gateway.health import router as health_router
from services.api_gateway.patch_endpoints import router as patch_router
from services.api_gateway.vm_inventory import router as vm_inventory_router
from services.api_gateway.vm_detail import router as vm_detail_router
from services.api_gateway.vm_chat import router as vm_chat_router
from services.api_gateway.topology_endpoints import router as topology_router
from services.api_gateway.topology import TopologyClient, run_topology_sync_loop
from services.api_gateway.forecaster import (
    FORECAST_ENABLED,
    FORECAST_SWEEP_INTERVAL_SECONDS,
    ForecasterClient,
    run_forecast_sweep_loop,
)
from services.api_gateway.forecast_endpoints import router as forecast_router

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
            # incident_memory table (Phase 25 — INTEL-003)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_memory (
                    id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    resource_type TEXT,
                    title TEXT,
                    summary TEXT,
                    transcript TEXT,
                    resolution TEXT,
                    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    embedding VECTOR(1536)
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS incident_memory_embedding_idx "
                "ON incident_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);"
            )
            # slo_definitions table (Phase 25 — INTEL-004)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS slo_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    target_pct FLOAT NOT NULL,
                    window_hours INT NOT NULL,
                    current_value FLOAT,
                    error_budget_pct FLOAT,
                    burn_rate_1h FLOAT,
                    burn_rate_15min FLOAT,
                    status TEXT DEFAULT 'healthy',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS slo_definitions_domain_status_idx "
                "ON slo_definitions (domain, status);"
            )
            logger.info(
                "Startup migrations complete "
                "(pgvector + runbooks + eol_cache + incident_memory + slo_definitions)"
            )
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

    # Initialize ForecasterClient and start background sweep (INTEL-005)
    _forecast_sweep_task = None
    if app.state.cosmos_client is not None and FORECAST_ENABLED:
        app.state.forecaster_client = ForecasterClient(
            cosmos_client=app.state.cosmos_client,
            credential=app.state.credential,
        )
        _forecast_sweep_task = asyncio.create_task(
            run_forecast_sweep_loop(
                cosmos_client=app.state.cosmos_client,
                credential=app.state.credential,
                topology_client=app.state.topology_client,
            )
        )
        logger.info(
            "startup: forecast sweep loop started | interval=%ds",
            FORECAST_SWEEP_INTERVAL_SECONDS,
        )
    else:
        app.state.forecaster_client = None
        logger.warning(
            "startup: forecaster_client not initialized "
            "(COSMOS_ENDPOINT=%s, FORECAST_ENABLED=%s)",
            "set" if app.state.cosmos_client else "not_set",
            os.environ.get("FORECAST_ENABLED", "true"),
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
    # Cancel forecast sweep loop on shutdown
    if _forecast_sweep_task is not None and not _forecast_sweep_task.done():
        _forecast_sweep_task.cancel()
        try:
            await _forecast_sweep_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: forecast sweep loop cancelled")

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
app.include_router(forecast_router)

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


async def _attach_historical_matches(
    incident_id: str,
    title: Optional[str],
    domain: Optional[str],
    resource_type: Optional[str],
    cosmos_client: Any,
) -> None:
    """BackgroundTask: search incident_memory and attach top-3 matches to Cosmos doc.

    Non-fatal — logs warning and returns on any error. Must complete within 10s
    to satisfy INTEL-003 (historical match available before first agent triage response).
    """
    try:
        matches = await search_incident_memory(
            title=title,
            domain=domain,
            resource_type=resource_type,
            limit=3,
        )
        if not matches or cosmos_client is None:
            return

        db = cosmos_client.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")
        container.patch_item(
            item=incident_id,
            partition_key=incident_id,
            patch_operations=[
                {"op": "add", "path": "/historical_matches", "value": matches},
            ],
        )
        logger.info(
            "memory: attached %d historical match(es) | incident=%s",
            len(matches),
            incident_id,
        )
    except Exception as exc:
        logger.warning(
            "memory: attach failed (non-fatal) | incident=%s error=%s",
            incident_id,
            exc,
        )


@app.post(
    "/api/v1/incidents",
    response_model=IncidentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_incident(
    payload: IncidentPayload,
    request: Request,
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

    # topology_client resolved here so it is available for noise reduction (Phase 24),
    # BackgroundTask correlator, and the TOPO-004 blast-radius prefetch below.
    topology_client = getattr(request.app.state, "topology_client", None)

    # --- Phase 24: Noise reduction (INTEL-001) ---
    # Runs before dedup check. Precedence: suppression > correlation > dedup > new.
    from services.api_gateway.noise_reducer import (
        check_causal_suppression,
        check_temporal_topological_correlation,
        compute_composite_severity,
    )
    from datetime import datetime as _datetime, timezone as _timezone

    _primary_resource_id = (
        payload.affected_resources[0].resource_id if payload.affected_resources else ""
    )
    _composite_severity: Optional[str] = None

    # 0a. Pre-fetch blast_radius for suppression + severity scoring.
    _blast_radius_size = 0
    if topology_client is not None and _primary_resource_id:
        try:
            loop = asyncio.get_running_loop()
            _br = await loop.run_in_executor(
                None,
                topology_client.get_blast_radius,
                _primary_resource_id,
                3,
            )
            _blast_radius_size = _br.get("total_affected", 0)
        except Exception as _br_exc:
            logger.warning(
                "noise_reducer: blast_radius prefetch failed (non-fatal) | "
                "incident=%s error=%s",
                payload.incident_id, _br_exc,
            )

    # 0b. Causal suppression check.
    _suppressed_by: Optional[str] = await check_causal_suppression(
        resource_id=_primary_resource_id,
        topology_client=topology_client,
        cosmos_client=cosmos,
    )
    if _suppressed_by is not None:
        # Store suppressed incident to Cosmos (status=suppressed_cascade).
        if cosmos is not None:
            try:
                _db = cosmos.get_database_client(
                    os.environ.get("COSMOS_DB_NAME", "aap")
                )
                _cont = _db.get_container_client("incidents")
                _cont.upsert_item({
                    "id": payload.incident_id,
                    "incident_id": payload.incident_id,
                    "resource_id": _primary_resource_id,
                    "severity": payload.severity,
                    "domain": payload.domain,
                    "status": "suppressed_cascade",
                    "parent_incident_id": _suppressed_by,
                    "title": payload.title,
                    "created_at": _datetime.now(_timezone.utc).isoformat(),
                })
            except Exception as _sup_exc:
                logger.warning(
                    "noise_reducer: failed to persist suppressed incident | "
                    "incident=%s error=%s",
                    payload.incident_id, _sup_exc,
                )
        logger.info(
            "noise_reducer: suppressed | incident=%s parent=%s",
            payload.incident_id, _suppressed_by,
        )
        return IncidentResponse(
            thread_id="suppressed",
            status="suppressed_cascade",
            suppressed=True,
            parent_incident_id=_suppressed_by,
        )

    # 0c. Multi-dimensional correlation check.
    _correlated_with: Optional[str] = await check_temporal_topological_correlation(
        resource_id=_primary_resource_id,
        domain=payload.domain,
        topology_client=topology_client,
        cosmos_client=cosmos,
    )

    # 0d. Composite severity scoring.
    _composite_severity = compute_composite_severity(
        severity=payload.severity,
        blast_radius_size=_blast_radius_size,
        domain=payload.domain,
    )
    logger.info(
        "noise_reducer: composite_severity=%s blast_radius=%d | incident=%s",
        _composite_severity, _blast_radius_size, payload.incident_id,
    )
    # --- End Phase 24 noise reduction ---

    # --- Phase 25: SLO-aware escalation (INTEL-004) ---
    _slo_escalated: bool = False
    if _composite_severity != "Sev0":
        try:
            _domain_in_alert = await check_domain_burn_rate_alert(payload.domain)
            if _domain_in_alert:
                _composite_severity = "Sev0"
                _slo_escalated = True
                logger.info(
                    "slo_escalation: escalated to Sev0 | incident=%s domain=%s",
                    payload.incident_id,
                    payload.domain,
                )
        except Exception as _slo_exc:
            # Non-fatal: SLO check failure must not block incident ingestion
            logger.warning(
                "slo_escalation: check failed (non-fatal) | incident=%s error=%s",
                payload.incident_id,
                _slo_exc,
            )
    # --- End Phase 25 SLO escalation ---

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

    # Attach noise-reduction metadata to Cosmos incident doc (best-effort).
    # The dedup check may have already written the doc; patch_item enriches it.
    if cosmos is not None and _primary_resource_id:
        try:
            _db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
            _cont = _db.get_container_client("incidents")
            _cont.patch_item(
                item=payload.incident_id,
                partition_key=payload.incident_id,
                patch_operations=[
                    {"op": "add", "path": "/composite_severity", "value": _composite_severity},
                    {"op": "add", "path": "/correlated_with", "value": _correlated_with},
                    {"op": "add", "path": "/slo_escalated", "value": _slo_escalated},  # Phase 25
                ],
            )
        except Exception as _patch_exc:
            logger.debug(
                "noise_reducer: composite_severity patch skipped | incident=%s reason=%s",
                payload.incident_id, _patch_exc,
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

        # Queue change correlator as background task (INTEL-002: within 30 seconds)
        # Runs in parallel with diagnostic_pipeline — both are independent BackgroundTasks.
        # incident_created_at is not yet in payload; use current UTC time as proxy
        # (Fabric Activator fires within seconds of the event, so skew is negligible).
        _incident_created_at = _datetime.now(_timezone.utc)
        background_tasks.add_task(
            correlate_incident_changes,
            incident_id=payload.incident_id,
            resource_id=primary_resource,
            incident_created_at=_incident_created_at,
            credential=credential,
            cosmos_client=cosmos,
            topology_client=topology_client,
        )
        logger.info(
            "correlator: queued | incident_id=%s resource=%s",
            payload.incident_id, primary_resource,
        )

        # Queue historical incident memory search (INTEL-003: surface past patterns within 10s)
        background_tasks.add_task(
            _attach_historical_matches,
            incident_id=payload.incident_id,
            title=payload.title,
            domain=payload.domain,
            resource_type=(
                payload.affected_resources[0].resource_type
                if payload.affected_resources else None
            ),
            cosmos_client=cosmos,
        )
        logger.info(
            "memory: queued | incident_id=%s",
            payload.incident_id,
        )

    # TOPO-004: Pre-fetch topology blast-radius for primary affected resource.
    # Attach as blast_radius_summary to IncidentResponse so the Foundry thread
    # receives topology context at dispatch time without an extra API round-trip.
    # Gracefully degraded: if topology is unavailable, incident is still dispatched.
    blast_radius_summary = None
    if topology_client is not None and payload.affected_resources:
        primary_resource_id = payload.affected_resources[0].resource_id
        try:
            loop = asyncio.get_running_loop()
            blast_result = await loop.run_in_executor(
                None,
                topology_client.get_blast_radius,
                primary_resource_id,
                3,  # max_depth=3 is the standard triage depth
            )
            blast_radius_summary = {
                "resource_id": blast_result.get("resource_id"),
                "total_affected": blast_result.get("total_affected", 0),
                "affected_resources": blast_result.get("affected_resources", []),
                "hop_counts": blast_result.get("hop_counts", {}),
            }
            logger.info(
                "topology: blast_radius prefetch | incident=%s resource=%s affected=%d",
                payload.incident_id,
                primary_resource_id[:80],
                blast_result.get("total_affected", 0),
            )
        except Exception as exc:
            logger.warning(
                "topology: blast_radius prefetch failed (non-fatal) | incident=%s error=%s",
                payload.incident_id,
                exc,
            )

    return IncidentResponse(
        thread_id=result["thread_id"],
        status="dispatched",
        blast_radius_summary=blast_radius_summary,
        composite_severity=_composite_severity,
    )


@app.get("/api/v1/incidents/stats")
async def get_incident_stats(
    window_hours: int = 24,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> dict:
    """Noise reduction metrics for the INTEL-001 requirement.

    Queries the incidents container and returns counts for:
    - total: all incidents in the window
    - suppressed: status == 'suppressed_cascade'
    - correlated: status == 'correlated'
    - new: all other non-terminal statuses
    - noise_reduction_pct: (suppressed + correlated) / total * 100
    - window_hours: echo of input param

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Incident store not configured")

    import time as _time_mod
    cutoff_ts = int(_time_mod.time()) - (window_hours * 3600)

    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")

        query = (
            "SELECT c.status FROM c "
            "WHERE c._ts > @cutoff"
        )
        params = [{"name": "@cutoff", "value": cutoff_ts}]
        items = list(container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        ))

        total = len(items)
        suppressed = sum(1 for i in items if i.get("status") == "suppressed_cascade")
        correlated = sum(1 for i in items if i.get("status") == "correlated")
        noise_reduction_pct = (
            round((suppressed + correlated) / total * 100, 1) if total > 0 else 0.0
        )
        new_count = total - suppressed - correlated

        return {
            "total": total,
            "suppressed": suppressed,
            "correlated": correlated,
            "new": new_count,
            "noise_reduction_pct": noise_reduction_pct,
            "window_hours": window_hours,
        }
    except Exception as exc:
        logger.error("get_incident_stats: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Stats query failed")


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
    "/api/v1/incidents/{incident_id}/correlations",
    response_model=list[ChangeCorrelation],
)
async def get_incident_correlations(
    incident_id: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> list[ChangeCorrelation]:
    """Get change correlations for an incident (INTEL-002).

    Returns the top-3 ChangeCorrelation objects stored on the incident document.
    These are populated within 30 seconds of incident ingestion by the
    change_correlator BackgroundTask.

    Returns 200 with empty list if correlations have not yet been computed.
    Returns 404 if the incident itself does not exist.
    Returns 503 if Cosmos DB is not configured.

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Incident store not configured")
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")
        doc = container.read_item(incident_id, partition_key=incident_id)
        raw_changes = doc.get("top_changes") or []
        return [ChangeCorrelation(**c) for c in raw_changes]
    except Exception as exc:
        if "404" in str(exc) or "NotFound" in type(exc).__name__:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        logger.error(
            "get_incident_correlations: error | incident_id=%s error=%s",
            incident_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Correlations retrieval failed")


class ResolveIncidentRequest(BaseModel):
    """Request body for POST /api/v1/incidents/{incident_id}/resolve."""

    summary: str = Field(..., min_length=1, description="Operator-provided investigation summary")
    resolution: str = Field(..., min_length=1, description="What fixed the incident")


@app.post("/api/v1/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    payload: ResolveIncidentRequest,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> dict:
    """Mark an incident as resolved and store its embedding in incident_memory (INTEL-003).

    Reads the incident from Cosmos DB to retrieve domain, severity, resource_type,
    and title. Generates an embedding for the summary+resolution text and upserts
    into incident_memory. Updates Cosmos status to 'resolved'.

    Returns:
        { incident_id, memory_id, resolved_at }

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Incident store not configured")

    # Read incident from Cosmos
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DB_NAME", "aap"))
        container = db.get_container_client("incidents")
        doc = container.read_item(incident_id, partition_key=incident_id)
    except Exception as exc:
        if "404" in str(exc) or "NotFound" in type(exc).__name__:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        logger.error("resolve_incident: read failed | incident=%s error=%s", incident_id, exc)
        raise HTTPException(status_code=500, detail="Failed to read incident")

    domain = doc.get("domain", "")
    severity = doc.get("severity", "")
    resource_type = doc.get("resource_type")
    title = doc.get("title")

    # Store in incident_memory (embed + upsert)
    from services.api_gateway.incident_memory import IncidentMemoryUnavailableError

    try:
        memory_id = await store_incident_memory(
            incident_id=incident_id,
            domain=domain,
            severity=severity,
            resource_type=resource_type,
            title=title,
            summary=payload.summary,
            resolution=payload.resolution,
        )
    except IncidentMemoryUnavailableError as exc:
        logger.error(
            "resolve_incident: memory store unavailable | incident=%s error=%s",
            incident_id, exc,
        )
        raise HTTPException(status_code=503, detail="Incident memory store unavailable")

    # Update Cosmos status to 'resolved'
    from datetime import datetime as _datetime, timezone as _timezone
    _resolved_at = _datetime.now(_timezone.utc).isoformat()
    try:
        container.patch_item(
            item=incident_id,
            partition_key=incident_id,
            patch_operations=[
                {"op": "add", "path": "/status", "value": "resolved"},
                {"op": "add", "path": "/resolved_at", "value": _resolved_at},
                {"op": "add", "path": "/resolution", "value": payload.resolution},
                {"op": "add", "path": "/summary", "value": payload.summary},
            ],
        )
    except Exception as exc:
        # Memory was already stored — log but don't fail the request
        logger.warning(
            "resolve_incident: Cosmos status update failed (non-fatal) | "
            "incident=%s error=%s",
            incident_id, exc,
        )

    logger.info(
        "resolve_incident: complete | incident=%s memory_id=%s",
        incident_id, memory_id,
    )
    return {"incident_id": incident_id, "memory_id": memory_id, "resolved_at": _resolved_at}


@app.post("/api/v1/slos", response_model=SLODefinition, status_code=status.HTTP_201_CREATED)
async def create_slo_endpoint(
    payload: SLOCreateRequest,
    token: dict[str, Any] = Depends(verify_token),
) -> SLODefinition:
    """Create a new SLO definition (INTEL-004).

    Authentication: Entra ID Bearer token required.
    """
    from services.api_gateway.slo_tracker import SLOTrackerUnavailableError

    try:
        result = await create_slo(
            name=payload.name,
            domain=payload.domain,
            metric=payload.metric,
            target_pct=payload.target_pct,
            window_hours=payload.window_hours,
        )
    except SLOTrackerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return SLODefinition(**result)


@app.get("/api/v1/slos", response_model=list[SLODefinition])
async def list_slos_endpoint(
    domain: Optional[str] = None,
    token: dict[str, Any] = Depends(verify_token),
) -> list[SLODefinition]:
    """List SLO definitions, optionally filtered by domain (INTEL-004).

    Authentication: Entra ID Bearer token required.
    """
    results = await list_slos(domain=domain)
    return [SLODefinition(**r) for r in results]


@app.get("/api/v1/slos/{slo_id}/health", response_model=SLOHealth)
async def get_slo_health_endpoint(
    slo_id: str,
    token: dict[str, Any] = Depends(verify_token),
) -> SLOHealth:
    """Get the current health snapshot for a single SLO (INTEL-004).

    Authentication: Entra ID Bearer token required.
    """
    from services.api_gateway.slo_tracker import SLOTrackerUnavailableError

    try:
        result = await get_slo_health(slo_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"SLO {slo_id} not found")
    except SLOTrackerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return SLOHealth(**result)


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
