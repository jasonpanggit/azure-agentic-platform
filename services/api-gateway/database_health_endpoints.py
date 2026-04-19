from __future__ import annotations
"""Database Health API endpoints — Phase 105.

GET  /api/v1/database/health        — list DB resources (Cosmos+PG+SQL), live ARG query
GET  /api/v1/database/health/summary — aggregate summary, live ARG query
GET  /api/v1/database/slow-queries  — slow query servers (PG + SQL) from ARG
GET  /api/v1/database/throughput    — throughput resources (Cosmos + SQL) from ARG

Data is queried live from Azure Resource Graph on every request (900s TTL cache).
No POST /scan route. No Cosmos DB intermediary.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from services.api_gateway.arg_cache import get_cached
from services.api_gateway.auth import verify_token
from services.api_gateway.database_health_service import scan_database_health
from services.api_gateway.federation import resolve_subscription_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/database", tags=["database-health"])


@router.get("/health")
async def list_database_health(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    db_type: Optional[str] = Query(None, description="Filter by type: cosmos, postgresql, sql"),
    health_status: Optional[str] = Query(None, description="Filter by health_status: healthy/stopped/failed/provisioning"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Return database health records queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)

    results = get_cached(
        key="database_health",
        subscription_ids=subscription_ids,
        ttl_seconds=900,
        fetch_fn=lambda: scan_database_health(subscription_ids),
    )

    if db_type:
        results = [r for r in results if r.get("db_type") == db_type]
    if health_status:
        results = [r for r in results if r.get("health_status") == health_status]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "database_health.list: total=%d db_type=%s health_status=%s duration_ms=%.0f",
        len(results), db_type, health_status, duration_ms,
    )
    return {"databases": results, "total": len(results)}


@router.get("/health/summary")
async def get_database_health_summary(
    request: Request,
    subscription_id: Optional[str] = Query(None),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Return aggregate summary of database health queried live from ARG (15m TTL cache)."""
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)

    results = get_cached(
        key="database_health",
        subscription_ids=subscription_ids,
        ttl_seconds=900,
        fetch_fn=lambda: scan_database_health(subscription_ids),
    )

    total = len(results)
    by_type: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for r in results:
        db_t = r.get("db_type", "unknown")
        status = r.get("health_status", "unknown")
        by_type[db_t] = by_type.get(db_t, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

    summary = {
        "total": total,
        "by_type": by_type,
        "by_status": by_status,
        "healthy_pct": round((by_status.get("healthy", 0) / total * 100) if total else 0, 1),
    }
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("database_health.summary: total=%d duration_ms=%.0f", total, duration_ms)
    return summary


@router.get("/slow-queries")
async def list_slow_queries(
    request: Request,
    subscription_id: Optional[str] = Query(None),
    db_type: Optional[str] = Query(None, description="Filter by type: postgresql, sql"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Return database resources that have slow-query diagnostics enabled (live ARG, 15m TTL).

    Returns the inventory of PG and SQL servers. The frontend uses this to:
    1. Show which databases have Log Analytics / slow query logging enabled
    2. Drive a "Query Details" chat panel via the Database agent

    Full slow-query log data requires Log Analytics workspace_id which is
    per-server — the Database agent's query_postgres_slow_queries and
    query_sql_query_store tools handle that on-demand via chat.
    """
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)

    results = get_cached(
        key="database_health",
        subscription_ids=subscription_ids,
        ttl_seconds=900,
        fetch_fn=lambda: scan_database_health(subscription_ids),
    )

    # Filter to PG and SQL only (Cosmos uses RU throttle, not slow queries)
    slow_query_types = {"postgresql", "sql"}
    filtered = [r for r in results if r.get("db_type") in slow_query_types]
    if db_type:
        filtered = [r for r in filtered if r.get("db_type") == db_type]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "database_health.slow_queries: total=%d db_type=%s duration_ms=%.0f",
        len(filtered), db_type, duration_ms,
    )
    return {"servers": filtered, "total": len(filtered)}


@router.get("/throughput")
async def list_throughput(
    request: Request,
    subscription_id: Optional[str] = Query(None),
    db_type: Optional[str] = Query(None, description="Filter by type: cosmos, sql"),
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Return Cosmos and SQL resources for throughput monitoring (live ARG, 15m TTL).

    Returns the inventory with resource IDs. The frontend uses this to:
    1. Display throughput-capable resources (Cosmos RU, SQL DTU/vCore)
    2. Drive "View Metrics" chat panel via the Database agent

    Real-time metric values require Azure Monitor calls — the Database agent's
    get_cosmos_throughput_metrics and get_sql_dtu_metrics handle that on-demand.
    """
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)

    results = get_cached(
        key="database_health",
        subscription_ids=subscription_ids,
        ttl_seconds=900,
        fetch_fn=lambda: scan_database_health(subscription_ids),
    )

    throughput_types = {"cosmos", "sql"}
    filtered = [r for r in results if r.get("db_type") in throughput_types]
    if db_type:
        filtered = [r for r in filtered if r.get("db_type") == db_type]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "database_health.throughput: total=%d db_type=%s duration_ms=%.0f",
        len(filtered), db_type, duration_ms,
    )
    return {"resources": filtered, "total": len(filtered)}
