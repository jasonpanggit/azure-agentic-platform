"""EOL batch lookup endpoint for VM tab.

Accepts a list of OS names, checks the eol_cache PostgreSQL table
(with endoflife.date API fallback), and returns structured EOL data.

Does NOT import from agents/eol/tools.py — this is a standalone gateway
module following the same per-request asyncpg.connect() pattern as runbook_rag.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vms", tags=["vms"])

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class EolBatchRequest(BaseModel):
    os_names: list[str]


class EolResult(BaseModel):
    os_name: str
    eol_date: Optional[str] = None
    is_eol: Optional[bool] = None
    source: Optional[str] = None


class EolBatchResponse(BaseModel):
    results: list[EolResult]


# ---------------------------------------------------------------------------
# OS normalisation
# ---------------------------------------------------------------------------

_WINDOWS_SERVER_YEARS = [
    "2025",
    "2022",
    "2019",
    "2016",
    "2012 r2",
    "2012",
    "2008 r2",
    "2008",
]

# Ubuntu: "Ubuntu 22.04 LTS" -> ("ubuntu", "22.04")
_UBUNTU_RE = re.compile(r"ubuntu\s+(\d+\.\d+)", re.IGNORECASE)

# RHEL: "RHEL 9", "RHEL 8" -> ("rhel", "9")
_RHEL_RE = re.compile(r"rhel\s+(\d+)", re.IGNORECASE)

# SLES: "SLES 15" -> ("sles", "15")
_SLES_RE = re.compile(r"sles\s+(\d+)", re.IGNORECASE)

# Debian: "Debian 12" -> ("debian", "12")
_DEBIAN_RE = re.compile(r"debian\s+(\d+)", re.IGNORECASE)

# CentOS: "CentOS 8" -> ("centos", "8")
_CENTOS_RE = re.compile(r"centos\s+(\d+)", re.IGNORECASE)


def _parse_os_for_eol(os_name: str) -> tuple[str, str] | None:
    """Parse an OS display name into (product_slug, cycle) for endoflife.date.

    Product slugs must match the endoflife.date URL scheme exactly:
      https://endoflife.date/api/{product}/{cycle}.json

    Returns None for unrecognised OS names.
    """
    lower = os_name.lower()

    # Windows Server — slug is always "windows-server", cycle is the year
    # e.g. "Windows Server 2022 Datacenter" -> ("windows-server", "2022")
    for year in _WINDOWS_SERVER_YEARS:
        if f"windows server {year}" in lower:
            cycle = year.replace(" ", "-")
            return "windows-server", cycle

    # Ubuntu
    m = _UBUNTU_RE.search(os_name)
    if m:
        return "ubuntu", m.group(1)

    # RHEL
    m = _RHEL_RE.search(os_name)
    if m:
        return "rhel", m.group(1)

    # SLES
    m = _SLES_RE.search(os_name)
    if m:
        return "sles", m.group(1)

    # Debian
    m = _DEBIAN_RE.search(os_name)
    if m:
        return "debian", m.group(1)

    # CentOS
    m = _CENTOS_RE.search(os_name)
    if m:
        return "centos", m.group(1)

    return None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _resolve_dsn() -> str:
    """Re-use the same DSN resolution as runbook_rag (no cross-import)."""
    for env in ("PGVECTOR_CONNECTION_STRING", "POSTGRES_DSN"):
        val = os.environ.get(env, "").strip()
        if val:
            return val
    host = os.environ.get("POSTGRES_HOST", "").strip()
    if host:
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "aap")
        user = os.environ.get("POSTGRES_USER", "aap")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    raise RuntimeError(
        "PostgreSQL not configured — set PGVECTOR_CONNECTION_STRING, "
        "POSTGRES_DSN, or POSTGRES_HOST."
    )


async def _lookup_cache(
    conn, product: str, version: str
) -> dict | None:  # noqa: ANN001 — asyncpg.Connection
    """Query eol_cache for a non-expired row."""
    row = await conn.fetchrow(
        "SELECT eol_date, is_eol, source "
        "FROM eol_cache "
        "WHERE product = $1 AND version = $2 AND expires_at > now() "
        "LIMIT 1",
        product,
        version,
    )
    if row is None:
        return None
    eol_date_val = row["eol_date"]
    return {
        "eol_date": eol_date_val.isoformat() if eol_date_val else None,
        "is_eol": row["is_eol"],
        "source": row["source"],
    }


async def _fetch_from_api(product: str, cycle: str) -> dict | None:
    """GET https://endoflife.date/api/{product}/{cycle}.json — returns parsed result or None."""
    url = f"https://endoflife.date/api/{product}/{cycle}.json"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(url)
        duration_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            logger.debug(
                "endoflife.date: non-200 | url=%s status=%d duration_ms=%.0f",
                url,
                resp.status_code,
                duration_ms,
            )
            return None
        data = resp.json()
        eol_raw = data.get("eol")

        # eol can be a date string ("2026-10-14") or a boolean
        eol_date_str: str | None = None
        is_eol: bool = False

        if isinstance(eol_raw, bool):
            is_eol = eol_raw
        elif isinstance(eol_raw, str):
            try:
                eol_date_obj = date.fromisoformat(eol_raw)
                eol_date_str = eol_date_obj.isoformat()
                is_eol = eol_date_obj < date.today()
            except ValueError:
                pass

        logger.debug(
            "endoflife.date: fetched | product=%s cycle=%s eol=%s duration_ms=%.0f",
            product,
            cycle,
            eol_raw,
            duration_ms,
        )
        return {
            "eol_date": eol_date_str,
            "is_eol": is_eol,
            "source": "endoflife.date",
        }
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.warning(
            "endoflife.date: request failed | product=%s cycle=%s "
            "error=%s duration_ms=%.0f",
            product,
            cycle,
            exc,
            duration_ms,
        )
        return None


async def _upsert_cache(
    conn,  # noqa: ANN001
    product: str,
    version: str,
    eol_date_str: str | None,
    is_eol: bool,
    source: str,
) -> None:
    """Insert or update eol_cache with a 24h TTL."""
    eol_date_val: date | None = None
    if eol_date_str:
        try:
            eol_date_val = date.fromisoformat(eol_date_str)
        except ValueError:
            pass
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    try:
        await conn.execute(
            """
            INSERT INTO eol_cache (product, version, eol_date, is_eol, source, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (product, version, source)
            DO UPDATE SET eol_date = EXCLUDED.eol_date,
                          is_eol = EXCLUDED.is_eol,
                          expires_at = EXCLUDED.expires_at,
                          cached_at = now()
            """,
            product,
            version,
            eol_date_val,
            is_eol,
            source,
            expires_at,
        )
    except Exception as exc:
        logger.warning("eol_cache: upsert failed (non-fatal) | error=%s", exc)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/eol", response_model=EolBatchResponse)
async def batch_eol_lookup(payload: EolBatchRequest) -> EolBatchResponse:
    """Look up EOL dates for a batch of OS names.

    Returns structured results; unrecognised names return null fields.
    Tool function never raises — returns error-safe results.
    """
    start_time = time.monotonic()

    if not payload.os_names:
        return EolBatchResponse(results=[])

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_names: list[str] = []
    for name in payload.os_names:
        if name not in seen:
            seen.add(name)
            unique_names.append(name)

    results: list[EolResult] = []
    conn = None

    try:
        dsn = _resolve_dsn()
        conn = await asyncpg.connect(dsn)

        for os_name in unique_names:
            parsed = _parse_os_for_eol(os_name)
            if parsed is None:
                results.append(EolResult(os_name=os_name))
                continue

            product, cycle = parsed

            # Cache lookup
            cached = await _lookup_cache(conn, product, cycle)
            if cached is not None:
                results.append(
                    EolResult(
                        os_name=os_name,
                        eol_date=cached["eol_date"],
                        is_eol=cached["is_eol"],
                        source=cached["source"],
                    )
                )
                continue

            # Cache miss — fetch from endoflife.date
            api_result = await _fetch_from_api(product, cycle)
            if api_result is not None:
                await _upsert_cache(
                    conn,
                    product,
                    cycle,
                    api_result["eol_date"],
                    api_result["is_eol"],
                    api_result["source"],
                )
                results.append(
                    EolResult(
                        os_name=os_name,
                        eol_date=api_result["eol_date"],
                        is_eol=api_result["is_eol"],
                        source=api_result["source"],
                    )
                )
            else:
                # API also failed — return unknown
                results.append(EolResult(os_name=os_name))

    except Exception as exc:
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.error(
            "batch_eol_lookup: error | names=%d error=%s duration_ms=%.0f",
            len(unique_names),
            exc,
            duration_ms,
        )
        # Fill remaining results with unknowns — never raise
        already = {r.os_name for r in results}
        for os_name in unique_names:
            if os_name not in already:
                results.append(EolResult(os_name=os_name))
    finally:
        if conn is not None:
            await conn.close()

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "batch_eol_lookup: complete | names=%d results=%d duration_ms=%.0f",
        len(unique_names),
        len(results),
        duration_ms,
    )
    return EolBatchResponse(results=results)
