"""Simulation endpoints — Phase 69.

Provides a library of predefined incident scenarios that operators can trigger
to validate platform health, test alerting pipelines, and verify agent responses.

Endpoints:
- GET  /api/v1/simulations          — list all available scenarios
- POST /api/v1/simulations/run      — trigger a simulation
- GET  /api/v1/simulations/runs     — list run history
- GET  /api/v1/simulations/runs/{run_id} — get specific run details

All tool functions never raise — structured error dicts returned on failure.
Simulation incidents use the ``sim-`` prefix to distinguish them from real incidents.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.api_gateway.dependencies import get_credential, get_optional_cosmos_client

router = APIRouter(prefix="/api/v1/simulations", tags=["simulations"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scenario library
# ---------------------------------------------------------------------------

SIMULATION_SCENARIOS: List[dict] = [
    {
        "id": "vm-high-cpu",
        "name": "VM High CPU Alert",
        "description": "Simulates a VM exceeding 95% CPU for 30 minutes — tests compute agent triage",
        "domain": "compute",
        "severity": "Sev2",
        "expected_agent": "ca-compute-prod",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "detection_rule": "sim-vm-high-cpu",
    },
    {
        "id": "storage-latency",
        "name": "Storage Latency Spike",
        "description": "Simulates storage account end-to-end latency exceeding 1000ms — tests storage agent",
        "domain": "storage",
        "severity": "Sev2",
        "expected_agent": "ca-storage-prod",
        "resource_type": "Microsoft.Storage/storageAccounts",
        "detection_rule": "sim-storage-latency",
    },
    {
        "id": "nsg-blocked-traffic",
        "name": "NSG Blocked Traffic",
        "description": "Simulates excessive dropped packets on a network security group — tests network agent",
        "domain": "network",
        "severity": "Sev1",
        "expected_agent": "ca-network-prod",
        "resource_type": "Microsoft.Network/networkSecurityGroups",
        "detection_rule": "sim-nsg-blocked-traffic",
    },
    {
        "id": "vm-disk-full",
        "name": "VM Disk Full",
        "description": "Simulates OS disk reaching 95% capacity — tests compute agent disk remediation path",
        "domain": "compute",
        "severity": "Sev1",
        "expected_agent": "ca-compute-prod",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "detection_rule": "sim-vm-disk-full",
    },
    {
        "id": "keyvault-access-denied",
        "name": "Key Vault Access Denied",
        "description": "Simulates repeated unauthorized Key Vault access — tests security agent escalation",
        "domain": "security",
        "severity": "Sev1",
        "expected_agent": "ca-security-prod",
        "resource_type": "Microsoft.KeyVault/vaults",
        "detection_rule": "sim-keyvault-access-denied",
    },
    {
        "id": "arc-agent-offline",
        "name": "Arc Agent Offline",
        "description": "Simulates an Arc-enabled server going offline — tests Arc agent heartbeat detection",
        "domain": "arc",
        "severity": "Sev2",
        "expected_agent": "ca-arc-prod",
        "resource_type": "Microsoft.HybridCompute/machines",
        "detection_rule": "sim-arc-agent-offline",
    },
    {
        "id": "database-connection-pool",
        "name": "Database Connection Pool Exhausted",
        "description": "Simulates PostgreSQL connection pool at 100% — tests database agent triage",
        "domain": "storage",
        "severity": "Sev1",
        "expected_agent": "ca-storage-prod",
        "resource_type": "Microsoft.DBforPostgreSQL/flexibleServers",
        "detection_rule": "sim-database-connection-pool",
    },
    {
        "id": "aks-node-notready",
        "name": "AKS Node NotReady",
        "description": "Simulates an AKS node entering NotReady state — tests compute/network agent response",
        "domain": "compute",
        "severity": "Sev1",
        "expected_agent": "ca-compute-prod",
        "resource_type": "Microsoft.ContainerService/managedClusters",
        "detection_rule": "sim-aks-node-notready",
    },
    {
        "id": "sev0-cascade",
        "name": "Sev0 Multi-Domain Cascade",
        "description": "Simulates a Sev0 incident affecting compute + network + storage simultaneously — tests orchestrator fan-out",
        "domain": "compute",
        "severity": "Sev0",
        "expected_agent": "ca-orchestrator-prod",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "detection_rule": "sim-sev0-cascade",
    },
    {
        "id": "cost-anomaly",
        "name": "Cost Anomaly Spike",
        "description": "Simulates a 300% cost spike on a subscription — tests FinOps agent alerting",
        "domain": "finops",
        "severity": "Sev2",
        "expected_agent": "ca-finops-prod",
        "resource_type": "Microsoft.Billing/billingAccounts",
        "detection_rule": "sim-cost-anomaly",
    },
]

# Fast lookup by ID
_SCENARIO_INDEX: dict[str, dict] = {s["id"]: s for s in SIMULATION_SCENARIOS}

# ---------------------------------------------------------------------------
# Cosmos container name
# ---------------------------------------------------------------------------

_SIMULATION_RUNS_CONTAINER = "simulation_runs"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SimulationRunRequest(BaseModel):
    scenario_id: str = Field(..., description="Scenario ID to run")
    subscription_id: str = Field(..., description="Target Azure subscription ID")
    target_resource: Optional[str] = Field(default=None, description="Optional resource name override")
    resource_group: Optional[str] = Field(default=None, description="Optional resource group override")
    dry_run: bool = Field(default=False, description="If true, validates but does NOT inject incident")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_incident_payload(
    scenario: dict,
    subscription_id: str,
    target_resource: Optional[str],
    resource_group: Optional[str],
) -> dict:
    """Construct a realistic IncidentPayload-compatible dict for a scenario."""
    resource_name = target_resource or f"sim-resource-{scenario['domain']}-001"
    rg = resource_group or "rg-simulation"
    resource_type = scenario["resource_type"]
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{rg}"
        f"/providers/{resource_type}/{resource_name}"
    )
    incident_id = f"sim-{uuid.uuid4().hex[:8]}"
    return {
        "incident_id": incident_id,
        "title": f"[SIMULATION] {scenario['name']}",
        "description": f"Automated simulation: {scenario['description']}",
        "severity": scenario["severity"],
        "domain": scenario["domain"],
        "detection_rule": scenario["detection_rule"],
        "affected_resources": [
            {
                "resource_id": resource_id,
                "subscription_id": subscription_id,
                "resource_type": resource_type,
            }
        ],
        "kql_evidence": (
            f"// Simulation: {scenario['id']}\n"
            f"// Generated at {datetime.now(timezone.utc).isoformat()}"
        ),
    }


async def _persist_run(
    cosmos_client: Any,
    run_record: dict,
) -> None:
    """Persist a simulation run record to Cosmos DB (best-effort)."""
    if cosmos_client is None:
        return
    start_time = time.monotonic()
    try:
        db = cosmos_client.get_database_client("aap-db")
        try:
            from azure.cosmos.exceptions import CosmosResourceExistsError  # type: ignore[import]
            db.create_container(id=_SIMULATION_RUNS_CONTAINER, partition_key={"paths": ["/scenario_id"], "kind": "Hash"})
        except Exception:
            pass  # container already exists or unavailable — proceed
        container = db.get_container_client(_SIMULATION_RUNS_CONTAINER)
        # Use run_id as Cosmos id
        doc = {**run_record, "id": run_record["run_id"]}
        container.upsert_item(doc)
        duration_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.debug("simulation_run_persist: run_id=%s duration_ms=%s", run_record["run_id"], duration_ms)
    except Exception as exc:
        logger.warning("simulation_run_persist: failed | run_id=%s error=%s", run_record.get("run_id"), exc)


async def _query_runs(
    cosmos_client: Any,
    scenario_id: Optional[str],
    limit: int,
) -> List[dict]:
    """Query simulation run history from Cosmos DB."""
    if cosmos_client is None:
        return []
    try:
        db = cosmos_client.get_database_client("aap-db")
        container = db.get_container_client(_SIMULATION_RUNS_CONTAINER)
        if scenario_id:
            query = (
                "SELECT * FROM c WHERE c.scenario_id = @scenario_id "
                "ORDER BY c.triggered_at DESC OFFSET 0 LIMIT @limit"
            )
            params = [
                {"name": "@scenario_id", "value": scenario_id},
                {"name": "@limit", "value": limit},
            ]
        else:
            query = "SELECT * FROM c ORDER BY c.triggered_at DESC OFFSET 0 LIMIT @limit"
            params = [{"name": "@limit", "value": limit}]
        items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return items
    except Exception as exc:
        logger.warning("simulation_query_runs: error | scenario_id=%s error=%s", scenario_id, exc)
        return []


async def _get_run_by_id(cosmos_client: Any, run_id: str) -> Optional[dict]:
    """Fetch a single run record from Cosmos DB by run_id."""
    if cosmos_client is None:
        return None
    try:
        db = cosmos_client.get_database_client("aap-db")
        container = db.get_container_client(_SIMULATION_RUNS_CONTAINER)
        query = "SELECT * FROM c WHERE c.run_id = @run_id"
        params = [{"name": "@run_id", "value": run_id}]
        items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return items[0] if items else None
    except Exception as exc:
        logger.warning("simulation_get_run: error | run_id=%s error=%s", run_id, exc)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_scenarios(
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return all available simulation scenarios."""
    return {
        "scenarios": SIMULATION_SCENARIOS,
        "total": len(SIMULATION_SCENARIOS),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/run")
async def run_simulation(
    payload: SimulationRunRequest,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Trigger a simulation scenario.

    - dry_run=True  → validates scenario + builds payload, skips incident injection
    - dry_run=False → injects incident via POST /api/v1/incidents (internal call)
    """
    start_time = time.monotonic()

    scenario = _SCENARIO_INDEX.get(payload.scenario_id)
    if scenario is None:
        return JSONResponse(
            {"error": f"Unknown scenario_id: '{payload.scenario_id}'", "available": list(_SCENARIO_INDEX.keys())},
            status_code=404,
        )

    run_id = f"sim-{uuid.uuid4().hex[:12]}"
    triggered_at = datetime.now(timezone.utc).isoformat()

    incident_payload = _build_incident_payload(
        scenario,
        payload.subscription_id,
        payload.target_resource,
        payload.resource_group,
    )
    incident_id = incident_payload["incident_id"]

    status_val = "validated" if payload.dry_run else "triggered"
    actual_incident_id: Optional[str] = None

    if not payload.dry_run:
        # Inject the incident via internal HTTP to avoid circular import issues
        # with main.py's ingest_incident (which has many dependencies).
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "http://localhost:8000/api/v1/incidents",
                    json=incident_payload,
                )
                if resp.status_code in (200, 201, 202):
                    actual_incident_id = incident_id
                    status_val = "triggered"
                else:
                    logger.warning(
                        "simulation_run: incident injection returned %d | run_id=%s body=%s",
                        resp.status_code, run_id, resp.text[:200],
                    )
                    # Still record the run — incident injection may fail in test envs
                    actual_incident_id = incident_id
                    status_val = "injection_failed"
        except Exception as exc:
            logger.warning("simulation_run: incident injection error | run_id=%s error=%s", run_id, exc)
            actual_incident_id = incident_id
            status_val = "injection_failed"
    else:
        actual_incident_id = None

    run_record = {
        "run_id": run_id,
        "scenario_id": payload.scenario_id,
        "scenario_name": scenario["name"],
        "incident_id": actual_incident_id,
        "status": status_val,
        "triggered_at": triggered_at,
        "subscription_id": payload.subscription_id,
        "target_resource": payload.target_resource,
        "resource_group": payload.resource_group,
        "dry_run": payload.dry_run,
        "expected_agent": scenario["expected_agent"],
    }

    await _persist_run(cosmos_client, run_record)

    duration_ms = round((time.monotonic() - start_time) * 1000, 1)
    logger.info(
        "simulation_run: scenario=%s run_id=%s dry_run=%s status=%s duration_ms=%s",
        payload.scenario_id, run_id, payload.dry_run, status_val, duration_ms,
    )

    return {
        "run_id": run_id,
        "scenario_id": payload.scenario_id,
        "incident_id": actual_incident_id,
        "dry_run": payload.dry_run,
        "status": status_val,
        "triggered_at": triggered_at,
        "expected_agent": scenario["expected_agent"],
        "duration_ms": int(duration_ms),
    }


@router.get("/runs")
async def list_runs(
    scenario_id: Optional[str] = Query(default=None, description="Filter by scenario ID"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results to return"),
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return simulation run history, newest first."""
    start_time = time.monotonic()
    runs = await _query_runs(cosmos_client, scenario_id, limit)
    duration_ms = round((time.monotonic() - start_time) * 1000, 1)
    return {
        "runs": runs,
        "total": len(runs),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": int(duration_ms),
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    credential: Any = Depends(get_credential),
    cosmos_client: Any = Depends(get_optional_cosmos_client),
) -> Any:
    """Return details for a specific simulation run."""
    start_time = time.monotonic()
    run = await _get_run_by_id(cosmos_client, run_id)
    if run is None:
        return JSONResponse(
            {"error": f"Run not found: '{run_id}'"},
            status_code=404,
        )
    duration_ms = round((time.monotonic() - start_time) * 1000, 1)
    return {**run, "duration_ms": int(duration_ms)}
