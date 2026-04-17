"""Phase 70: Agent Health Monitor.

Monitors all 9 domain agents by polling their /health endpoints,
persists health records to Cosmos DB, and raises platform incidents
when agents go offline.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------

KNOWN_AGENTS: List[Dict[str, str]] = [
    {"name": "orchestrator", "container_app": "ca-orchestrator-prod", "env_var": "ORCHESTRATOR_ENDPOINT"},
    {"name": "compute",      "container_app": "ca-compute-prod",      "env_var": "COMPUTE_ENDPOINT"},
    {"name": "network",      "container_app": "ca-network-prod",      "env_var": "NETWORK_ENDPOINT"},
    {"name": "storage",      "container_app": "ca-storage-prod",      "env_var": "STORAGE_ENDPOINT"},
    {"name": "security",     "container_app": "ca-security-prod",     "env_var": "SECURITY_ENDPOINT"},
    {"name": "arc",          "container_app": "ca-arc-prod",          "env_var": "ARC_ENDPOINT"},
    {"name": "sre",          "container_app": "ca-sre-prod",          "env_var": "SRE_ENDPOINT"},
    {"name": "patch",        "container_app": "ca-patch-prod",        "env_var": "PATCH_ENDPOINT"},
    {"name": "eol",          "container_app": "ca-eol-prod",          "env_var": "EOL_ENDPOINT"},
]

COSMOS_AGENT_HEALTH_CONTAINER = "agent_health"
_HEALTH_CHECK_TIMEOUT_SECONDS = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AgentHealthRecord:
    name: str
    container_app: str
    status: str                   # "healthy" | "degraded" | "offline" | "unknown"
    last_checked: str             # ISO-8601
    last_healthy: Optional[str]
    consecutive_failures: int
    latency_ms: Optional[float]
    endpoint: str                 # resolved from env var or ""
    error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["id"] = self.name       # Cosmos document id
        return d

    @staticmethod
    def _status_from_failures(failures: int, endpoint: str) -> str:
        if not endpoint:
            return "unknown"
        if failures == 0:
            return "healthy"
        if failures < 3:
            return "degraded"
        return "offline"


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class AgentHealthMonitor:
    """Polls all known agents, caches results, persists to Cosmos."""

    def __init__(
        self,
        cosmos_client: Optional[Any],
        cosmos_database_name: str,
        incident_callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        self._cosmos_client = cosmos_client
        self._db_name = cosmos_database_name
        self._incident_callback = incident_callback
        # In-memory cache: name -> AgentHealthRecord
        self._cache: Dict[str, AgentHealthRecord] = {}
        self._container: Optional[Any] = None
        self._ensure_container_done = False

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_all(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._cache.values()]

    def get_one(self, name: str) -> Optional[Dict[str, Any]]:
        record = self._cache.get(name)
        return record.to_dict() if record else None

    # ------------------------------------------------------------------
    # Cosmos helpers
    # ------------------------------------------------------------------

    def _get_container(self) -> Optional[Any]:
        if self._container is not None:
            return self._container
        if self._cosmos_client is None:
            return None
        try:
            db = self._cosmos_client.get_database_client(self._db_name)
            try:
                db.create_container_if_not_exists(
                    id=COSMOS_AGENT_HEALTH_CONTAINER,
                    partition_key={"paths": ["/name"], "kind": "Hash"},
                    default_ttl=86400,
                )
            except Exception as exc:
                logger.debug("agent_health: container create (non-fatal) | error=%s", exc)
            self._container = db.get_container_client(COSMOS_AGENT_HEALTH_CONTAINER)
        except Exception as exc:
            logger.warning("agent_health: cannot get cosmos container | error=%s", exc)
        return self._container

    async def _persist_record(self, record: AgentHealthRecord) -> None:
        container = self._get_container()
        if container is None:
            return
        try:
            loop = asyncio.get_running_loop()
            doc = record.to_dict()
            await loop.run_in_executor(None, lambda: container.upsert_item(doc))
        except Exception as exc:
            logger.warning("agent_health: cosmos upsert failed (non-fatal) | name=%s error=%s", record.name, exc)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def check_agent(self, agent: Dict[str, str]) -> AgentHealthRecord:
        name = agent["name"]
        container_app = agent["container_app"]
        env_var = agent["env_var"]
        endpoint = os.environ.get(env_var, "")

        # Carry over previous state for consecutive_failures tracking
        previous = self._cache.get(name)
        prev_failures = previous.consecutive_failures if previous else 0
        prev_last_healthy = previous.last_healthy if previous else None

        if not endpoint:
            return AgentHealthRecord(
                name=name,
                container_app=container_app,
                status="unknown",
                last_checked=_now_iso(),
                last_healthy=prev_last_healthy,
                consecutive_failures=prev_failures,
                latency_ms=None,
                endpoint="",
                error="ENDPOINT env var not configured",
            )

        health_url = endpoint.rstrip("/") + "/health"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_CHECK_TIMEOUT_SECONDS) as client:
                response = await client.get(health_url)
            latency_ms = (time.monotonic() - start) * 1000

            if response.status_code == 200:
                new_failures = 0
                now = _now_iso()
                return AgentHealthRecord(
                    name=name,
                    container_app=container_app,
                    status="healthy",
                    last_checked=now,
                    last_healthy=now,
                    consecutive_failures=0,
                    latency_ms=round(latency_ms, 2),
                    endpoint=endpoint,
                    error=None,
                )
            else:
                new_failures = prev_failures + 1
                status = AgentHealthRecord._status_from_failures(new_failures, endpoint)
                return AgentHealthRecord(
                    name=name,
                    container_app=container_app,
                    status=status,
                    last_checked=_now_iso(),
                    last_healthy=prev_last_healthy,
                    consecutive_failures=new_failures,
                    latency_ms=round(latency_ms, 2),
                    endpoint=endpoint,
                    error=f"HTTP {response.status_code}",
                )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            new_failures = prev_failures + 1
            status = AgentHealthRecord._status_from_failures(new_failures, endpoint)
            return AgentHealthRecord(
                name=name,
                container_app=container_app,
                status=status,
                last_checked=_now_iso(),
                last_healthy=prev_last_healthy,
                consecutive_failures=new_failures,
                latency_ms=round(latency_ms, 2),
                endpoint=endpoint,
                error=str(exc),
            )

    async def check_all(self) -> List[AgentHealthRecord]:
        results = await asyncio.gather(
            *[self.check_agent(agent) for agent in KNOWN_AGENTS],
            return_exceptions=True,
        )
        records: List[AgentHealthRecord] = []
        for agent, result in zip(KNOWN_AGENTS, results):
            if isinstance(result, Exception):
                logger.error("agent_health: check_agent raised | name=%s error=%s", agent["name"], result)
                # Preserve previous or create degraded record
                prev = self._cache.get(agent["name"])
                if prev is not None:
                    records.append(prev)
            else:
                records.append(result)
        return records

    # ------------------------------------------------------------------
    # Incident logic
    # ------------------------------------------------------------------

    def _should_raise_incident(
        self,
        record: AgentHealthRecord,
        previous: Optional[AgentHealthRecord],
    ) -> bool:
        """True when transitioning to degraded (failures==3) or offline (failures==5)."""
        failures = record.consecutive_failures
        if failures not in (3, 5):
            return False
        # Only fire once per threshold (not on every subsequent check)
        if previous is None:
            return True
        return previous.consecutive_failures < failures

    async def _emit_incident(self, record: AgentHealthRecord) -> None:
        failures = record.consecutive_failures
        severity = "Sev0" if failures >= 5 else "Sev1"
        status_label = "offline" if failures >= 5 else "degraded"
        payload = {
            "incident_id": f"agent-{record.name}-{uuid4().hex[:8]}",
            "title": f"[PLATFORM] Agent {record.name} {status_label} — {failures} consecutive health check failures",
            "severity": severity,
            "domain": "platform",
            "source": "agent_health_monitor",
            "subscription_id": "",
            "status": "new",
            "detected_at": _now_iso(),
            "tags": {
                "agent": record.name,
                "container_app": record.container_app,
                "monitor": "agent_health",
            },
        }
        try:
            await self._incident_callback(payload)
        except Exception as exc:
            logger.error("agent_health: incident callback failed | name=%s error=%s", record.name, exc)

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run_health_loop(self, interval_seconds: int = 60) -> None:
        """Background loop: check → cache → persist → emit incidents.

        Never raises — logs all errors and continues.
        """
        while True:
            try:
                records = await self.check_all()
                for record in records:
                    previous = self._cache.get(record.name)
                    self._cache[record.name] = record

                    # Persist async (non-blocking best-effort)
                    asyncio.create_task(self._persist_record(record))

                    # Incident emission
                    if self._should_raise_incident(record, previous):
                        asyncio.create_task(self._emit_incident(record))

                healthy = sum(1 for r in records if r.status == "healthy")
                degraded = sum(1 for r in records if r.status == "degraded")
                offline = sum(1 for r in records if r.status == "offline")
                logger.info(
                    "agent_health: check complete | healthy=%d degraded=%d offline=%d",
                    healthy, degraded, offline,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("agent_health: loop error (non-fatal) | error=%s", exc)

            await asyncio.sleep(interval_seconds)
