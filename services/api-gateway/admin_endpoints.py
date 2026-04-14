"""Admin CRUD endpoints for remediation policies (Phase 51 — Autonomous Remediation).

Provides full CRUD on the PostgreSQL remediation_policies table, plus
execution history queries against the Cosmos remediation_audit container.
All endpoints require Entra ID Bearer token via Depends(verify_token).

Routes:
  GET    /api/v1/admin/remediation-policies              — list all policies
  POST   /api/v1/admin/remediation-policies              — create a policy
  GET    /api/v1/admin/remediation-policies/{policy_id}  — get single policy
  PUT    /api/v1/admin/remediation-policies/{policy_id}  — update policy
  DELETE /api/v1/admin/remediation-policies/{policy_id}  — delete policy
  GET    /api/v1/admin/remediation-policies/{policy_id}/executions — execution history
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from services.api_gateway.auth import verify_token
from services.api_gateway.models import (
    AutoRemediationPolicy,
    AutoRemediationPolicyCreate,
    AutoRemediationPolicyUpdate,
    PolicyExecution,
    PolicySuggestion,
)
from services.api_gateway.remediation_executor import SAFE_ARM_ACTIONS
from services.api_gateway.runbook_rag import (
    RunbookSearchUnavailableError,
    resolve_postgres_dsn,
)
from services.api_gateway.suggestion_engine import (
    convert_suggestion_to_policy,
    dismiss_suggestion,
    get_pending_suggestions,
)

logger = logging.getLogger(__name__)

COSMOS_DATABASE_NAME = os.environ.get("COSMOS_DATABASE_NAME", "aap")
COSMOS_REMEDIATION_AUDIT_CONTAINER = os.environ.get(
    "COSMOS_REMEDIATION_AUDIT_CONTAINER", "remediation_audit"
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


async def _get_pg_connection() -> asyncpg.Connection:
    """Create a PostgreSQL connection using the resolved DSN."""
    dsn = resolve_postgres_dsn()
    return await asyncpg.connect(dsn)


def _row_to_policy(row: asyncpg.Record, execution_count_today: int = 0) -> AutoRemediationPolicy:
    """Convert an asyncpg Record to an AutoRemediationPolicy model."""
    return AutoRemediationPolicy(
        id=str(row["id"]),
        name=row["name"],
        description=row["description"],
        action_class=row["action_class"],
        resource_tag_filter=json.loads(row["resource_tag_filter"]) if row["resource_tag_filter"] else {},
        max_blast_radius=row["max_blast_radius"],
        max_daily_executions=row["max_daily_executions"],
        require_slo_healthy=row["require_slo_healthy"],
        maintenance_window_exempt=row["maintenance_window_exempt"],
        enabled=row["enabled"],
        created_at=row["created_at"].isoformat() if row["created_at"] else None,
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
        execution_count_today=execution_count_today,
    )


def _get_cosmos_audit_container(request: Request) -> Optional[Any]:
    """Return the Cosmos remediation_audit container, or None if unavailable."""
    cosmos_client = getattr(request.app.state, "cosmos_client", None)
    if cosmos_client is None:
        return None
    try:
        db = cosmos_client.get_database_client(COSMOS_DATABASE_NAME)
        return db.get_container_client(COSMOS_REMEDIATION_AUDIT_CONTAINER)
    except Exception:
        logger.warning("Failed to get Cosmos remediation_audit container", exc_info=True)
        return None


def _get_today_start_utc() -> str:
    """Return ISO 8601 string for 00:00 UTC today."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


async def _count_executions_today(container: Any, policy_id: str) -> int:
    """Count auto-executions for a policy today from Cosmos remediation_audit."""
    if container is None:
        return 0
    try:
        today_start = _get_today_start_utc()
        query = (
            "SELECT VALUE COUNT(1) FROM c "
            "WHERE c.auto_approved_by_policy = @policy_id "
            "AND c.executed_at >= @today_start"
        )
        parameters: list[dict[str, Any]] = [
            {"name": "@policy_id", "value": policy_id},
            {"name": "@today_start", "value": today_start},
        ]
        items = list(container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        ))
        return items[0] if items else 0
    except Exception:
        logger.warning("Failed to count executions for policy %s", policy_id, exc_info=True)
        return 0


@router.get("/remediation-policies", response_model=list[AutoRemediationPolicy])
async def list_policies(
    request: Request,
    _token: dict = Depends(verify_token),
) -> list[AutoRemediationPolicy]:
    """List all remediation policies with today's execution count."""
    try:
        conn = await _get_pg_connection()
    except (RunbookSearchUnavailableError, Exception) as exc:
        logger.error("PostgreSQL unavailable for policy list: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy database unavailable",
        ) from exc

    try:
        rows = await conn.fetch(
            "SELECT * FROM remediation_policies ORDER BY created_at DESC"
        )
        audit_container = _get_cosmos_audit_container(request)
        policies = []
        for row in rows:
            count = await _count_executions_today(audit_container, str(row["id"]))
            policies.append(_row_to_policy(row, execution_count_today=count))
        return policies
    finally:
        await conn.close()


@router.post(
    "/remediation-policies",
    response_model=AutoRemediationPolicy,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy(
    body: AutoRemediationPolicyCreate,
    request: Request,
    _token: dict = Depends(verify_token),
) -> AutoRemediationPolicy:
    """Create a new remediation policy."""
    # Validate action_class against SAFE_ARM_ACTIONS
    if body.action_class not in SAFE_ARM_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid action_class '{body.action_class}'. "
                f"Must be one of: {', '.join(sorted(SAFE_ARM_ACTIONS.keys()))}"
            ),
        )

    try:
        conn = await _get_pg_connection()
    except (RunbookSearchUnavailableError, Exception) as exc:
        logger.error("PostgreSQL unavailable for policy create: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy database unavailable",
        ) from exc

    try:
        tag_filter_json = json.dumps(body.resource_tag_filter)
        row = await conn.fetchrow(
            """
            INSERT INTO remediation_policies
                (name, description, action_class, resource_tag_filter,
                 max_blast_radius, max_daily_executions, require_slo_healthy,
                 maintenance_window_exempt, enabled)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            body.name,
            body.description,
            body.action_class,
            tag_filter_json,
            body.max_blast_radius,
            body.max_daily_executions,
            body.require_slo_healthy,
            body.maintenance_window_exempt,
            body.enabled,
        )
        return _row_to_policy(row)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Policy with name '{body.name}' already exists",
        ) from exc
    finally:
        await conn.close()


@router.get("/remediation-policies/{policy_id}", response_model=AutoRemediationPolicy)
async def get_policy(
    policy_id: str,
    request: Request,
    _token: dict = Depends(verify_token),
) -> AutoRemediationPolicy:
    """Get a single remediation policy by UUID."""
    try:
        conn = await _get_pg_connection()
    except (RunbookSearchUnavailableError, Exception) as exc:
        logger.error("PostgreSQL unavailable for policy get: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy database unavailable",
        ) from exc

    try:
        row = await conn.fetchrow(
            "SELECT * FROM remediation_policies WHERE id = $1::uuid",
            policy_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Policy {policy_id} not found",
            )
        audit_container = _get_cosmos_audit_container(request)
        count = await _count_executions_today(audit_container, policy_id)
        return _row_to_policy(row, execution_count_today=count)
    finally:
        await conn.close()


@router.put("/remediation-policies/{policy_id}", response_model=AutoRemediationPolicy)
async def update_policy(
    policy_id: str,
    body: AutoRemediationPolicyUpdate,
    request: Request,
    _token: dict = Depends(verify_token),
) -> AutoRemediationPolicy:
    """Update a remediation policy. Only non-None fields are updated."""
    # Validate action_class if provided
    if body.action_class is not None and body.action_class not in SAFE_ARM_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid action_class '{body.action_class}'. "
                f"Must be one of: {', '.join(sorted(SAFE_ARM_ACTIONS.keys()))}"
            ),
        )

    try:
        conn = await _get_pg_connection()
    except (RunbookSearchUnavailableError, Exception) as exc:
        logger.error("PostgreSQL unavailable for policy update: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy database unavailable",
        ) from exc

    try:
        # Build dynamic SET clause from non-None fields
        update_fields: dict[str, Any] = {}
        if body.name is not None:
            update_fields["name"] = body.name
        if body.description is not None:
            update_fields["description"] = body.description
        if body.action_class is not None:
            update_fields["action_class"] = body.action_class
        if body.resource_tag_filter is not None:
            update_fields["resource_tag_filter"] = json.dumps(body.resource_tag_filter)
        if body.max_blast_radius is not None:
            update_fields["max_blast_radius"] = body.max_blast_radius
        if body.max_daily_executions is not None:
            update_fields["max_daily_executions"] = body.max_daily_executions
        if body.require_slo_healthy is not None:
            update_fields["require_slo_healthy"] = body.require_slo_healthy
        if body.maintenance_window_exempt is not None:
            update_fields["maintenance_window_exempt"] = body.maintenance_window_exempt
        if body.enabled is not None:
            update_fields["enabled"] = body.enabled

        if not update_fields:
            # No fields to update — return existing record
            row = await conn.fetchrow(
                "SELECT * FROM remediation_policies WHERE id = $1::uuid",
                policy_id,
            )
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Policy {policy_id} not found",
                )
            return _row_to_policy(row)

        # Build parameterized SET clause
        set_parts: list[str] = []
        params: list[Any] = []
        for i, (col, val) in enumerate(update_fields.items(), start=1):
            if col == "resource_tag_filter":
                set_parts.append(f"{col} = ${i}::jsonb")
            else:
                set_parts.append(f"{col} = ${i}")
            params.append(val)

        # Add updated_at = now()
        set_parts.append("updated_at = now()")

        # Add policy_id as last param
        params.append(policy_id)
        policy_param_idx = len(params)

        query = (
            f"UPDATE remediation_policies SET {', '.join(set_parts)} "
            f"WHERE id = ${policy_param_idx}::uuid RETURNING *"
        )
        row = await conn.fetchrow(query, *params)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Policy {policy_id} not found",
            )
        audit_container = _get_cosmos_audit_container(request)
        count = await _count_executions_today(audit_container, policy_id)
        return _row_to_policy(row, execution_count_today=count)
    finally:
        await conn.close()


@router.delete(
    "/remediation-policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_policy(
    policy_id: str,
    _token: dict = Depends(verify_token),
) -> None:
    """Delete a remediation policy."""
    try:
        conn = await _get_pg_connection()
    except (RunbookSearchUnavailableError, Exception) as exc:
        logger.error("PostgreSQL unavailable for policy delete: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy database unavailable",
        ) from exc

    try:
        result = await conn.execute(
            "DELETE FROM remediation_policies WHERE id = $1::uuid",
            policy_id,
        )
        # asyncpg returns "DELETE N" where N is the count
        if result == "DELETE 0":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Policy {policy_id} not found",
            )
    finally:
        await conn.close()


@router.get(
    "/remediation-policies/{policy_id}/executions",
    response_model=list[PolicyExecution],
)
async def get_policy_executions(
    policy_id: str,
    request: Request,
    _token: dict = Depends(verify_token),
) -> list[PolicyExecution]:
    """Return last 10 auto-executions for a policy from Cosmos remediation_audit."""
    audit_container = _get_cosmos_audit_container(request)
    if audit_container is None:
        return []

    try:
        query = (
            "SELECT TOP 10 * FROM c "
            "WHERE c.auto_approved_by_policy = @policy_id "
            "ORDER BY c.executed_at DESC"
        )
        parameters: list[dict[str, str]] = [
            {"name": "@policy_id", "value": policy_id},
        ]
        items = list(audit_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        ))
        return [
            PolicyExecution(
                execution_id=item.get("id", ""),
                resource_id=item.get("resource_id", ""),
                proposed_action=item.get("proposed_action", ""),
                status=item.get("status", ""),
                verification_result=item.get("verification_result"),
                executed_at=item.get("executed_at", ""),
                duration_ms=item.get("duration_ms"),
            )
            for item in items
        ]
    except Exception:
        logger.warning(
            "Failed to query executions for policy %s", policy_id, exc_info=True
        )
        return []


# ---------------------------------------------------------------------------
# Policy suggestion endpoints (Phase 51-3: Learning Suggestion Engine)
# ---------------------------------------------------------------------------


def _get_cosmos_client(request: Request) -> Optional[Any]:
    """Return the Cosmos client from app state, or None if unavailable."""
    return getattr(request.app.state, "cosmos_client", None)


@router.get("/policy-suggestions", response_model=list[PolicySuggestion])
async def list_policy_suggestions(
    request: Request,
    _token: dict = Depends(verify_token),
) -> list[PolicySuggestion]:
    """Return all pending (non-dismissed, not-yet-converted) policy suggestions."""
    cosmos_client = _get_cosmos_client(request)
    items = await get_pending_suggestions(cosmos_client)
    return [PolicySuggestion(**item) for item in items]


@router.post("/policy-suggestions/{suggestion_id}/dismiss")
async def dismiss_policy_suggestion(
    suggestion_id: str,
    action_class: str,
    request: Request,
    _token: dict = Depends(verify_token),
) -> dict:
    """Dismiss a policy suggestion so it no longer appears in the list."""
    cosmos_client = _get_cosmos_client(request)
    success = await dismiss_suggestion(cosmos_client, suggestion_id, action_class)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Suggestion {suggestion_id} not found or could not be dismissed",
        )
    return {"status": "dismissed"}


@router.post(
    "/policy-suggestions/{suggestion_id}/convert",
    response_model=AutoRemediationPolicy,
    status_code=status.HTTP_201_CREATED,
)
async def convert_policy_suggestion(
    suggestion_id: str,
    action_class: str,
    body: AutoRemediationPolicyCreate,
    request: Request,
    _token: dict = Depends(verify_token),
) -> AutoRemediationPolicy:
    """Convert a suggestion into a real auto-remediation policy.

    Creates the policy in PostgreSQL using the same logic as POST /remediation-policies,
    then links the suggestion to the created policy_id in Cosmos.
    """
    # Validate action_class
    if body.action_class not in SAFE_ARM_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid action_class '{body.action_class}'. "
                f"Must be one of: {', '.join(sorted(SAFE_ARM_ACTIONS.keys()))}"
            ),
        )

    try:
        conn = await _get_pg_connection()
    except (RunbookSearchUnavailableError, Exception) as exc:
        logger.error("PostgreSQL unavailable for suggestion convert: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy database unavailable",
        ) from exc

    try:
        tag_filter_json = json.dumps(body.resource_tag_filter)
        row = await conn.fetchrow(
            """
            INSERT INTO remediation_policies
                (name, description, action_class, resource_tag_filter,
                 max_blast_radius, max_daily_executions, require_slo_healthy,
                 maintenance_window_exempt, enabled)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            body.name,
            body.description,
            body.action_class,
            tag_filter_json,
            body.max_blast_radius,
            body.max_daily_executions,
            body.require_slo_healthy,
            body.maintenance_window_exempt,
            body.enabled,
        )
        policy = _row_to_policy(row)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Policy with name '{body.name}' already exists",
        ) from exc
    finally:
        await conn.close()

    # Link suggestion → policy in Cosmos (best-effort; non-fatal)
    cosmos_client = _get_cosmos_client(request)
    linked = await convert_suggestion_to_policy(
        cosmos_client, suggestion_id, action_class, policy.id
    )
    if not linked:
        logger.warning(
            "suggestion_engine: failed to link suggestion %s to policy %s — suggestion may still show",
            suggestion_id,
            policy.id,
        )

    return policy
