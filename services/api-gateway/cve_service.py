"""CVEService — fetch CVEs affecting VM OS/software, correlate with patch status.

Fetches CVEs via the existing msrc_client (KB → CVE mapping) and cross-references
with installed/pending patches to produce PATCHED / PENDING_PATCH / UNPATCHED status.
Results are cached in PostgreSQL cve_cache table with 24h TTL.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import asyncpg  # type: ignore[import]
except ImportError:
    asyncpg = None  # type: ignore[assignment,misc]

try:
    from azure.mgmt.resourcegraph import ResourceGraphClient  # type: ignore[import]
    from azure.mgmt.resourcegraph.models import QueryRequest  # type: ignore[import]
except ImportError:
    ResourceGraphClient = None  # type: ignore[assignment,misc]
    QueryRequest = None  # type: ignore[assignment,misc]

_KB_DIGITS_PATTERN = re.compile(r"\d+")
_CACHE_TTL_HOURS = 24


@dataclass
class CVERecord:
    cve_id: str
    description: str
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW
    cvss_score: Optional[float]
    affected_product: str
    affected_versions: str
    published_date: Optional[str]
    patched_kb_ids: List[str]
    patched_by_installed: bool
    patched_by_pending: bool
    status: str  # PATCHED | PENDING_PATCH | UNPATCHED


def _normalise_kb(kb_id: str) -> str:
    m = _KB_DIGITS_PATTERN.search(kb_id)
    return m.group() if m else kb_id.strip()


def _severity_from_cvss(score: Optional[float]) -> str:
    if score is None:
        return "MEDIUM"
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


def _extract_kbs_from_patches(patches: List[Dict[str, Any]]) -> List[str]:
    """Return list of normalised KB digit strings from a patch list."""
    kb_list: List[str] = []
    for p in patches:
        # Pending patch fields
        kbid = p.get("kbid") or p.get("KBId") or ""
        name = p.get("patchName") or p.get("SoftwareName") or ""
        if kbid:
            kb_list.append(_normalise_kb(str(kbid)))
        else:
            m = re.search(r"KB(\d+)", name, re.IGNORECASE)
            if m:
                kb_list.append(m.group(1))
    return kb_list


def _run_arg_query(credential: Any, subscription_ids: List[str], kql: str) -> List[Dict[str, Any]]:
    if ResourceGraphClient is None or QueryRequest is None:
        logger.warning("azure-mgmt-resourcegraph not installed")
        return []
    client = ResourceGraphClient(credential)
    request = QueryRequest(subscriptions=subscription_ids, query=kql)
    try:
        response = client.resources(request)
        return list(response.data)
    except Exception as exc:
        logger.warning("ARG query failed: %s", exc)
        return []


def _fetch_vm_os_version(credential: Any, vm_name: str, subscription_id: str) -> str:
    """Fetch VM OS version from ARG. Returns empty string on failure."""
    kql = (
        "resources\n"
        "| where type =~ 'microsoft.compute/virtualmachines'\n"
        f"   or type =~ 'microsoft.hybridcompute/machines'\n"
        f"| where name =~ '{vm_name}'\n"
        "| extend osVersion = coalesce(\n"
        "    tostring(properties.osSku),\n"
        "    tostring(properties.extended.instanceView.osName),\n"
        "    tostring(properties.osType)\n"
        "  )\n"
        "| project osVersion\n"
        "| limit 1"
    )
    rows = _run_arg_query(credential, [subscription_id], kql)
    if rows:
        return str(rows[0].get("osVersion", ""))
    return ""


def _fetch_pending_patches_arg(
    credential: Any, vm_name: str, subscription_id: str, resource_group: str
) -> List[Dict[str, Any]]:
    """Fetch pending patches from ARG patchassessmentresources."""
    # Build resource_id prefix for filtering
    rid_prefix = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/microsoft.compute/virtualmachines/{vm_name}"
    ).lower()
    kql = (
        "patchassessmentresources\n"
        "| where type == 'microsoft.compute/virtualmachines/patchassessmentresults/softwarepatches'\n"
        f"| where tolower(id) startswith '{rid_prefix}'\n"
        "| project patchName = tostring(properties.patchName),\n"
        "          kbid = tostring(properties.kbId)"
    )
    return _run_arg_query(credential, [subscription_id], kql)


async def _get_pg_connection() -> Optional[Any]:
    """Get a single asyncpg connection from env DSN. Returns None if unavailable."""
    if asyncpg is None:
        return None
    dsn = os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL") or ""
    if not dsn:
        return None
    try:
        conn = await asyncpg.connect(dsn, timeout=5)
        return conn
    except Exception as exc:
        logger.debug("PG connection failed (cache disabled): %s", exc)
        return None


async def _load_from_cache(vm_resource_id: str) -> Optional[List[Dict[str, Any]]]:
    conn = await _get_pg_connection()
    if conn is None:
        return None
    try:
        now = datetime.now(timezone.utc)
        row = await conn.fetchrow(
            "SELECT cve_data FROM cve_cache WHERE vm_resource_id = $1 AND expires_at > $2",
            vm_resource_id,
            now,
        )
        if row:
            data = row["cve_data"]
            return json.loads(data) if isinstance(data, str) else data
        return None
    except Exception as exc:
        logger.debug("Cache read failed: %s", exc)
        return None
    finally:
        await conn.close()


async def _save_to_cache(vm_resource_id: str, cve_data: List[Dict[str, Any]]) -> None:
    conn = await _get_pg_connection()
    if conn is None:
        return
    try:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=_CACHE_TTL_HOURS)
        await conn.execute(
            """
            INSERT INTO cve_cache (vm_resource_id, cve_data, expires_at)
            VALUES ($1, $2::jsonb, $3)
            ON CONFLICT DO NOTHING
            """,
            vm_resource_id,
            json.dumps(cve_data),
            expires_at,
        )
    except Exception as exc:
        logger.debug("Cache write failed: %s", exc)
    finally:
        await conn.close()


class CVEService:
    """Fetch and correlate CVEs for a VM against its patch state."""

    def __init__(self, credential: Any) -> None:
        self._credential = credential

    async def get_cves_for_vm(
        self, vm_name: str, subscription_id: str, resource_group: str
    ) -> List[CVERecord]:
        """Fetch CVEs for VM and correlate with patch status.

        Returns list of CVERecord. Never raises — returns empty list on error.
        """
        start_time = time.monotonic()
        vm_resource_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
        ).lower()

        # Check cache first
        cached = await _load_from_cache(vm_resource_id)
        if cached is not None:
            logger.debug("CVE cache hit for %s (%.0fms)", vm_name, (time.monotonic() - start_time) * 1000)
            return [CVERecord(**r) for r in cached]

        try:
            records = await self._fetch_and_correlate(vm_name, subscription_id, resource_group, vm_resource_id)
        except Exception as exc:
            logger.warning("CVE fetch failed for %s: %s", vm_name, exc)
            return []

        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info("CVE fetch for %s: %d CVEs (%.0fms)", vm_name, len(records), duration_ms)

        # Cache result asynchronously (fire-and-forget)
        if records:
            asyncio.ensure_future(
                _save_to_cache(vm_resource_id, [asdict(r) for r in records])
            )

        return records

    async def _fetch_and_correlate(
        self,
        vm_name: str,
        subscription_id: str,
        resource_group: str,
        vm_resource_id: str,
    ) -> List[CVERecord]:
        """Internal: fetch patches + CVEs, correlate, build CVERecord list."""
        loop = asyncio.get_running_loop()

        # Fetch pending patches from ARG (sync in executor)
        pending_patches = await loop.run_in_executor(
            None, _fetch_pending_patches_arg, self._credential, vm_name, subscription_id, resource_group
        )

        pending_kb_digits = set(_extract_kbs_from_patches(pending_patches))

        # Fetch installed patches from LAW (best-effort)
        installed_kb_digits: set[str] = set()
        try:
            installed_patches = await self._fetch_installed_patches(vm_resource_id)
            installed_kb_digits = set(_extract_kbs_from_patches(installed_patches))
        except Exception as exc:
            logger.debug("Installed patch fetch failed (degraded): %s", exc)

        # Build full KB set to look up CVEs
        all_kb_digits = pending_kb_digits | installed_kb_digits
        if not all_kb_digits:
            return []

        # Map KB digits -> CVEs via msrc_client
        kb_cve_map: Dict[str, List[str]] = {}
        try:
            from services.api_gateway.msrc_client import get_cves_for_kbs
            kb_ids = [f"KB{d}" for d in all_kb_digits]
            result = await get_cves_for_kbs(kb_ids)
            # Remap: result keys are "KB12345", we want "12345"
            for kb_id, cves in result.items():
                digits = _normalise_kb(kb_id)
                if digits:
                    kb_cve_map[digits] = cves
        except Exception as exc:
            logger.warning("MSRC CVE lookup failed (degraded): %s", exc)
            return []

        # Invert: CVE -> list of KB digits that patch it
        cve_to_kbs: Dict[str, List[str]] = {}
        for digits, cves in kb_cve_map.items():
            for cve in cves:
                cve_to_kbs.setdefault(cve, []).append(digits)

        records: List[CVERecord] = []
        for cve_id, kb_digits_list in cve_to_kbs.items():
            patched_by_installed = any(d in installed_kb_digits for d in kb_digits_list)
            patched_by_pending = any(d in pending_kb_digits for d in kb_digits_list)

            if patched_by_installed:
                status = "PATCHED"
            elif patched_by_pending:
                status = "PENDING_PATCH"
            else:
                status = "UNPATCHED"

            record = CVERecord(
                cve_id=cve_id,
                description=f"Vulnerability addressed by KB: {', '.join(f'KB{d}' for d in kb_digits_list)}",
                severity=_severity_from_cvss(None),
                cvss_score=None,
                affected_product="Windows",
                affected_versions="See MSRC for details",
                published_date=None,
                patched_kb_ids=[f"KB{d}" for d in kb_digits_list],
                patched_by_installed=patched_by_installed,
                patched_by_pending=patched_by_pending,
                status=status,
            )
            records.append(record)

        # Sort: UNPATCHED first, then PENDING_PATCH, then PATCHED
        status_order = {"UNPATCHED": 0, "PENDING_PATCH": 1, "PATCHED": 2}
        records.sort(key=lambda r: status_order.get(r.status, 3))
        return records

    async def _fetch_installed_patches(self, vm_resource_id: str) -> List[Dict[str, Any]]:
        """Fetch installed patches from Log Analytics (best-effort)."""
        try:
            from services.api_gateway.patch_endpoints import (
                _discover_change_tracking_workspace,
                _query_law_installed_detail,
            )
            loop = asyncio.get_running_loop()
            workspace_id = await loop.run_in_executor(
                None, _discover_change_tracking_workspace, self._credential, vm_resource_id
            )
            if not workspace_id:
                return []
            return await _query_law_installed_detail(self._credential, workspace_id, vm_resource_id, 90)
        except Exception as exc:
            logger.debug("Installed patch lookup failed: %s", exc)
            return []

    async def get_cve_stats(
        self, vm_name: str, subscription_id: str, resource_group: str
    ) -> Dict[str, Any]:
        """Return CVE count summary for a VM.

        Returns dict with total, critical, high, medium, low, patched_count,
        pending_count, unpatched_count. Never raises.
        """
        start_time = time.monotonic()
        try:
            records = await self.get_cves_for_vm(vm_name, subscription_id, resource_group)
        except Exception as exc:
            logger.warning("CVE stats failed for %s: %s", vm_name, exc)
            records = []

        stats = {
            "total": len(records),
            "critical": sum(1 for r in records if r.severity == "CRITICAL"),
            "high": sum(1 for r in records if r.severity == "HIGH"),
            "medium": sum(1 for r in records if r.severity == "MEDIUM"),
            "low": sum(1 for r in records if r.severity == "LOW"),
            "patched_count": sum(1 for r in records if r.status == "PATCHED"),
            "pending_count": sum(1 for r in records if r.status == "PENDING_PATCH"),
            "unpatched_count": sum(1 for r in records if r.status == "UNPATCHED"),
        }
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.debug("CVE stats for %s: %s (%.0fms)", vm_name, stats, duration_ms)
        return stats
