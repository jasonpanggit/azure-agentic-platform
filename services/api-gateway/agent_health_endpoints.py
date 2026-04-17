"""Phase 70: Agent Health Monitor — FastAPI endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from services.api_gateway.agent_health import KNOWN_AGENTS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-health"])

_KNOWN_NAMES = {a["name"] for a in KNOWN_AGENTS}


def _get_monitor(request: Request) -> Any:
    monitor = getattr(request.app.state, "agent_health_monitor", None)
    return monitor


@router.get("/api/v1/agents/health")
async def list_agent_health(request: Request) -> Dict[str, Any]:
    """Return health status for all 9 domain agents."""
    monitor = _get_monitor(request)
    if monitor is None:
        # Return empty but valid response when monitor not initialised
        return {
            "agents": [],
            "total": 0,
            "healthy_count": 0,
            "degraded_count": 0,
            "offline_count": 0,
            "unknown_count": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    agents = monitor.get_all()
    healthy_count = sum(1 for a in agents if a.get("status") == "healthy")
    degraded_count = sum(1 for a in agents if a.get("status") == "degraded")
    offline_count = sum(1 for a in agents if a.get("status") == "offline")
    unknown_count = sum(1 for a in agents if a.get("status") == "unknown")

    return {
        "agents": agents,
        "total": len(agents),
        "healthy_count": healthy_count,
        "degraded_count": degraded_count,
        "offline_count": offline_count,
        "unknown_count": unknown_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/v1/agents/{name}/health")
async def get_agent_health(name: str, request: Request) -> Dict[str, Any]:
    """Return health status for a single agent."""
    if name not in _KNOWN_NAMES:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found in registry")

    monitor = _get_monitor(request)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Agent health monitor not initialised")

    record = monitor.get_one(name)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No health record for agent '{name}' yet")

    return record


@router.post("/api/v1/agents/{name}/check")
async def force_agent_check(name: str, request: Request) -> Dict[str, Any]:
    """Force an immediate health check for a specific agent and return updated record."""
    if name not in _KNOWN_NAMES:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found in registry")

    monitor = _get_monitor(request)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Agent health monitor not initialised")

    # Find agent config
    agent_cfg = next((a for a in KNOWN_AGENTS if a["name"] == name), None)
    if agent_cfg is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found in registry")

    try:
        record = await monitor.check_agent(agent_cfg)
        monitor._cache[name] = record
        # Persist async best-effort
        import asyncio
        asyncio.create_task(monitor._persist_record(record))
        return record.to_dict()
    except Exception as exc:
        logger.error("force_agent_check: error | name=%s error=%s", name, exc)
        raise HTTPException(status_code=500, detail=str(exc))
