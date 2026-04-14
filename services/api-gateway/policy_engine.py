"""Policy evaluation engine — auto-approval guard for known-safe remediation actions (Phase 51).

Evaluation flow per request (in order):
  1. aap-protected tag check — NON-NEGOTIABLE emergency brake; always blocks first
  2. PostgreSQL policy query — find enabled policies matching action_class
  3. For each policy (first-match wins):
     a. Tag filter check
     b. Blast-radius check (uses topology_client.get_blast_radius)
     c. Daily execution cap (Cosmos remediation_audit count query)
     d. SLO health gate (Azure Resource Health, when require_slo_healthy=True)
  4. Return auto_approved=True on first policy that passes all guards

Never raises — all guard exceptions are caught and treated as guard-FAILURE (conservative).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Imported from remediation_executor to avoid duplication
from services.api_gateway.remediation_executor import (
    COSMOS_DATABASE_NAME,
    COSMOS_REMEDIATION_AUDIT_CONTAINER,
)


async def evaluate_auto_approval(
    action_class: str,
    resource_id: str,
    resource_tags: dict,
    topology_client: Optional[Any],
    cosmos_client: Optional[Any],
    credential: Optional[Any],
) -> tuple[bool, Optional[str], str]:
    """Evaluate whether a remediation action can be auto-approved by a policy.

    Returns (auto_approved, policy_id, reason).

    Args:
        action_class:    Remediation action string (must match SAFE_ARM_ACTIONS key).
        resource_id:     ARM resource ID of the target resource.
        resource_tags:   Tags dict from the resource snapshot.
        topology_client: Topology client with get_blast_radius(); may be None.
        cosmos_client:   Cosmos DB client for daily-cap query; may be None.
        credential:      Azure credential for Resource Health check; may be None.

    Returns:
        (True,  policy_id, "policy_match")          — auto-approved
        (False, None,      "resource_tagged_aap_protected") — emergency brake
        (False, None,      "no_matching_policy")    — no enabled policy for action_class
        (False, None,      "guards_failed")         — policy found but all guards blocked
    """
    # -----------------------------------------------------------------------
    # Guard 1: aap-protected tag — NON-NEGOTIABLE emergency brake
    # -----------------------------------------------------------------------
    if resource_tags.get("aap-protected") == "true":
        logger.info(
            "evaluate_auto_approval: BLOCKED by aap-protected tag | "
            "action_class=%s resource_id=%s",
            action_class, resource_id,
        )
        return (False, None, "resource_tagged_aap_protected")

    # -----------------------------------------------------------------------
    # Guard 2: Query PostgreSQL for enabled policies matching action_class
    # -----------------------------------------------------------------------
    policies = await _query_matching_policies(action_class)
    if not policies:
        logger.debug(
            "evaluate_auto_approval: no matching policy | action_class=%s", action_class
        )
        return (False, None, "no_matching_policy")

    # -----------------------------------------------------------------------
    # Guards 3a-3d: Evaluate each policy (first match wins)
    # -----------------------------------------------------------------------
    for policy in policies:
        policy_id = str(policy.get("id", ""))
        passed = await _evaluate_policy_guards(
            policy=policy,
            policy_id=policy_id,
            action_class=action_class,
            resource_id=resource_id,
            resource_tags=resource_tags,
            topology_client=topology_client,
            cosmos_client=cosmos_client,
            credential=credential,
        )
        if passed:
            logger.info(
                "evaluate_auto_approval: AUTO-APPROVED by policy | "
                "policy_id=%s action_class=%s resource_id=%s",
                policy_id, action_class, resource_id,
            )
            return (True, policy_id, "policy_match")

    logger.info(
        "evaluate_auto_approval: all policies failed guards | "
        "action_class=%s resource_id=%s",
        action_class, resource_id,
    )
    return (False, None, "guards_failed")


async def _query_matching_policies(action_class: str) -> list[dict]:
    """Query PostgreSQL for enabled policies matching action_class.

    Returns list of policy dicts (from asyncpg records).
    Returns [] on any error (conservative — no auto-approve on DB failure).
    """
    try:
        import asyncpg
        from services.api_gateway.runbook_rag import resolve_postgres_dsn

        dsn = resolve_postgres_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                "SELECT * FROM remediation_policies WHERE action_class = $1 AND enabled = true",
                action_class,
            )
            return [dict(row) for row in rows]
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning(
            "_query_matching_policies: failed to query policies (treating as no match) | "
            "action_class=%s error=%s",
            action_class, exc,
        )
        return []


async def _evaluate_policy_guards(
    policy: dict,
    policy_id: str,
    action_class: str,
    resource_id: str,
    resource_tags: dict,
    topology_client: Optional[Any],
    cosmos_client: Optional[Any],
    credential: Optional[Any],
) -> bool:
    """Evaluate all guards for a single policy.

    Returns True only if ALL guards pass. Conservative: any exception = guard failure.
    """
    # -----------------------------------------------------------------------
    # Guard 3a: Tag filter check
    # -----------------------------------------------------------------------
    try:
        tag_filter = policy.get("resource_tag_filter") or {}
        if isinstance(tag_filter, str):
            import json
            tag_filter = json.loads(tag_filter)
        for required_key, required_value in tag_filter.items():
            if resource_tags.get(required_key) != required_value:
                logger.debug(
                    "_evaluate_policy_guards: tag filter mismatch | "
                    "policy_id=%s required=%s=%s actual=%s",
                    policy_id, required_key, required_value, resource_tags.get(required_key),
                )
                return False
    except Exception as exc:
        logger.warning(
            "_evaluate_policy_guards: tag filter check failed (guard failure) | "
            "policy_id=%s error=%s",
            policy_id, exc,
        )
        return False

    # -----------------------------------------------------------------------
    # Guard 3b: Blast-radius check
    # -----------------------------------------------------------------------
    try:
        max_blast_radius = int(policy.get("max_blast_radius", 10))
        blast_radius_size = 0
        if topology_client is not None:
            blast_result = topology_client.get_blast_radius(resource_id, 3)
            blast_radius_size = blast_result.get("total_affected", 0)
        if blast_radius_size > max_blast_radius:
            logger.info(
                "_evaluate_policy_guards: blast radius exceeds cap | "
                "policy_id=%s blast_radius_size=%d max_blast_radius=%d",
                policy_id, blast_radius_size, max_blast_radius,
            )
            return False
    except Exception as exc:
        logger.warning(
            "_evaluate_policy_guards: blast radius check failed (guard failure) | "
            "policy_id=%s error=%s",
            policy_id, exc,
        )
        return False

    # -----------------------------------------------------------------------
    # Guard 3c: Daily execution cap (Cosmos remediation_audit count)
    # -----------------------------------------------------------------------
    try:
        if cosmos_client is not None:
            today_start = (
                datetime.now(timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )
            max_daily = int(policy.get("max_daily_executions", 20))
            container = cosmos_client.get_database_client(
                COSMOS_DATABASE_NAME
            ).get_container_client(COSMOS_REMEDIATION_AUDIT_CONTAINER)
            query_result = list(container.query_items(
                query=(
                    "SELECT VALUE COUNT(1) FROM c "
                    "WHERE c.auto_approved_by_policy = @policy_id "
                    "AND c.executed_at >= @today_start "
                    "AND c.action_type = 'execute'"
                ),
                parameters=[
                    {"name": "@policy_id", "value": policy_id},
                    {"name": "@today_start", "value": today_start},
                ],
                enable_cross_partition_query=True,
            ))
            count = query_result[0] if query_result else 0
            if count >= max_daily:
                logger.info(
                    "_evaluate_policy_guards: daily cap exceeded | "
                    "policy_id=%s count=%d max=%d",
                    policy_id, count, max_daily,
                )
                return False
    except Exception as exc:
        logger.warning(
            "_evaluate_policy_guards: daily cap check failed (guard failure) | "
            "policy_id=%s error=%s",
            policy_id, exc,
        )
        return False

    # -----------------------------------------------------------------------
    # Guard 3d: SLO health gate (Azure Resource Health)
    # -----------------------------------------------------------------------
    try:
        require_slo_healthy = bool(policy.get("require_slo_healthy", True))
        if require_slo_healthy and credential is not None:
            available = await _check_resource_health(resource_id, credential)
            if not available:
                logger.info(
                    "_evaluate_policy_guards: SLO health gate blocked | "
                    "policy_id=%s resource_id=%s",
                    policy_id, resource_id,
                )
                return False
    except Exception as exc:
        logger.warning(
            "_evaluate_policy_guards: SLO health gate failed (guard failure) | "
            "policy_id=%s error=%s",
            policy_id, exc,
        )
        return False

    return True


async def _check_resource_health(resource_id: str, credential: Any) -> bool:
    """Check Azure Resource Health availability for the resource.

    Returns True if availability_state == "Available", False otherwise.
    Runs sync SDK call in thread executor.
    """
    parts = resource_id.split("/")
    subscription_id = parts[2] if len(parts) > 2 else ""

    def _sync_health_check() -> bool:
        from azure.mgmt.resourcehealth import MicrosoftResourceHealth

        health_client = MicrosoftResourceHealth(credential, subscription_id)
        status_result = health_client.availability_statuses.get_by_resource(
            resource_uri=resource_id,
            api_version="2023-07-01",
        )
        availability = getattr(
            getattr(status_result, "properties", None),
            "availability_state",
            None,
        )
        return str(availability) == "Available" if availability else False

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_health_check)
