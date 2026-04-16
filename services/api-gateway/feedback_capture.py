"""FeedbackCapture — capture operator approve/reject decisions as training signal."""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import asyncpg
    _ASYNCPG_IMPORT_ERROR: str = ""
except Exception as _e:
    asyncpg = None  # type: ignore[assignment]
    _ASYNCPG_IMPORT_ERROR = str(_e)


def _log_sdk_availability() -> None:
    if _ASYNCPG_IMPORT_ERROR:
        logger.warning("feedback_capture: asyncpg unavailable: %s", _ASYNCPG_IMPORT_ERROR)
    else:
        logger.debug("feedback_capture: asyncpg available")


_log_sdk_availability()


# ---------------------------------------------------------------------------
# FeedbackRecord — Pydantic model
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel, Field

    class FeedbackRecord(BaseModel):
        """Operator feedback record written to eval_feedback table."""

        feedback_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        incident_id: str
        action_type: str  # 'approve' | 'reject' | 'resolved' | 'degraded'
        operator_id: Optional[str] = None
        agent_response_summary: Optional[str] = None
        operator_decision: Optional[str] = None
        verification_outcome: Optional[str] = None  # 'RESOLVED' | 'DEGRADED' | 'UNKNOWN'
        response_quality_score: Optional[float] = None  # 0.0–1.0
        sop_id: Optional[str] = None
        created_at: str = Field(
            default_factory=lambda: datetime.now(timezone.utc).isoformat()
        )

except Exception:
    FeedbackRecord = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_postgres_dsn() -> str:
    """Resolve PostgreSQL DSN from environment variables.

    Priority: PGVECTOR_CONNECTION_STRING → POSTGRES_DSN → POSTGRES_HOST parts.
    Raises RuntimeError if not configured.
    """
    for env_var in ("PGVECTOR_CONNECTION_STRING", "POSTGRES_DSN"):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val

    host = os.environ.get("POSTGRES_HOST", "").strip()
    if not host:
        raise RuntimeError(
            "PostgreSQL not configured: set PGVECTOR_CONNECTION_STRING, POSTGRES_DSN, or POSTGRES_HOST"
        )

    user = os.environ.get("POSTGRES_USER", "aap_admin")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    database = os.environ.get("POSTGRES_DATABASE", "aap")
    port = os.environ.get("POSTGRES_PORT", "5432")
    ssl = os.environ.get("POSTGRES_SSL", "require")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={ssl}"


# ---------------------------------------------------------------------------
# FeedbackCaptureService
# ---------------------------------------------------------------------------

class FeedbackCaptureService:
    """Writes operator feedback to eval_feedback table and computes quality metrics."""

    def __init__(self, pool: Any = None) -> None:
        self._pool = pool  # asyncpg connection pool; None = unavailable

    @classmethod
    async def create(cls) -> "FeedbackCaptureService":
        """Factory: create service with asyncpg pool.

        Returns service with pool=None if asyncpg/postgres unavailable (non-fatal).
        """
        if asyncpg is None:
            logger.warning("feedback_capture: asyncpg not available — running in no-op mode")
            return cls(pool=None)
        try:
            dsn = _resolve_postgres_dsn()
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
            return cls(pool=pool)
        except Exception as exc:
            logger.warning("feedback_capture: failed to create pool (non-fatal): %s", exc)
            return cls(pool=None)

    async def record_feedback(self, feedback: Any) -> None:
        """Write a FeedbackRecord to the eval_feedback table.

        Non-fatal — logs warning on failure, never raises.
        """
        if self._pool is None:
            logger.debug("feedback_capture: pool unavailable — skipping record_feedback")
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO eval_feedback (
                        feedback_id, incident_id, action_type, operator_id,
                        agent_response_summary, operator_decision,
                        verification_outcome, response_quality_score,
                        sop_id, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (feedback_id) DO NOTHING
                    """,
                    feedback.feedback_id,
                    feedback.incident_id,
                    feedback.action_type,
                    feedback.operator_id,
                    feedback.agent_response_summary,
                    feedback.operator_decision,
                    feedback.verification_outcome,
                    feedback.response_quality_score,
                    feedback.sop_id,
                    datetime.fromisoformat(feedback.created_at),
                )
        except Exception as exc:
            logger.warning("feedback_capture: record_feedback failed (non-fatal): %s", exc)

    async def compute_sop_effectiveness(
        self, sop_id: str, days: int = 30
    ) -> Dict[str, Any]:
        """Compute fraction of incidents where cited SOP led to RESOLVED within MTTR window.

        Args:
            sop_id: SOP identifier.
            days: Lookback window in days.

        Returns:
            Dict with sop_id, total_incidents, resolved_count, effectiveness_score, window_days.
            Never raises — returns error dict on failure.
        """
        start_time = time.monotonic()
        if self._pool is None:
            return {
                "sop_id": sop_id,
                "error": "database unavailable",
                "total_incidents": 0,
                "resolved_count": 0,
                "effectiveness_score": 0.0,
                "window_days": days,
            }
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT verification_outcome, created_at
                    FROM eval_feedback
                    WHERE sop_id = $1
                      AND created_at >= $2
                    ORDER BY created_at DESC
                    """,
                    sop_id,
                    cutoff,
                )

            total = len(rows)
            resolved = sum(
                1 for r in rows if r["verification_outcome"] == "RESOLVED"
            )
            score = round(resolved / total, 4) if total > 0 else 0.0

            return {
                "sop_id": sop_id,
                "total_incidents": total,
                "resolved_count": resolved,
                "effectiveness_score": score,
                "window_days": days,
                "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
            }
        except Exception as exc:
            logger.warning("feedback_capture: compute_sop_effectiveness error: %s", exc)
            return {
                "sop_id": sop_id,
                "error": str(exc),
                "total_incidents": 0,
                "resolved_count": 0,
                "effectiveness_score": 0.0,
                "window_days": days,
            }

    async def get_quality_metrics(self) -> Dict[str, Any]:
        """Return platform-level quality metrics.

        Returns:
            Dict with mttr_p50_min, mttr_p95_min, auto_remediation_rate, noise_ratio,
            sop_count_scored, avg_sop_effectiveness.
            Never raises — returns fallback zeros on failure.
        """
        start_time = time.monotonic()
        if self._pool is None:
            return {
                "mttr_p50_min": None,
                "mttr_p95_min": None,
                "auto_remediation_rate": None,
                "noise_ratio": None,
                "sop_count_scored": 0,
                "avg_sop_effectiveness": None,
                "error": "database unavailable",
            }
        try:
            async with self._pool.acquire() as conn:
                # MTTR: use records with action_type='approve' paired with 'resolved'
                # Approximation: time between first approve and resolved for same incident
                mttr_rows = await conn.fetch(
                    """
                    WITH resolved AS (
                        SELECT incident_id, MIN(created_at) AS resolved_at
                        FROM eval_feedback
                        WHERE action_type = 'resolved'
                        GROUP BY incident_id
                    ),
                    approved AS (
                        SELECT incident_id, MIN(created_at) AS approved_at
                        FROM eval_feedback
                        WHERE action_type = 'approve'
                        GROUP BY incident_id
                    )
                    SELECT EXTRACT(EPOCH FROM (r.resolved_at - a.approved_at)) / 60 AS mttr_min
                    FROM resolved r
                    JOIN approved a ON r.incident_id = a.incident_id
                    WHERE r.resolved_at > a.approved_at
                    ORDER BY mttr_min
                    """
                )

                mttr_values = [
                    float(r["mttr_min"]) for r in mttr_rows if r["mttr_min"] is not None
                ]
                mttr_p50 = _percentile(mttr_values, 50)
                mttr_p95 = _percentile(mttr_values, 95)

                # Auto-remediation rate: approve actions / (approve + reject)
                ar_row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE action_type = 'approve') AS approvals,
                        COUNT(*) FILTER (WHERE action_type = 'reject') AS rejections
                    FROM eval_feedback
                    WHERE action_type IN ('approve', 'reject')
                      AND created_at >= NOW() - INTERVAL '30 days'
                    """
                )
                total_decisions = (ar_row["approvals"] or 0) + (ar_row["rejections"] or 0)
                auto_rate = (
                    round(ar_row["approvals"] / total_decisions, 4)
                    if total_decisions > 0
                    else None
                )

                # Noise ratio: reject / total decisions
                noise = (
                    round(ar_row["rejections"] / total_decisions, 4)
                    if total_decisions > 0
                    else None
                )

                # SOP effectiveness aggregates
                sop_row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(DISTINCT sop_id) FILTER (WHERE sop_id IS NOT NULL) AS sop_count,
                        AVG(
                            CASE WHEN verification_outcome = 'RESOLVED' THEN 1.0 ELSE 0.0 END
                        ) FILTER (WHERE sop_id IS NOT NULL) AS avg_effectiveness
                    FROM eval_feedback
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                    """
                )

                return {
                    "mttr_p50_min": round(mttr_p50, 1) if mttr_p50 is not None else None,
                    "mttr_p95_min": round(mttr_p95, 1) if mttr_p95 is not None else None,
                    "auto_remediation_rate": auto_rate,
                    "noise_ratio": noise,
                    "sop_count_scored": sop_row["sop_count"] or 0,
                    "avg_sop_effectiveness": (
                        round(float(sop_row["avg_effectiveness"]), 4)
                        if sop_row["avg_effectiveness"] is not None
                        else None
                    ),
                    "duration_ms": round((time.monotonic() - start_time) * 1000, 1),
                }
        except Exception as exc:
            logger.warning("feedback_capture: get_quality_metrics error: %s", exc)
            return {
                "mttr_p50_min": None,
                "mttr_p95_min": None,
                "auto_remediation_rate": None,
                "noise_ratio": None,
                "sop_count_scored": 0,
                "avg_sop_effectiveness": None,
                "error": str(exc),
            }

    async def list_recent_feedback(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent feedback records.

        Returns:
            List of feedback record dicts, most recent first.
            Never raises — returns empty list on failure.
        """
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT feedback_id, incident_id, action_type, operator_id,
                           agent_response_summary, operator_decision,
                           verification_outcome, response_quality_score,
                           sop_id, created_at
                    FROM eval_feedback
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("feedback_capture: list_recent_feedback error: %s", exc)
            return []

    async def list_sop_effectiveness(self, days: int = 30) -> List[Dict[str, Any]]:
        """Return effectiveness scores for all SOPs, sorted by score ASC (worst first).

        Returns:
            List of SOP effectiveness dicts.
            Never raises — returns empty list on failure.
        """
        if self._pool is None:
            return []
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        sop_id,
                        COUNT(*) AS total_incidents,
                        COUNT(*) FILTER (WHERE verification_outcome = 'RESOLVED') AS resolved_count,
                        ROUND(
                            COUNT(*) FILTER (WHERE verification_outcome = 'RESOLVED')::numeric
                            / NULLIF(COUNT(*), 0),
                            4
                        ) AS effectiveness_score
                    FROM eval_feedback
                    WHERE sop_id IS NOT NULL
                      AND created_at >= $1
                    GROUP BY sop_id
                    ORDER BY effectiveness_score ASC NULLS FIRST
                    """,
                    cutoff,
                )
            return [
                {
                    "sop_id": r["sop_id"],
                    "total_incidents": r["total_incidents"],
                    "resolved_count": r["resolved_count"],
                    "effectiveness_score": float(r["effectiveness_score"] or 0.0),
                    "window_days": days,
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("feedback_capture: list_sop_effectiveness error: %s", exc)
            return []

    async def close(self) -> None:
        """Close the asyncpg pool."""
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception as exc:
                logger.debug("feedback_capture: pool close error: %s", exc)


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------

def _percentile(values: List[float], pct: int) -> Optional[float]:
    """Compute a percentile from a sorted list. Returns None for empty lists."""
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = max(0, int(len(sorted_vals) * pct / 100) - 1)
    return sorted_vals[idx]
