"""CVE API endpoints for per-VM CVE tracking."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from services.api_gateway.auth import verify_token
from services.api_gateway.dependencies import get_credential

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vms", tags=["cve"])


@router.get("/{vm_name}/cves")
async def get_vm_cves(
    vm_name: str,
    subscription_id: str = Query(..., description="Azure subscription ID"),
    resource_group: str = Query(..., description="Resource group name"),
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return CVEs affecting a specific VM, correlated with patch status.

    Path param:
        vm_name: VM name.

    Query params:
        subscription_id: Azure subscription ID.
        resource_group: Resource group name.

    Returns:
        { cves: [...], total_count: int, vm_name: str }
    """
    start_time = time.monotonic()
    try:
        from services.api_gateway.cve_service import CVEService
        svc = CVEService(credential)
        records = await svc.get_cves_for_vm(vm_name, subscription_id, resource_group)
    except Exception as exc:
        logger.error("CVE fetch failed for %s: %s", vm_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CVE fetch failed: {exc}",
        )

    from dataclasses import asdict
    cve_list = [asdict(r) for r in records]

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /vms/%s/cves → %d CVEs (%.0fms)", vm_name, len(cve_list), duration_ms)

    return {
        "cves": cve_list,
        "total_count": len(cve_list),
        "vm_name": vm_name,
    }


@router.get("/{vm_name}/cves/stats")
async def get_vm_cve_stats(
    vm_name: str,
    subscription_id: str = Query(..., description="Azure subscription ID"),
    resource_group: str = Query(..., description="Resource group name"),
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
) -> Dict[str, Any]:
    """Return CVE count summary for a specific VM.

    Path param:
        vm_name: VM name.

    Query params:
        subscription_id: Azure subscription ID.
        resource_group: Resource group name.

    Returns:
        { total, critical, high, medium, low, patched_count, pending_count, unpatched_count, vm_name }
    """
    start_time = time.monotonic()
    try:
        from services.api_gateway.cve_service import CVEService
        svc = CVEService(credential)
        stats = await svc.get_cve_stats(vm_name, subscription_id, resource_group)
    except Exception as exc:
        logger.error("CVE stats failed for %s: %s", vm_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CVE stats failed: {exc}",
        )

    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info("GET /vms/%s/cves/stats → %s (%.0fms)", vm_name, stats, duration_ms)

    return {**stats, "vm_name": vm_name}
