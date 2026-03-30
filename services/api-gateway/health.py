"""Readiness health check for the API gateway (CONCERNS 5.1).

GET /health/ready — checks three required config dependencies:
  1. ORCHESTRATOR_AGENT_ID env var is set
  2. COSMOS_ENDPOINT env var is set (validates Cosmos connectivity config)
  3. AZURE_PROJECT_ENDPOINT (or FOUNDRY_ACCOUNT_ENDPOINT) is set

Returns 200 {"status": "ready", "checks": {...}} if all pass.
Returns 503 {"status": "not_ready", "checks": {...}} if any fail.

The existing /health (liveness) remains unchanged in main.py.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


def _run_readiness_checks() -> tuple[bool, dict[str, bool]]:
    """Run all readiness checks. Returns (all_passed, checks_dict)."""
    checks: dict[str, bool] = {}

    # Check 1: ORCHESTRATOR_AGENT_ID
    orchestrator_id = os.environ.get("ORCHESTRATOR_AGENT_ID", "").strip()
    checks["orchestrator_agent_id"] = bool(orchestrator_id)

    # Check 2: COSMOS_ENDPOINT
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "").strip()
    checks["cosmos"] = bool(cosmos_endpoint)

    # Check 3: Foundry endpoint (either name accepted)
    foundry_endpoint = (
        os.environ.get("AZURE_PROJECT_ENDPOINT", "").strip()
        or os.environ.get("FOUNDRY_ACCOUNT_ENDPOINT", "").strip()
    )
    checks["foundry"] = bool(foundry_endpoint)

    all_passed = all(checks.values())
    return all_passed, checks


@router.get("/health/ready")
async def health_ready() -> Any:
    """Readiness probe — checks required config deps are present.

    Returns 200 when all dependencies are configured.
    Returns 503 when any dependency is missing, with details.
    """
    all_passed, checks = _run_readiness_checks()

    status_str = "ready" if all_passed else "not_ready"
    status_code = 200 if all_passed else 503

    return JSONResponse(
        {"status": status_str, "checks": checks},
        status_code=status_code,
    )
