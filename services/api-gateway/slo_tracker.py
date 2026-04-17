from __future__ import annotations
"""SLO Tracking Service — CRUD, error budget computation, and burn-rate alerting (INTEL-004).

Provides `create_slo`, `list_slos`, `get_slo_health`, `update_slo_metrics`, and
`check_domain_burn_rate_alert`. No HTTP routes — those are added in Plan 25-3.

Postgres DSN resolution is delegated to `resolve_postgres_dsn` from `runbook_rag`
so that all database configuration is managed in one place.
"""

import logging
import uuid
from typing import Optional

from services.api_gateway.runbook_rag import (
    RunbookSearchUnavailableError,
    resolve_postgres_dsn,
)

logger = logging.getLogger(__name__)

# Burn-rate alert thresholds — Google SRE Book, Chapter 5
BURN_RATE_1H_THRESHOLD = 2.0
BURN_RATE_15MIN_THRESHOLD = 3.0


class SLOTrackerUnavailableError(RuntimeError):
    """Raised when the SLO tracking database is unavailable."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_status(
    burn_rate_1h: Optional[float],
    burn_rate_15min: Optional[float],
    error_budget_pct: Optional[float],
) -> str:
    """Compute SLO status string from metric values. Pure function, no DB.

    Priority order:
        1. budget_exhausted  (error_budget_pct <= 0.0)
        2. burn_rate_alert   (burn_rate_1h > 2.0 OR burn_rate_15min > 3.0)
        3. healthy
    """
    if error_budget_pct is not None and error_budget_pct <= 0.0:
        return "budget_exhausted"
    if (burn_rate_1h or 0.0) > BURN_RATE_1H_THRESHOLD:
        return "burn_rate_alert"
    if (burn_rate_15min or 0.0) > BURN_RATE_15MIN_THRESHOLD:
        return "burn_rate_alert"
    return "healthy"


def _row_to_dict(row: object) -> dict:
    """Convert an asyncpg Record to a plain dict with ISO 8601 timestamps."""
    result = dict(row)
    for key in ("created_at", "updated_at"):
        if result.get(key) is not None:
            ts = result[key]
            result[key] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_slo(
    name: str,
    domain: str,
    metric: str,
    target_pct: float,
    window_hours: int,
) -> dict:
    """Insert a new SLO definition into the slo_definitions table.

    Returns:
        Full SLODefinition dict with generated UUID id and timestamps.

    Raises:
        SLOTrackerUnavailableError: if postgres is unreachable.
    """
    import asyncpg  # lazy import — keeps module importable without asyncpg installed

    slo_id = str(uuid.uuid4())
    dsn = resolve_postgres_dsn()

    conn = None
    try:
        conn = await asyncpg.connect(dsn)
        row = await conn.fetchrow(
            """
            INSERT INTO slo_definitions
                (id, name, domain, metric, target_pct, window_hours, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'healthy')
            RETURNING *
            """,
            slo_id,
            name,
            domain,
            metric,
            target_pct,
            window_hours,
        )
        return _row_to_dict(row)
    except RunbookSearchUnavailableError:
        raise
    except Exception as exc:
        raise SLOTrackerUnavailableError(
            f"SLO tracking database unavailable: {exc}"
        ) from exc
    finally:
        if conn is not None:
            await conn.close()


async def list_slos(domain: Optional[str] = None) -> list[dict]:
    """List all SLO definitions, optionally filtered by domain.

    Returns:
        List of SLODefinition dicts.

    Returns [] when postgres is not configured (non-fatal).
    """
    import asyncpg  # lazy import

    try:
        dsn = resolve_postgres_dsn()
    except RunbookSearchUnavailableError as exc:
        logger.warning("SLO list unavailable — postgres not configured: %s", exc)
        return []

    conn = None
    try:
        conn = await asyncpg.connect(dsn)
        if domain:
            rows = await conn.fetch(
                "SELECT * FROM slo_definitions WHERE domain = $1 ORDER BY name",
                domain,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM slo_definitions ORDER BY domain, name"
            )
        return [_row_to_dict(row) for row in rows]
    except SLOTrackerUnavailableError:
        logger.warning("SLO list unavailable — returning empty list")
        return []
    except Exception as exc:
        logger.warning("SLO list failed — returning empty list: %s", exc)
        return []
    finally:
        if conn is not None:
            await conn.close()


async def get_slo_health(slo_id: str) -> dict:
    """Get the current health snapshot for a single SLO.

    Returns:
        SLOHealth dict: slo_id, status, error_budget_pct, burn_rate_1h,
        burn_rate_15min, alert (bool)

    Raises:
        KeyError: if slo_id does not exist.
        SLOTrackerUnavailableError: if postgres is unreachable.
    """
    import asyncpg  # lazy import

    dsn = resolve_postgres_dsn()

    conn = None
    try:
        conn = await asyncpg.connect(dsn)
        row = await conn.fetchrow(
            "SELECT * FROM slo_definitions WHERE id = $1",
            slo_id,
        )
        if row is None:
            raise KeyError(slo_id)

        data = _row_to_dict(row)
        burn_rate_1h = data.get("burn_rate_1h")
        burn_rate_15min = data.get("burn_rate_15min")
        alert = (burn_rate_1h or 0) > BURN_RATE_1H_THRESHOLD or (
            burn_rate_15min or 0
        ) > BURN_RATE_15MIN_THRESHOLD

        return {
            "slo_id": slo_id,
            "status": data.get("status", "healthy"),
            "error_budget_pct": data.get("error_budget_pct"),
            "burn_rate_1h": burn_rate_1h,
            "burn_rate_15min": burn_rate_15min,
            "alert": alert,
        }
    except (KeyError, RunbookSearchUnavailableError):
        raise
    except Exception as exc:
        raise SLOTrackerUnavailableError(
            f"SLO tracking database unavailable: {exc}"
        ) from exc
    finally:
        if conn is not None:
            await conn.close()


async def update_slo_metrics(
    slo_id: str,
    current_value: float,
    burn_rate_1h: Optional[float] = None,
    burn_rate_15min: Optional[float] = None,
) -> dict:
    """Update the current metric value and recompute error budget + status.

    Error budget formula:
        error_budget_pct = (current_value / target_pct) * 100

    Status logic (applied in order):
        1. error_budget_pct <= 0.0 → 'budget_exhausted'
        2. burn_rate_1h > 2.0 OR burn_rate_15min > 3.0 → 'burn_rate_alert'
        3. else → 'healthy'

    Returns:
        Updated SLODefinition dict.

    Raises:
        KeyError: if slo_id does not exist.
        SLOTrackerUnavailableError: if postgres is unreachable.
    """
    import asyncpg  # lazy import

    dsn = resolve_postgres_dsn()

    conn = None
    try:
        conn = await asyncpg.connect(dsn)

        # Fetch current target_pct to compute error budget
        target_row = await conn.fetchrow(
            "SELECT target_pct FROM slo_definitions WHERE id = $1",
            slo_id,
        )
        if target_row is None:
            raise KeyError(slo_id)

        target_pct = float(target_row["target_pct"])
        error_budget_pct = (current_value / target_pct) * 100
        status = _compute_status(burn_rate_1h, burn_rate_15min, error_budget_pct)

        row = await conn.fetchrow(
            """
            UPDATE slo_definitions
            SET current_value    = $2,
                error_budget_pct = $3,
                burn_rate_1h     = $4,
                burn_rate_15min  = $5,
                status           = $6,
                updated_at       = NOW()
            WHERE id = $1
            RETURNING *
            """,
            slo_id,
            current_value,
            error_budget_pct,
            burn_rate_1h,
            burn_rate_15min,
            status,
        )
        return _row_to_dict(row)
    except (KeyError, RunbookSearchUnavailableError):
        raise
    except Exception as exc:
        raise SLOTrackerUnavailableError(
            f"SLO tracking database unavailable: {exc}"
        ) from exc
    finally:
        if conn is not None:
            await conn.close()


async def check_domain_burn_rate_alert(domain: str) -> bool:
    """Return True if ANY SLO for the given domain is in burn_rate_alert or budget_exhausted state.

    Used by ingest_incident to decide whether to escalate to Sev0 (INTEL-004).

    Returns:
        True  → domain has an active SLO burn-rate or budget alert.
        False → all SLOs healthy, or no SLOs defined, or postgres unavailable.

    Never raises — always returns bool (non-fatal for incident ingestion).
    """
    import asyncpg  # lazy import

    try:
        dsn = resolve_postgres_dsn()
        conn = None
        try:
            conn = await asyncpg.connect(dsn)
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS count
                FROM slo_definitions
                WHERE domain = $1
                  AND status IN ('burn_rate_alert', 'budget_exhausted')
                """,
                domain,
            )
            return int(row["count"]) > 0
        finally:
            if conn is not None:
                await conn.close()
    except Exception as exc:
        logger.warning(
            "check_domain_burn_rate_alert failed for domain=%s — returning False: %s",
            domain,
            exc,
        )
        return False
