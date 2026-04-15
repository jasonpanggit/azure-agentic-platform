"""SLA Definition admin CRUD and compliance endpoints (Phase 55).

Provides:
  POST   /api/v1/admin/sla-definitions          — create SLA definition
  GET    /api/v1/admin/sla-definitions           — list SLA definitions
  GET    /api/v1/admin/sla-definitions/{sla_id}  — get single SLA definition
  PUT    /api/v1/admin/sla-definitions/{sla_id}  — update SLA definition
  DELETE /api/v1/admin/sla-definitions/{sla_id}  — soft delete SLA definition
  GET    /api/v1/sla/compliance                  — compute and return SLA compliance

All admin endpoints require Entra ID Bearer token via Depends(verify_token).
The compliance endpoint is public (no auth required).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Optional

import asyncpg
import asyncpg.exceptions as asyncpg_exc
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator

from services.api_gateway.auth import verify_token
from services.api_gateway.runbook_rag import resolve_postgres_dsn

# Azure Resource Health SDK — guarded import for environments without azure-mgmt-resourcehealth
try:
    from azure.mgmt.resourcehealth import ResourceHealthClient  # type: ignore[import]
except ImportError:
    ResourceHealthClient = None  # type: ignore[assignment,misc]

try:
    from azure.identity import DefaultAzureCredential  # type: ignore[import]
except ImportError:
    DefaultAzureCredential = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


def _log_sdk_availability() -> None:
    if ResourceHealthClient is None:
        logger.warning(
            "sla_endpoints: azure-mgmt-resourcehealth not installed — "
            "compliance calculation will use data_source='unavailable'"
        )
    if DefaultAzureCredential is None:
        logger.warning(
            "sla_endpoints: azure-identity not installed — "
            "compliance calculation will use data_source='unavailable'"
        )


_log_sdk_availability()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SLADefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    target_availability_pct: float = Field(
        ..., description="Target availability percentage, e.g. 99.9"
    )
    covered_resource_ids: List[str] = Field(default_factory=list)
    measurement_period: str = Field(default="monthly")
    customer_name: Optional[str] = None
    report_recipients: List[str] = Field(default_factory=list)

    @validator("target_availability_pct")
    def validate_target_pct(cls, v: float) -> float:  # noqa: N805
        if v <= 0.0 or v > 100.0:
            raise ValueError("target_availability_pct must be in (0.0, 100.0]")
        return v


class SLADefinitionUpdate(BaseModel):
    name: Optional[str] = None
    target_availability_pct: Optional[float] = None
    covered_resource_ids: Optional[List[str]] = None
    measurement_period: Optional[str] = None
    customer_name: Optional[str] = None
    report_recipients: Optional[List[str]] = None
    is_active: Optional[bool] = None

    @validator("target_availability_pct")
    def validate_target_pct(cls, v: Optional[float]) -> Optional[float]:  # noqa: N805
        if v is not None and (v <= 0.0 or v > 100.0):
            raise ValueError("target_availability_pct must be in (0.0, 100.0]")
        return v


class SLADefinitionResponse(BaseModel):
    id: str
    name: str
    target_availability_pct: float
    covered_resource_ids: List[str]
    measurement_period: str
    customer_name: Optional[str]
    report_recipients: List[str]
    is_active: bool
    created_at: str
    updated_at: str


class ResourceAttainment(BaseModel):
    resource_id: str
    availability_pct: Optional[float]
    downtime_minutes: float
    data_source: str  # "resource_health" | "unavailable"


class SLAComplianceResult(BaseModel):
    sla_id: str
    sla_name: str
    target_availability_pct: float
    attained_availability_pct: Optional[float]
    is_compliant: Optional[bool]
    period_start: str
    period_end: str
    resource_attainments: List[ResourceAttainment]
    duration_ms: float


class SLAComplianceResponse(BaseModel):
    results: List[SLAComplianceResult]
    computed_at: str


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

admin_sla_router = APIRouter(prefix="/api/v1/admin", tags=["admin-sla"])
sla_router = APIRouter(prefix="/api/v1/sla", tags=["sla"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_response(row: Any) -> dict:
    """Convert an asyncpg Record to a SLADefinitionResponse-compatible dict.

    Returns a new dict — never mutates the original row.
    """
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "target_availability_pct": float(row["target_availability_pct"]),
        "covered_resource_ids": list(row["covered_resource_ids"] or []),
        "measurement_period": row["measurement_period"],
        "customer_name": row["customer_name"],
        "report_recipients": list(row["report_recipients"] or []),
        "is_active": row["is_active"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
    }


async def _get_pg_connection() -> asyncpg.Connection:
    """Create a fresh PostgreSQL connection using the resolved DSN."""
    dsn = resolve_postgres_dsn()
    return await asyncpg.connect(dsn)


async def _calculate_compliance(sla_row: Any) -> SLAComplianceResult:
    """Calculate SLA compliance for a single SLA definition row.

    Uses Azure ResourceHealthClient to determine uptime for each covered resource.
    Never raises — all exceptions are caught and surfaced as data_source='unavailable'.
    """
    start_time = time.monotonic()

    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    period_end = now

    period_minutes = max(
        (period_end - period_start).total_seconds() / 60.0, 1.0
    )

    sla_id = str(sla_row["id"])
    sla_name = sla_row["name"]
    target_pct = float(sla_row["target_availability_pct"])
    covered_resource_ids: List[str] = list(sla_row["covered_resource_ids"] or [])

    resource_attainments: List[ResourceAttainment] = []

    for resource_id in covered_resource_ids:
        try:
            if ResourceHealthClient is None or DefaultAzureCredential is None:
                raise RuntimeError("azure-mgmt-resourcehealth or azure-identity not installed")

            credential = DefaultAzureCredential()

            # Extract subscription id from resource_id
            # Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/...
            sub_id = _extract_subscription_id(resource_id)
            client = ResourceHealthClient(credential=credential, subscription_id=sub_id)

            statuses = list(
                client.availability_statuses.list(resource_uri=resource_id)
            )

            downtime_minutes = 0.0
            for status_item in statuses:
                props = getattr(status_item, "properties", None)
                if props is None:
                    continue
                avail_state = getattr(props, "availability_state", None)
                if avail_state is None:
                    continue

                state_str = str(avail_state).lower()
                if state_str == "available":
                    # No downtime
                    pass
                elif state_str == "unavailable":
                    downtime_minutes += period_minutes
                elif state_str == "degraded":
                    downtime_minutes += period_minutes / 2.0
                # "unknown" — skip

            availability_pct = (
                (period_minutes - downtime_minutes) / period_minutes * 100.0
            )

            resource_attainments.append(
                ResourceAttainment(
                    resource_id=resource_id,
                    availability_pct=round(availability_pct, 4),
                    downtime_minutes=round(downtime_minutes, 4),
                    data_source="resource_health",
                )
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sla_compliance: resource health unavailable | sla=%s resource=%s error=%s",
                sla_id,
                resource_id,
                exc,
            )
            resource_attainments.append(
                ResourceAttainment(
                    resource_id=resource_id,
                    availability_pct=None,
                    downtime_minutes=0.0,
                    data_source="unavailable",
                )
            )

    # Aggregate: mean of non-None availability_pct values
    valid_pcts = [
        ra.availability_pct
        for ra in resource_attainments
        if ra.availability_pct is not None
    ]

    if valid_pcts:
        attained = round(sum(valid_pcts) / len(valid_pcts), 4)
        is_compliant = attained >= target_pct
    else:
        attained = None
        is_compliant = None

    duration_ms = (time.monotonic() - start_time) * 1000.0

    return SLAComplianceResult(
        sla_id=sla_id,
        sla_name=sla_name,
        target_availability_pct=target_pct,
        attained_availability_pct=attained,
        is_compliant=is_compliant,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        resource_attainments=resource_attainments,
        duration_ms=round(duration_ms, 2),
    )


def _extract_subscription_id(resource_id: str) -> str:
    """Extract subscription ID from an Azure resource ID string.

    Falls back to empty string if the format is unexpected.
    """
    parts = resource_id.split("/")
    try:
        idx = [p.lower() for p in parts].index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""


# ---------------------------------------------------------------------------
# Admin CRUD endpoints
# ---------------------------------------------------------------------------

@admin_sla_router.post(
    "/sla-definitions",
    response_model=SLADefinitionResponse,
    status_code=status.HTTP_200_OK,
    tags=["admin-sla"],
)
async def create_sla_definition(
    body: SLADefinitionCreate,
    _token: dict = Depends(verify_token),
) -> SLADefinitionResponse:
    """Create a new SLA definition."""
    try:
        conn = await _get_pg_connection()
    except Exception as exc:
        logger.error("sla_endpoints: PostgreSQL unavailable for create: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLA database unavailable",
        ) from exc

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO sla_definitions
                (name, target_availability_pct, covered_resource_ids,
                 measurement_period, customer_name, report_recipients)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            body.name,
            body.target_availability_pct,
            body.covered_resource_ids,
            body.measurement_period,
            body.customer_name,
            body.report_recipients,
        )
        return SLADefinitionResponse(**_row_to_response(row))
    except asyncpg_exc.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SLA definition with name '{body.name}' already exists",
        ) from exc
    finally:
        await conn.close()


@admin_sla_router.get(
    "/sla-definitions",
    response_model=dict,
    tags=["admin-sla"],
)
async def list_sla_definitions(
    include_inactive: bool = False,
    _token: dict = Depends(verify_token),
) -> dict:
    """List SLA definitions. By default returns only active (is_active=True) rows."""
    try:
        conn = await _get_pg_connection()
    except Exception as exc:
        logger.error("sla_endpoints: PostgreSQL unavailable for list: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLA database unavailable",
        ) from exc

    try:
        if include_inactive:
            rows = await conn.fetch(
                "SELECT * FROM sla_definitions ORDER BY created_at DESC"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM sla_definitions WHERE is_active = TRUE ORDER BY created_at DESC"
            )
        items = [_row_to_response(row) for row in rows]
        return {"items": items, "total": len(items)}
    finally:
        await conn.close()


@admin_sla_router.get(
    "/sla-definitions/{sla_id}",
    response_model=SLADefinitionResponse,
    tags=["admin-sla"],
)
async def get_sla_definition(
    sla_id: str,
    _token: dict = Depends(verify_token),
) -> SLADefinitionResponse:
    """Get a single SLA definition by UUID."""
    try:
        conn = await _get_pg_connection()
    except Exception as exc:
        logger.error("sla_endpoints: PostgreSQL unavailable for get: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLA database unavailable",
        ) from exc

    try:
        row = await conn.fetchrow(
            "SELECT * FROM sla_definitions WHERE id = $1::uuid",
            sla_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SLA definition {sla_id} not found",
            )
        return SLADefinitionResponse(**_row_to_response(row))
    finally:
        await conn.close()


@admin_sla_router.put(
    "/sla-definitions/{sla_id}",
    response_model=SLADefinitionResponse,
    tags=["admin-sla"],
)
async def update_sla_definition(
    sla_id: str,
    body: SLADefinitionUpdate,
    _token: dict = Depends(verify_token),
) -> SLADefinitionResponse:
    """Update an SLA definition. Only non-None fields are updated."""
    try:
        conn = await _get_pg_connection()
    except Exception as exc:
        logger.error("sla_endpoints: PostgreSQL unavailable for update: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLA database unavailable",
        ) from exc

    try:
        update_fields: dict = {}
        if body.name is not None:
            update_fields["name"] = body.name
        if body.target_availability_pct is not None:
            update_fields["target_availability_pct"] = body.target_availability_pct
        if body.covered_resource_ids is not None:
            update_fields["covered_resource_ids"] = body.covered_resource_ids
        if body.measurement_period is not None:
            update_fields["measurement_period"] = body.measurement_period
        if body.customer_name is not None:
            update_fields["customer_name"] = body.customer_name
        if body.report_recipients is not None:
            update_fields["report_recipients"] = body.report_recipients
        if body.is_active is not None:
            update_fields["is_active"] = body.is_active

        if not update_fields:
            row = await conn.fetchrow(
                "SELECT * FROM sla_definitions WHERE id = $1::uuid",
                sla_id,
            )
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"SLA definition {sla_id} not found",
                )
            return SLADefinitionResponse(**_row_to_response(row))

        set_parts: List[str] = []
        params: List[Any] = []
        for i, (col, val) in enumerate(update_fields.items(), start=1):
            set_parts.append(f"{col} = ${i}")
            params.append(val)

        set_parts.append("updated_at = now()")
        params.append(sla_id)
        id_param_idx = len(params)

        query = (
            f"UPDATE sla_definitions SET {', '.join(set_parts)} "
            f"WHERE id = ${id_param_idx}::uuid RETURNING *"
        )
        row = await conn.fetchrow(query, *params)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SLA definition {sla_id} not found",
            )
        return SLADefinitionResponse(**_row_to_response(row))
    finally:
        await conn.close()


@admin_sla_router.delete(
    "/sla-definitions/{sla_id}",
    tags=["admin-sla"],
)
async def delete_sla_definition(
    sla_id: str,
    _token: dict = Depends(verify_token),
) -> dict:
    """Soft-delete an SLA definition (sets is_active=false)."""
    try:
        conn = await _get_pg_connection()
    except Exception as exc:
        logger.error("sla_endpoints: PostgreSQL unavailable for delete: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLA database unavailable",
        ) from exc

    try:
        row = await conn.fetchrow(
            "UPDATE sla_definitions SET is_active = FALSE, updated_at = now() "
            "WHERE id = $1::uuid RETURNING id",
            sla_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SLA definition {sla_id} not found",
            )
        return {"deleted": True, "id": str(row["id"])}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Compliance endpoint
# ---------------------------------------------------------------------------

@sla_router.get(
    "/compliance",
    response_model=SLAComplianceResponse,
    tags=["sla"],
)
async def get_sla_compliance() -> SLAComplianceResponse:
    """Compute and return SLA compliance for all active SLA definitions.

    No authentication required.
    Returns HTTP 503 when PostgreSQL is unavailable.
    """
    try:
        conn = await _get_pg_connection()
    except Exception as exc:
        logger.error("sla_endpoints: PostgreSQL unavailable for compliance: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLA database unavailable",
        ) from exc

    try:
        rows = await conn.fetch(
            "SELECT * FROM sla_definitions WHERE is_active = TRUE ORDER BY name"
        )
    finally:
        await conn.close()

    results: List[SLAComplianceResult] = []
    for row in rows:
        result = await _calculate_compliance(row)
        results.append(result)

    return SLAComplianceResponse(
        results=results,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Report endpoints
# ---------------------------------------------------------------------------

from services.api_gateway.sla_report import generate_and_send_sla_report  # noqa: E402


@sla_router.post("/report/{sla_id}", tags=["sla"])
async def trigger_sla_report(sla_id: str):
    """Manually trigger SLA report generation and email delivery."""
    result = await generate_and_send_sla_report(sla_id)
    if result.error:
        raise HTTPException(status_code=404, detail=result.error)
    return result


class SLAReportJobConfig(BaseModel):
    schedule: str = "0 6 1 * *"
    enabled: bool = True
    description: str = (
        "Monthly SLA report generation job. "
        "Trigger via POST /api/v1/sla/report/{sla_id} or schedule externally."
    )


@admin_sla_router.post("/sla-report-job", tags=["admin-sla"])
async def register_sla_report_job(config: SLAReportJobConfig, _=Depends(verify_token)):
    """Register/describe the monthly SLA report schedule."""
    return {
        "schedule": config.schedule,
        "enabled": config.enabled,
        "description": config.description,
        "note": (
            "External trigger required. POST /api/v1/sla/report/{sla_id} "
            "on the 1st of each month to generate and email reports."
        ),
    }
