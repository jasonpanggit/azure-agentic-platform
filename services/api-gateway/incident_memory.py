from __future__ import annotations
"""Incident memory service — pgvector historical pattern matching (INTEL-003).

Embeds resolved incidents into the incident_memory table and searches
historical patterns for new incidents using cosine similarity.

generate_query_embedding and resolve_postgres_dsn are imported from
runbook_rag — no reimplementation.
"""
import os

import logging
import os
from typing import Optional

from services.api_gateway.runbook_rag import (
    RunbookSearchUnavailableError,
    generate_query_embedding,
    resolve_postgres_dsn,
)

logger = logging.getLogger(__name__)

MEMORY_SIMILARITY_THRESHOLD = float(os.environ.get("MEMORY_SIMILARITY_THRESHOLD", "0.35"))
MAX_RESOLUTION_EXCERPT_LENGTH = 300


class IncidentMemoryUnavailableError(RuntimeError):
    """Raised when the incident_memory data plane is unavailable (postgres missing or unreachable)."""


def _is_memory_data_plane_error(exc: Exception) -> bool:
    """Return True when the exception originates from the DB access layer."""
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return True
    module_name = exc.__class__.__module__
    return module_name.startswith("asyncpg") or module_name.startswith("pgvector")


async def store_incident_memory(
    incident_id: str,
    domain: str,
    severity: str,
    resource_type: Optional[str],
    title: Optional[str],
    summary: Optional[str],
    resolution: Optional[str],
) -> str:
    """Embed and upsert a resolved incident into the incident_memory table.

    Embedding text: "{title} {domain} {resource_type} {summary} {resolution}"
    Uses generate_query_embedding imported from runbook_rag (no duplication).

    Args:
        incident_id: Unique incident identifier (becomes the PRIMARY KEY).
        domain: Incident domain (compute, network, etc.).
        severity: Incident severity (Sev0–Sev3).
        resource_type: ARM resource type, may be None.
        title: Human-readable incident title, may be None.
        summary: Triage summary text, may be None.
        resolution: Resolution description, may be None.

    Returns:
        incident_id — the primary key stored.

    Raises:
        IncidentMemoryUnavailableError: if postgres is unreachable.
    """
    embed_text = (
        f"{title or ''} {domain} {resource_type or ''} {summary or ''} {resolution or ''}"
    ).strip()

    embedding = await generate_query_embedding(embed_text)

    dsn = resolve_postgres_dsn()

    import asyncpg
    from pgvector.asyncpg import register_vector

    conn = None
    try:
        conn = await asyncpg.connect(dsn)
        await register_vector(conn)

        await conn.execute(
            """
            INSERT INTO incident_memory
                (id, domain, severity, resource_type, title, summary, resolution, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                domain       = EXCLUDED.domain,
                severity     = EXCLUDED.severity,
                resource_type = EXCLUDED.resource_type,
                title        = EXCLUDED.title,
                summary      = EXCLUDED.summary,
                resolution   = EXCLUDED.resolution,
                embedding    = EXCLUDED.embedding,
                resolved_at  = NOW()
            """,
            incident_id,
            domain,
            severity,
            resource_type,
            title,
            summary,
            resolution,
            embedding,
        )
        return incident_id
    except Exception as exc:
        if _is_memory_data_plane_error(exc):
            logger.error("Incident memory store unavailable: %s", exc)
            raise IncidentMemoryUnavailableError(
                "Incident memory database is unavailable."
            ) from exc
        raise
    finally:
        if conn is not None:
            await conn.close()


async def search_incident_memory(
    title: Optional[str],
    domain: Optional[str],
    resource_type: Optional[str],
    limit: int = 3,
) -> list[dict]:
    """Search for historical incidents similar to the new incident.

    Query text: "{title} {domain} {resource_type}"
    Similarity threshold: MEMORY_SIMILARITY_THRESHOLD (default 0.35, env-overridable).

    Cross-domain search — no domain filter applied so a network issue that
    preceded a compute incident will still surface as a historical match.

    Args:
        title: Incident title text, may be None.
        domain: Incident domain hint, may be None.
        resource_type: ARM resource type, may be None.
        limit: Maximum rows to fetch from postgres before threshold filtering.

    Returns:
        List of dicts with keys:
            incident_id, domain, severity, title,
            similarity, resolution_excerpt, resolved_at

    Returns [] non-fatally when postgres is not configured or unavailable.
    Returns [] when the incident_memory table is empty.
    """
    query_text = f"{title or ''} {domain or ''} {resource_type or ''}".strip()
    if not query_text:
        return []

    try:
        dsn = resolve_postgres_dsn()
    except RunbookSearchUnavailableError as exc:
        logger.warning("Incident memory search skipped — postgres not configured: %s", exc)
        return []

    try:
        embedding = await generate_query_embedding(query_text)

        import asyncpg
        from pgvector.asyncpg import register_vector

        conn = None
        try:
            conn = await asyncpg.connect(dsn)
            await register_vector(conn)

            rows = await conn.fetch(
                """
                SELECT id, domain, severity, title, resolution, resolved_at,
                       1 - (embedding <=> $1) AS similarity
                FROM incident_memory
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                embedding,
                limit,
            )

            results = []
            for row in rows:
                sim = float(row["similarity"])
                if sim >= MEMORY_SIMILARITY_THRESHOLD:
                    resolved_at_val = row["resolved_at"]
                    resolved_at_str = (
                        resolved_at_val.isoformat()
                        if hasattr(resolved_at_val, "isoformat")
                        else str(resolved_at_val)
                    )
                    resolution = row["resolution"]
                    results.append({
                        "incident_id": str(row["id"]),
                        "domain": row["domain"],
                        "severity": row["severity"],
                        "title": row["title"],
                        "similarity": round(sim, 4),
                        "resolution_excerpt": (
                            resolution[:MAX_RESOLUTION_EXCERPT_LENGTH]
                            if resolution is not None
                            else None
                        ),
                        "resolved_at": resolved_at_str,
                    })
            return results
        except Exception as exc:
            if _is_memory_data_plane_error(exc):
                raise IncidentMemoryUnavailableError(
                    "Incident memory database is unavailable."
                ) from exc
            raise
        finally:
            if conn is not None:
                await conn.close()

    except IncidentMemoryUnavailableError as exc:
        logger.warning("Incident memory search unavailable (non-fatal): %s", exc)
        return []
