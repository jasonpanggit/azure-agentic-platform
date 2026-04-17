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
from azure.core.exceptions import HttpResponseError
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
from services.api_gateway.audit_export import (
    generate_remediation_audit_export,
    generate_remediation_report,
)
from services.api_gateway.remediation_executor import (
    execute_remediation,
    run_wal_stale_monitor,
)
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
    ApprovalCreateRequest,
    ApprovalRecord,
    ApprovalResponse,
    AuditEntry,
    AuditExportResponse,
    AutoRemediationPolicy,
    AutoRemediationPolicyCreate,
    AutoRemediationPolicyUpdate,
    BusinessTier,
    BusinessTiersResponse,
    ChangeCorrelation,
    ChatRequest,
    ChatResponse,
    ChatResultResponse,
    HealthResponse,
    HistoricalMatch,
    IncidentPattern,
    IncidentPayload,
    IncidentResponse,
    IncidentSummary,
    PatternAnalysisResult,
    PlatformHealth,
    PolicyExecution,
    PolicySuggestion,
    RemediationAuditRecord,
    RemediationResult,
    RunbookResult,
    SLOCreateRequest,
    SLODefinition,
    SLOHealth,
)
from services.api_gateway.approvals import (
    create_approval,
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
from services.api_gateway.resources_inventory import router as resources_inventory_router
from services.api_gateway.topology_tree import router as topology_tree_router
from services.api_gateway.pattern_analyzer import (
    PATTERN_ANALYSIS_ENABLED,
    PATTERN_ANALYSIS_INTERVAL_SECONDS,
    analyze_patterns,
    run_pattern_analysis_loop,
)
from services.api_gateway.suggestion_engine import (
    SUGGESTION_SWEEP_INTERVAL_SECONDS,
    run_suggestion_sweep_loop,
)
from services.api_gateway.eol_endpoints import router as eol_router
from services.api_gateway.vm_cost import router as vm_cost_router
from services.api_gateway.finops_endpoints import router as finops_router
from services.api_gateway.vmss_endpoints import router as vmss_router
from services.api_gateway.aks_endpoints import router as aks_router
from services.api_gateway.subscription_registry import SubscriptionRegistry
from services.api_gateway.admin_endpoints import router as admin_router
from services.api_gateway.compliance_endpoints import router as compliance_router
from services.api_gateway.capacity_endpoints import router as capacity_router
from services.api_gateway.security_posture_endpoints import router as security_posture_router
from services.api_gateway.cve_endpoints import router as cve_router
from services.api_gateway.sla_endpoints import sla_router, admin_sla_router
from services.api_gateway.war_room import (
    get_or_create_war_room,
    add_annotation,
    update_presence,
    generate_handoff_summary,
    register_sse_queue,
    deregister_sse_queue,
)
from services.api_gateway.push_notifications import router as push_router
from services.api_gateway.push_notifications import send_push_to_all
from services.api_gateway.capacity_planner import (
    CAPACITY_SWEEP_ENABLED,
    CAPACITY_SWEEP_INTERVAL_SECONDS,
    run_capacity_sweep_loop,
)
from services.api_gateway.drift_endpoints import router as drift_router
from services.api_gateway.deployment_endpoints import router as deployment_router
from services.api_gateway.quality_endpoints import router as quality_router
from services.api_gateway.runbook_executor_endpoints import router as runbook_executor_router
from services.api_gateway.tenant_endpoints import router as tenant_router
from services.api_gateway.tenant_manager import TenantManager
from services.api_gateway.quota_endpoints import router as quota_router
from services.api_gateway.subscription_endpoints import router as subscription_mgmt_router
from services.api_gateway.simulation_endpoints import router as simulation_router
from services.api_gateway.agent_health import AgentHealthMonitor
from services.api_gateway.agent_health_endpoints import router as agent_health_router

# Configure root logger so all INFO+ messages appear in Container Apps log stream.
# Override level with LOG_LEVEL env var (e.g. LOG_LEVEL=DEBUG for verbose mode).
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

COSMOS_PATTERN_ANALYSIS_CONTAINER = os.environ.get(
    "COSMOS_PATTERN_ANALYSIS_CONTAINER", "pattern_analysis"
)
COSMOS_BUSINESS_TIERS_CONTAINER = os.environ.get(
    "COSMOS_BUSINESS_TIERS_CONTAINER", "business_tiers"
)


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
            # remediation_policies table (Phase 51 — Autonomous Remediation)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS remediation_policies (
                    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name                    TEXT NOT NULL UNIQUE,
                    description             TEXT,
                    action_class            TEXT NOT NULL,
                    resource_tag_filter     JSONB DEFAULT '{}',
                    max_blast_radius        INT DEFAULT 10,
                    max_daily_executions    INT DEFAULT 20,
                    require_slo_healthy     BOOLEAN DEFAULT true,
                    maintenance_window_exempt BOOLEAN DEFAULT false,
                    enabled                 BOOLEAN DEFAULT true,
                    created_at              TIMESTAMPTZ DEFAULT now(),
                    updated_at              TIMESTAMPTZ DEFAULT now()
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_remediation_policies_action_class "
                "ON remediation_policies (action_class, enabled);"
            )
            # sla_definitions table (Phase 55 — SLA Dashboard)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sla_definitions (
                    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name                    TEXT NOT NULL UNIQUE,
                    target_availability_pct NUMERIC(6,3) NOT NULL,
                    covered_resource_ids    TEXT[]          NOT NULL DEFAULT '{}',
                    measurement_period      TEXT            NOT NULL DEFAULT 'monthly',
                    customer_name           TEXT,
                    report_recipients       TEXT[]          NOT NULL DEFAULT '{}',
                    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
                    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
                    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sla_definitions_active "
                "ON sla_definitions (is_active);"
            )
            # compliance_mappings table (Phase 54 — Compliance Framework Mapping)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS compliance_mappings (
                    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    finding_type        TEXT NOT NULL,
                    defender_rule_id    TEXT,
                    display_name        TEXT NOT NULL,
                    description         TEXT,
                    cis_control_id      TEXT,
                    cis_title           TEXT,
                    nist_control_id     TEXT,
                    nist_title          TEXT,
                    asb_control_id      TEXT,
                    asb_title           TEXT,
                    severity            TEXT NOT NULL DEFAULT 'Medium',
                    remediation_sop_id  UUID,
                    created_at          TIMESTAMPTZ DEFAULT now(),
                    updated_at          TIMESTAMPTZ DEFAULT now()
                );
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_compliance_mappings_defender_rule_id "
                "ON compliance_mappings (defender_rule_id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_compliance_mappings_asb "
                "ON compliance_mappings (asb_control_id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_compliance_mappings_nist "
                "ON compliance_mappings (nist_control_id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_compliance_mappings_cis "
                "ON compliance_mappings (cis_control_id);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_compliance_mappings_finding_type "
                "ON compliance_mappings (finding_type);"
            )
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_compliance_mappings_unique_finding "
                "ON compliance_mappings (finding_type, COALESCE(defender_rule_id, display_name));"
            )
            # Seed compliance mappings (idempotent — ON CONFLICT DO NOTHING)
            # Load seed data from the canonical seed script via importlib (hyphenated filename).
            try:
                import importlib.util as _ilu  # noqa: PLC0415
                import os as _os  # noqa: PLC0415
                _repo_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__)))
                _seed_path = _os.path.join(_repo_root, "scripts", "seed-compliance-mappings.py")
                _spec = _ilu.spec_from_file_location("seed_compliance_mappings", _seed_path)
                _seed_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
                _spec.loader.exec_module(_seed_mod)  # type: ignore[union-attr]
                _CM = _seed_mod.COMPLIANCE_MAPPINGS
                _INSERT_SQL = _seed_mod.INSERT_SQL
                seeded = 0
                for _row in _CM:
                    await conn.execute(
                        _INSERT_SQL,
                        _row["finding_type"],
                        _row.get("defender_rule_id"),
                        _row["display_name"],
                        _row.get("description"),
                        _row.get("cis_control_id"),
                        _row.get("cis_title"),
                        _row.get("nist_control_id"),
                        _row.get("nist_title"),
                        _row.get("asb_control_id"),
                        _row.get("asb_title"),
                        _row.get("severity", "Medium"),
                    )
                    seeded += 1
                logger.info("Compliance mappings seeded: %d rows (idempotent)", seeded)
            except Exception as _seed_exc:  # noqa: BLE001
                logger.warning("Compliance mappings seed skipped: %s", _seed_exc)
            logger.info(
                "Startup migrations complete "
                "(pgvector + runbooks + eol_cache + incident_memory + slo_definitions "
                "+ remediation_policies + sla_definitions + compliance_mappings)"
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

    # Initialize SubscriptionRegistry — auto-discovers all accessible subscriptions via ARG
    app.state.subscription_registry = SubscriptionRegistry(
        credential=app.state.credential,
        cosmos_client=app.state.cosmos_client,
        cosmos_database_name=os.environ.get("COSMOS_DATABASE", "aap"),
    )
    try:
        await app.state.subscription_registry.full_sync()
    except Exception as _exc:
        logger.warning("startup: subscription_registry bootstrap failed (non-fatal) | error=%s", _exc)
    asyncio.create_task(
        app.state.subscription_registry.run_refresh_loop(interval_seconds=6 * 3600)
    )
    logger.info(
        "startup: subscription_registry initialized | subscriptions=%d",
        len(app.state.subscription_registry.get_all_ids()),
    )

    # Initialize TopologyClient and run bootstrap if Cosmos is configured (TOPO-001)
    _topology_sync_task = None
    # Prefer registry-discovered subscription IDs; fall back to SUBSCRIPTION_IDS env var
    _subscription_ids = app.state.subscription_registry.get_all_ids()
    if not _subscription_ids:
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

    # Start capacity planning daily sweep (Phase 57)
    if CAPACITY_SWEEP_ENABLED and app.state.cosmos_client is not None and _subscription_ids:
        asyncio.create_task(
            run_capacity_sweep_loop(
                cosmos_client=app.state.cosmos_client,
                credential=app.state.credential,
                subscription_ids=_subscription_ids,
                interval_seconds=CAPACITY_SWEEP_INTERVAL_SECONDS,
            )
        )
        logger.info("Capacity sweep task started (interval=%ds)", CAPACITY_SWEEP_INTERVAL_SECONDS)
    else:
        logger.info(
            "startup: capacity sweep not started "
            "(CAPACITY_SWEEP_ENABLED=%s, cosmos=%s, subscriptions=%d)",
            CAPACITY_SWEEP_ENABLED,
            "set" if app.state.cosmos_client else "not_set",
            len(_subscription_ids),
        )

    # Start WAL stale-monitor background task (REMEDI-011)
    _wal_monitor_task: Optional[asyncio.Task] = None
    if app.state.cosmos_client is not None:
        _wal_monitor_task = asyncio.create_task(
            run_wal_stale_monitor(app.state.cosmos_client)
        )
        logger.info("startup: WAL stale monitor started | interval=300s")
    else:
        logger.warning("startup: WAL stale monitor not started (COSMOS_ENDPOINT not set)")

    # Startup sweep for missed verifications (LOOP-001)
    from services.api_gateway.remediation_executor import run_missed_verification_sweep
    asyncio.create_task(run_missed_verification_sweep(
        cosmos_client=app.state.cosmos_client if hasattr(app.state, "cosmos_client") else None,
        credential=app.state.credential,
    ))
    logger.info("startup: missed verification sweep queued")

    # Seed default business tier if container is empty (PLATINT-004)
    if app.state.cosmos_client is not None:
        try:
            from datetime import datetime as _dt_seed, timezone as _tz_seed
            _bt_db = app.state.cosmos_client.get_database_client(
                os.environ.get("COSMOS_DATABASE", "aap")
            )
            _bt_container = _bt_db.get_container_client(COSMOS_BUSINESS_TIERS_CONTAINER)
            _bt_items = list(_bt_container.query_items(
                "SELECT c.id FROM c",
                enable_cross_partition_query=True,
                max_item_count=1,
            ))
            if not _bt_items:
                _now_iso = _dt_seed.now(_tz_seed.utc).isoformat()
                _bt_container.upsert_item({
                    "id": "default",
                    "tier_name": "default",
                    "monthly_revenue_usd": 0.0,
                    "resource_tags": {},
                    "created_at": _now_iso,
                    "updated_at": _now_iso,
                })
                logger.info("startup: seeded default business tier")
            else:
                logger.info("startup: business_tiers container already has %d item(s)", len(_bt_items))
        except Exception as exc:
            logger.warning("startup: business tier seeding failed (non-fatal) | error=%s", exc)

    # Start pattern analysis background loop (PLATINT-001)
    _pattern_analysis_task: Optional[asyncio.Task] = None
    if app.state.cosmos_client is not None and PATTERN_ANALYSIS_ENABLED:
        _pattern_analysis_task = asyncio.create_task(
            run_pattern_analysis_loop(
                cosmos_client=app.state.cosmos_client,
                interval_seconds=PATTERN_ANALYSIS_INTERVAL_SECONDS,
            )
        )
        logger.info(
            "startup: pattern analysis loop started | interval=%ds",
            PATTERN_ANALYSIS_INTERVAL_SECONDS,
        )
    else:
        logger.warning(
            "startup: pattern analysis loop not started "
            "(COSMOS_ENDPOINT=%s, PATTERN_ANALYSIS_ENABLED=%s)",
            "set" if app.state.cosmos_client else "not_set",
            os.environ.get("PATTERN_ANALYSIS_ENABLED", "true"),
        )

    # Start learning suggestion sweep loop (Phase 51)
    _suggestion_sweep_task: Optional[asyncio.Task] = None
    if app.state.cosmos_client is not None:
        _suggestion_sweep_task = asyncio.create_task(
            run_suggestion_sweep_loop(
                cosmos_client=app.state.cosmos_client,
                interval_seconds=SUGGESTION_SWEEP_INTERVAL_SECONDS,
            )
        )
        logger.info(
            "startup: suggestion sweep loop started | interval=%ds",
            SUGGESTION_SWEEP_INTERVAL_SECONDS,
        )
    else:
        logger.warning("startup: suggestion sweep loop not started (COSMOS_ENDPOINT not set)")

    # Initialize TenantManager (Phase 64 — multi-tenant gateway)
    try:
        from services.api_gateway.runbook_rag import resolve_postgres_dsn, RunbookSearchUnavailableError
        _tenant_dsn = resolve_postgres_dsn()
        app.state.tenant_manager = TenantManager(postgres_dsn=_tenant_dsn)
        logger.info("startup: TenantManager initialized")
    except Exception as _tm_exc:
        app.state.tenant_manager = TenantManager(postgres_dsn=None)
        logger.warning("startup: TenantManager initialized without DB (non-fatal) | error=%s", _tm_exc)

    # Phase 70: Agent Health Monitor
    async def _agent_health_incident_callback(payload: dict) -> None:
        """Best-effort incident injection from the agent health monitor."""
        try:
            # Resolve ingest_incident from the module at call time to avoid circular refs
            import services.api_gateway.main as _gw_main
            _fn = getattr(_gw_main, "ingest_incident", None)
            if _fn is not None:
                from services.api_gateway.models import IncidentPayload
                _inc = IncidentPayload(**{k: v for k, v in payload.items() if k in IncidentPayload.model_fields})
                await _fn(_inc)
        except Exception as _cb_exc:
            pass  # best-effort; log below is sufficient
        logger.info("agent_health: incident raised | title=%s", payload.get("title"))

    app.state.agent_health_monitor = AgentHealthMonitor(
        cosmos_client=app.state.cosmos_client,
        cosmos_database_name=os.environ.get("COSMOS_DATABASE", "aap"),
        incident_callback=_agent_health_incident_callback,
    )
    asyncio.create_task(
        app.state.agent_health_monitor.run_health_loop(interval_seconds=60)
    )
    logger.info("startup: agent_health_monitor started | interval=60s")

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
    # Cancel WAL stale monitor on shutdown
    if _wal_monitor_task is not None and not _wal_monitor_task.done():
        _wal_monitor_task.cancel()
        try:
            await _wal_monitor_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: WAL stale monitor cancelled")

    # Cancel pattern analysis loop on shutdown
    if _pattern_analysis_task is not None and not _pattern_analysis_task.done():
        _pattern_analysis_task.cancel()
        try:
            await _pattern_analysis_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: pattern analysis loop cancelled")

    # Cancel suggestion sweep loop on shutdown
    if _suggestion_sweep_task is not None and not _suggestion_sweep_task.done():
        _suggestion_sweep_task.cancel()
        try:
            await _suggestion_sweep_task
        except asyncio.CancelledError:
            pass
        logger.info("shutdown: suggestion sweep loop cancelled")

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
# vm_cost_router MUST be registered before vm_detail_router because
# vm_detail_router defines a wildcard path /{resource_id_base64} that would
# otherwise swallow the fixed /cost-summary path.
app.include_router(vm_cost_router)
app.include_router(finops_router)
app.include_router(vm_detail_router)
app.include_router(vm_chat_router)
app.include_router(topology_router)
app.include_router(forecast_router)
app.include_router(resources_inventory_router)
app.include_router(topology_tree_router)
app.include_router(eol_router)
app.include_router(vmss_router)
app.include_router(aks_router)
app.include_router(admin_router)
app.include_router(compliance_router)
app.include_router(capacity_router)
app.include_router(security_posture_router)
app.include_router(cve_router)
app.include_router(sla_router)
app.include_router(admin_sla_router)
app.include_router(push_router)
app.include_router(drift_router)
app.include_router(deployment_router)
app.include_router(quality_router)
app.include_router(runbook_executor_router)
app.include_router(tenant_router)
app.include_router(quota_router)
app.include_router(subscription_mgmt_router)
app.include_router(simulation_router)
app.include_router(agent_health_router)


@app.get("/api/v1/subscriptions", tags=["subscriptions"])
async def list_subscriptions(request: Request):
    """Return all discovered Azure subscriptions from the subscription registry.

    Returns subscriptions discovered at startup and refreshed every 6 hours.
    Returns empty list gracefully when registry not initialized or no subscriptions found.
    """
    registry = getattr(request.app.state, "subscription_registry", None)
    if registry is None:
        return {"subscriptions": []}
    return {"subscriptions": registry.get_all()}


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

    # Phase 56: Fire-and-forget push notification for P0/P1 incidents
    if payload.severity in ("Sev0", "P0", "Sev1", "P1"):
        _push_body = (
            payload.description[:100]
            if getattr(payload, "description", None)
            else "New incident requires attention"
        )
        asyncio.ensure_future(
            send_push_to_all(
                title=f"{payload.severity} Incident: {payload.title}",
                body=_push_body,
                url="/approvals",
                cosmos_client=cosmos,
            )
        )
        logger.info(
            "push: fire-and-forget dispatched | incident=%s severity=%s",
            payload.incident_id,
            payload.severity,
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


class WarRoomJoinRequest(BaseModel):
    display_name: str = ""
    role: str = "support"  # "lead" or "support"


class AnnotationRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4096)
    trace_event_id: Optional[str] = None
    display_name: str = ""


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
    status_code=status.HTTP_200_OK,
)
async def start_chat(
    payload: ChatRequest,
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> ChatResponse:
    """Start an operator-initiated chat conversation via the Foundry Responses API.

    The Responses API is synchronous — this endpoint blocks until the
    orchestrator agent produces a reply. The result is cached server-side
    so GET /api/v1/chat/{id}/result returns immediately on first poll.

    Authentication: Entra ID Bearer token required.
    """
    user_id = payload.user_id or token.get("sub", "unknown")
    logger.info("Chat request from user %s: %s", user_id, payload.message[:100])

    try:
        result = await create_chat_thread(payload, user_id, credential=credential)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Foundry dispatch unavailable: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Chat dispatch failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Foundry API error: {exc}",
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
            feedback_text=payload.feedback_text,
            feedback_tags=payload.feedback_tags,
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
            feedback_text=payload.feedback_text,
            feedback_tags=payload.feedback_tags,
            cosmos_client=cosmos_client,
        )
        return ApprovalResponse(approval_id=approval_id, status="rejected")
    except ValueError as exc:
        error_msg = str(exc)
        if error_msg == "expired":
            raise HTTPException(status_code=410, detail="Approval has expired")
        raise HTTPException(status_code=400, detail=error_msg)


@app.post(
    "/api/v1/approvals/{approval_id}/execute",
    response_model=RemediationResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_approval(
    approval_id: str,
    request: Request,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
    credential: Any = Depends(get_credential),
) -> RemediationResult:
    """Execute an approved remediation proposal (REMEDI-009, REMEDI-010, REMEDI-011, REMEDI-012).

    Pre-conditions:
      - approval_id must exist in the approvals container (404 if not)
      - approval status must be 'approved' (409 if pending/rejected/expired/executed)
      - approval must not be expired (410 if expired)

    Returns RemediationResult with execution_id and verification_scheduled=True.
    """
    from services.api_gateway.approvals import _get_approvals_container, _is_expired
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    # Read approval record via cross-partition query (only have approval_id)
    approvals_container = _get_approvals_container(cosmos_client=cosmos_client)
    try:
        records = list(approvals_container.query_items(
            query="SELECT * FROM c WHERE c.id = @approval_id",
            parameters=[{"name": "@approval_id", "value": approval_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        logger.error(
            "execute_approval: cosmos read failed | approval_id=%s error=%s", approval_id, exc
        )
        raise HTTPException(status_code=500, detail="Failed to read approval record")

    if not records:
        raise HTTPException(status_code=404, detail="Approval not found")

    approval_record = records[0]

    # Status guards
    if _is_expired(approval_record):
        raise HTTPException(status_code=410, detail="Approval has expired")

    if approval_record["status"] != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot execute approval in status: {approval_record['status']}. Must be 'approved'.",
        )

    # Resolve topology client from app state
    topology_client = getattr(request.app.state, "topology_client", None)

    try:
        result = await execute_remediation(
            approval_id=approval_id,
            credential=credential,
            cosmos_client=cosmos_client,
            topology_client=topology_client,
            approval_record=approval_record,
        )
    except Exception as exc:
        logger.error(
            "execute_approval: execution failed | approval_id=%s error=%s",
            approval_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Remediation execution failed")

    # Update approval status to "executed" (best-effort)
    try:
        approvals_container.patch_item(
            item=approval_id,
            partition_key=approval_record["thread_id"],
            patch_operations=[
                {"op": "add", "path": "/status", "value": "executed"},
                {"op": "add", "path": "/executed_at", "value": result.execution_id},
            ],
        )
    except Exception as exc:
        logger.warning(
            "execute_approval: approval status update failed (non-fatal) | approval_id=%s error=%s",
            approval_id, exc,
        )

    return result


@app.get(
    "/api/v1/approvals/{approval_id}/verification",
    response_model=RemediationAuditRecord,
)
async def get_verification_result(
    approval_id: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> RemediationAuditRecord:
    """Get the verification result for an executed remediation (REMEDI-009).

    Returns 202 with Retry-After: 60 if verification is still pending.
    Returns 404 if no execution record exists for this approval_id.
    """
    from services.api_gateway.remediation_executor import _get_remediation_audit_container

    container = _get_remediation_audit_container(cosmos_client)
    try:
        records = list(container.query_items(
            query="SELECT * FROM c WHERE c.approval_id = @approval_id",
            parameters=[{"name": "@approval_id", "value": approval_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        logger.error(
            "get_verification_result: cosmos query failed | approval_id=%s error=%s",
            approval_id, exc,
        )
        raise HTTPException(status_code=500, detail="Failed to query remediation audit")

    # Filter to primary execution record (not rollback)
    execution_records = [r for r in records if r.get("action_type") == "execute"]

    if not execution_records:
        raise HTTPException(
            status_code=404, detail="No execution record found for this approval"
        )

    record = execution_records[-1]  # most recent

    # Verification not yet complete
    if record.get("verification_result") is None:
        return JSONResponse(
            content={
                "execution_id": record["id"],
                "approval_id": approval_id,
                "verification_result": None,
                "status": "pending_verification",
            },
            status_code=202,
            headers={"Retry-After": "60"},
        )

    clean = {k: v for k, v in record.items() if not k.startswith("_")}
    return RemediationAuditRecord(**clean)


@app.post("/api/v1/approvals", response_model=ApprovalRecord)
async def create_approval_endpoint(
    body: ApprovalCreateRequest,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> ApprovalRecord:
    """Create a synthetic approval record for ops/demo use.

    Allows operators to inject a pending approval directly via the API gateway
    (which reaches Cosmos via private endpoint) without needing public Cosmos access.
    The resulting record is identical to one created by the agent's approval_manager,
    so the UI ProposalCard renders it the same way.
    """
    record = await create_approval(
        thread_id=body.thread_id,
        incident_id=body.incident_id,
        agent_name=body.agent_name,
        proposal=body.proposal,
        resource_snapshot=body.resource_snapshot,
        risk_level=body.risk_level,
        timeout_minutes=body.timeout_minutes,
        cosmos_client=cosmos_client,
    )
    return ApprovalRecord(**{k: v for k, v in record.items() if not k.startswith("_")})


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


@app.get("/api/v1/audit/remediation-export", response_model=AuditExportResponse)
async def export_remediation_audit(
    from_time: str,
    to_time: str,
    token: dict[str, Any] = Depends(verify_token),
    cosmos_client: CosmosClient = Depends(get_cosmos_client),
) -> AuditExportResponse:
    """Export immutable remediation audit trail for compliance (REMEDI-013).

    Combines OneLake events + Cosmos approvals + Cosmos remediation_audit WAL records.
    """
    report = await generate_remediation_audit_export(
        from_time=from_time,
        to_time=to_time,
        cosmos_client=cosmos_client,
    )
    return AuditExportResponse(**report)


@app.get(
    "/api/v1/intelligence/patterns",
    response_model=PatternAnalysisResult,
)
async def get_pattern_analysis(
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> PatternAnalysisResult:
    """Get the most recent pattern analysis result (PLATINT-001).

    Returns the latest weekly analysis from the pattern_analysis container.
    Returns 404 if no analysis has been run yet.
    Returns 503 if Cosmos DB is not configured.

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Pattern analysis store not configured")
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DATABASE", "aap"))
        container = db.get_container_client(COSMOS_PATTERN_ANALYSIS_CONTAINER)
        # Get the most recent analysis by ordering analysis_date descending
        items = list(container.query_items(
            "SELECT * FROM c ORDER BY c.analysis_date DESC OFFSET 0 LIMIT 1",
            enable_cross_partition_query=True,
        ))
        if not items:
            raise HTTPException(status_code=404, detail="No pattern analysis available yet")
        clean = {k: v for k, v in items[0].items() if not k.startswith("_")}
        return PatternAnalysisResult(**clean)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_pattern_analysis: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Pattern analysis retrieval failed")


@app.get(
    "/api/v1/intelligence/platform-health",
    response_model=PlatformHealth,
)
async def get_platform_health(
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> PlatformHealth:
    """Aggregate platform-wide health metrics (PLATINT-004).

    Computes from existing data sources:
    - detection_pipeline_lag_seconds: age of most recent det- incident
    - auto_remediation_success_rate: complete/(complete+failed) from remediation_audit last 7d
    - noise_reduction_pct: suppressed_cascade/total incidents last 24h
    - slo_compliance_pct: healthy SLOs / total SLOs
    - automation_savings_count: complete remediation executions last 30d
    - agent_p50_ms, agent_p95_ms: None (deferred — requires App Insights query)
    - error_budget_portfolio: [{slo_id, error_budget_pct}] from slo_definitions

    Authentication: Entra ID Bearer token required.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    now = _dt.now(_tz.utc)
    now_iso = now.isoformat()

    detection_pipeline_lag_seconds: Optional[float] = None
    auto_remediation_success_rate: Optional[float] = None
    noise_reduction_pct: Optional[float] = None
    slo_compliance_pct: Optional[float] = None
    automation_savings_count: int = 0
    error_budget_portfolio: list[dict] = []

    if cosmos is not None:
        db_name = os.environ.get("COSMOS_DATABASE", "aap")
        db = cosmos.get_database_client(db_name)

        # 1. Detection pipeline lag: age of most recent det- incident
        try:
            incidents_container = db.get_container_client("incidents")
            det_items = list(incidents_container.query_items(
                "SELECT TOP 1 c.created_at FROM c WHERE STARTSWITH(c.incident_id, 'det-') ORDER BY c.created_at DESC",
                enable_cross_partition_query=True,
            ))
            if det_items and det_items[0].get("created_at"):
                last_det = _dt.fromisoformat(det_items[0]["created_at"])
                if last_det.tzinfo is None:
                    last_det = last_det.replace(tzinfo=_tz.utc)
                detection_pipeline_lag_seconds = (now - last_det).total_seconds()
        except Exception as exc:
            logger.debug("platform_health: detection lag query failed | error=%s", exc)

        # 2. Auto-remediation success rate (last 7 days)
        try:
            remediation_container = db.get_container_client("remediation_audit")
            cutoff_7d = (now - _td(days=7)).isoformat()
            rem_items = list(remediation_container.query_items(
                "SELECT c.status FROM c WHERE c.action_type = 'execute' AND c.executed_at >= @cutoff",
                parameters=[{"name": "@cutoff", "value": cutoff_7d}],
                enable_cross_partition_query=True,
            ))
            complete_count = sum(1 for r in rem_items if r.get("status") == "complete")
            failed_count = sum(1 for r in rem_items if r.get("status") == "failed")
            total_rem = complete_count + failed_count
            if total_rem > 0:
                auto_remediation_success_rate = round(complete_count / total_rem * 100, 1)
        except Exception as exc:
            logger.debug("platform_health: remediation rate query failed | error=%s", exc)

        # 3. Noise reduction percentage (last 24 hours)
        try:
            import time as _time_mod
            cutoff_ts = int(_time_mod.time()) - 86400
            noise_items = list(incidents_container.query_items(
                "SELECT c.status FROM c WHERE c._ts > @cutoff",
                parameters=[{"name": "@cutoff", "value": cutoff_ts}],
                enable_cross_partition_query=True,
            ))
            total_noise = len(noise_items)
            suppressed = sum(1 for i in noise_items if i.get("status") == "suppressed_cascade")
            if total_noise > 0:
                noise_reduction_pct = round(suppressed / total_noise * 100, 1)
        except Exception as exc:
            logger.debug("platform_health: noise reduction query failed | error=%s", exc)

        # 4. Automation savings count (last 30 days)
        try:
            cutoff_30d = (now - _td(days=30)).isoformat()
            savings_items = list(remediation_container.query_items(
                "SELECT c.id FROM c WHERE c.status = 'complete' AND c.action_type = 'execute' AND c.executed_at >= @cutoff",
                parameters=[{"name": "@cutoff", "value": cutoff_30d}],
                enable_cross_partition_query=True,
            ))
            automation_savings_count = len(savings_items)
        except Exception as exc:
            logger.debug("platform_health: automation savings query failed | error=%s", exc)

    # 5. SLO compliance + error budget portfolio (from PostgreSQL)
    try:
        slos = await list_slos()
        if slos:
            healthy_count = sum(1 for s in slos if s.get("status") == "healthy")
            slo_compliance_pct = round(healthy_count / len(slos) * 100, 1)
            error_budget_portfolio = [
                {"slo_id": s.get("id", ""), "error_budget_pct": s.get("error_budget_pct")}
                for s in slos
            ]
    except Exception as exc:
        logger.debug("platform_health: SLO compliance query failed | error=%s", exc)

    # 6. MTTR from latest pattern analysis (LOOP-003)
    mttr_p50 = None
    mttr_p95 = None
    mttr_by_type: dict = {}
    if cosmos is not None:
        try:
            db_name = os.environ.get("COSMOS_DATABASE", "aap")
            pattern_analysis_container = cosmos.get_database_client(db_name).get_container_client(
                COSMOS_PATTERN_ANALYSIS_CONTAINER
            )
            latest_results = list(
                pattern_analysis_container.query_items(
                    query="SELECT TOP 1 * FROM c ORDER BY c.generated_at DESC",
                    enable_cross_partition_query=True,
                )
            )
            latest_analysis = latest_results[0] if latest_results else {}
            if latest_analysis:
                mttr_summary = latest_analysis.get("mttr_summary", {})
                mttr_by_type = mttr_summary
                # Compute aggregate P50/P95 across all issue types
                # approximation: mean of per-issue-type P50s, not true population P50
                all_p50s = [v.get("p50_min", 0) for v in mttr_summary.values() if v.get("count", 0) > 0]
                all_p95s = [v.get("p95_min", 0) for v in mttr_summary.values() if v.get("count", 0) > 0]
                if all_p50s:
                    mttr_p50 = round(sum(all_p50s) / len(all_p50s), 1)
                if all_p95s:
                    mttr_p95 = round(max(all_p95s), 1)
        except Exception as exc:
            logger.debug("platform_health: MTTR query failed | error=%s", exc)

    return PlatformHealth(
        detection_pipeline_lag_seconds=detection_pipeline_lag_seconds,
        auto_remediation_success_rate=auto_remediation_success_rate,
        noise_reduction_pct=noise_reduction_pct,
        slo_compliance_pct=slo_compliance_pct,
        automation_savings_count=automation_savings_count,
        agent_p50_ms=None,
        agent_p95_ms=None,
        error_budget_portfolio=error_budget_portfolio,
        mttr_p50_minutes=mttr_p50,
        mttr_p95_minutes=mttr_p95,
        mttr_by_issue_type=mttr_by_type,
        generated_at=now_iso,
    )


@app.post(
    "/api/v1/admin/business-tiers",
    response_model=BusinessTier,
)
async def upsert_business_tier(
    payload: BusinessTier,
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> BusinessTier:
    """Create or update a business tier for FinOps cost impact tracking (PLATINT-004).

    Upserts by tier_name (id == tier_name). Requires admin-level Entra token.

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Business tier store not configured")
    try:
        from datetime import datetime as _dt, timezone as _tz
        now_iso = _dt.now(_tz.utc).isoformat()

        doc = payload.model_dump()
        doc["id"] = payload.tier_name  # Cosmos id = tier_name
        doc["updated_at"] = now_iso
        if not doc.get("created_at"):
            doc["created_at"] = now_iso

        db = cosmos.get_database_client(os.environ.get("COSMOS_DATABASE", "aap"))
        container = db.get_container_client(COSMOS_BUSINESS_TIERS_CONTAINER)
        container.upsert_item(doc)
        logger.info("business_tier: upserted | tier_name=%s", payload.tier_name)
        return BusinessTier(**doc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("upsert_business_tier: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Business tier upsert failed")


@app.get(
    "/api/v1/admin/business-tiers",
    response_model=BusinessTiersResponse,
)
async def list_business_tiers(
    token: dict[str, Any] = Depends(verify_token),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> BusinessTiersResponse:
    """List all configured business tiers (PLATINT-004).

    Authentication: Entra ID Bearer token required.
    """
    if cosmos is None:
        raise HTTPException(status_code=503, detail="Business tier store not configured")
    try:
        db = cosmos.get_database_client(os.environ.get("COSMOS_DATABASE", "aap"))
        container = db.get_container_client(COSMOS_BUSINESS_TIERS_CONTAINER)
        items = list(container.query_items(
            "SELECT * FROM c",
            enable_cross_partition_query=True,
        ))
        tiers = [
            BusinessTier(**{k: v for k, v in item.items() if not k.startswith("_")})
            for item in items
        ]
        return BusinessTiersResponse(tiers=tiers)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_business_tiers: error | error=%s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Business tier retrieval failed")


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


# ---------------------------------------------------------------------------
# War Room endpoints (Phase 53)
# ---------------------------------------------------------------------------

@app.post("/api/v1/incidents/{incident_id}/war-room")
async def create_or_join_war_room(
    incident_id: str,
    body: WarRoomJoinRequest,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    operator_id: str = token_claims.get("sub", "anonymous")
    display_name: str = body.display_name or token_claims.get("name", "")
    war_room = await get_or_create_war_room(
        incident_id=incident_id,
        operator_id=operator_id,
        display_name=display_name,
        role=body.role,
        cosmos_client=cosmos_client,
    )
    return {"ok": True, "war_room": war_room}


@app.post("/api/v1/incidents/{incident_id}/war-room/annotations")
async def post_annotation(
    incident_id: str,
    body: AnnotationRequest,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    operator_id: str = token_claims.get("sub", "anonymous")
    display_name: str = body.display_name or token_claims.get("name", "")
    annotation = await add_annotation(
        incident_id=incident_id,
        operator_id=operator_id,
        display_name=display_name,
        content=body.content,
        trace_event_id=body.trace_event_id,
        cosmos_client=cosmos_client,
    )
    return {"ok": True, "annotation": annotation}


@app.get("/api/v1/incidents/{incident_id}/war-room/stream")
async def war_room_sse_stream(
    incident_id: str,
    token_claims: dict = Depends(verify_token),
):
    """SSE endpoint — pushes annotation events to all connected participants."""
    import json
    from fastapi.responses import StreamingResponse

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    register_sse_queue(incident_id, queue)

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"event: annotation\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # 20-second heartbeat comment to prevent Container Apps 240s timeout
                    yield ": heartbeat\n\n"
        finally:
            deregister_sse_queue(incident_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/incidents/{incident_id}/war-room/heartbeat")
async def war_room_heartbeat(
    incident_id: str,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    operator_id: str = token_claims.get("sub", "anonymous")
    await update_presence(
        incident_id=incident_id,
        operator_id=operator_id,
        cosmos_client=cosmos_client,
    )
    return {"ok": True}


@app.post("/api/v1/incidents/{incident_id}/war-room/handoff")
async def generate_war_room_handoff(
    incident_id: str,
    token_claims: dict = Depends(verify_token),
    cosmos_client: Optional[CosmosClient] = Depends(get_optional_cosmos_client),
):
    try:
        summary = await generate_handoff_summary(
            incident_id=incident_id,
            cosmos_client=cosmos_client,
        )
        return {"ok": True, "summary": summary}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
