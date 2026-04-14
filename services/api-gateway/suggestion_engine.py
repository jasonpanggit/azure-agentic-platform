"""Learning suggestion engine — detects repeated HITL-approved patterns and proposes policies.

Background sweep queries the remediation_audit container for HITL-approved executions
(auto_approved_by_policy IS NULL). When an action_class accumulates >= SUGGESTION_APPROVAL_THRESHOLD
executions with 0 rollbacks in 30 days, a suggestion is created in the policy_suggestions container.

Architecture:
- run_suggestion_sweep: one-shot analysis pass, returns new suggestions created
- run_suggestion_sweep_loop: asyncio background task (mirrors run_pattern_analysis_loop)
- get_pending_suggestions: returns non-dismissed, unconverted suggestions
- dismiss_suggestion: marks a suggestion dismissed=True
- convert_suggestion_to_policy: records the policy_id the suggestion was converted to
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

SUGGESTION_APPROVAL_THRESHOLD: int = int(
    os.environ.get("SUGGESTION_APPROVAL_THRESHOLD", "5")
)
SUGGESTION_SWEEP_INTERVAL_SECONDS: int = int(
    os.environ.get("SUGGESTION_SWEEP_INTERVAL_SECONDS", "21600")  # 6 hours
)
COSMOS_POLICY_SUGGESTIONS_CONTAINER: str = os.environ.get(
    "COSMOS_POLICY_SUGGESTIONS_CONTAINER", "policy_suggestions"
)
COSMOS_REMEDIATION_AUDIT_CONTAINER: str = os.environ.get(
    "COSMOS_REMEDIATION_AUDIT_CONTAINER", "remediation_audit"
)
COSMOS_DATABASE_NAME: str = os.environ.get("COSMOS_DATABASE_NAME", "aap")


def _get_container(cosmos_client: Any, container_name: str) -> Any:
    """Return a Cosmos container client."""
    db = cosmos_client.get_database_client(COSMOS_DATABASE_NAME)
    return db.get_container_client(container_name)


async def run_suggestion_sweep(cosmos_client: Optional[Any]) -> list[dict]:
    """Detect repeated HITL-approved patterns and create suggestions.

    Queries remediation_audit for HITL-approved executions in the last 30 days
    (records where auto_approved_by_policy is not set or null).
    Groups by proposed_action (action_class). For each group:
    - If count >= SUGGESTION_APPROVAL_THRESHOLD and rollbacks == 0:
      - Check if a non-dismissed suggestion for this action_class already exists.
      - If not, upsert a new suggestion into the policy_suggestions container.

    Args:
        cosmos_client: CosmosClient instance, or None (skips sweep gracefully).

    Returns:
        List of new suggestion dicts created during this sweep.
    """
    if cosmos_client is None:
        logger.warning("suggestion_engine: sweep skipped (no cosmos_client)")
        return []

    loop = asyncio.get_running_loop()
    new_suggestions = await loop.run_in_executor(
        None, _run_sweep_sync, cosmos_client
    )
    return new_suggestions


def _run_sweep_sync(cosmos_client: Any) -> list[dict]:
    """Synchronous sweep body — runs in executor thread.

    Returns list of new suggestion dicts upserted this run.
    """
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    # --- Query HITL-approved executions (exclude auto-approved records) ---
    try:
        audit_container = _get_container(cosmos_client, COSMOS_REMEDIATION_AUDIT_CONTAINER)
        query = (
            "SELECT c.proposed_action, c.resource_id, c.verification_result, c.executed_at "
            "FROM c "
            "WHERE c.action_type = 'execute' "
            "AND c.status = 'complete' "
            "AND (NOT IS_DEFINED(c.auto_approved_by_policy) OR c.auto_approved_by_policy = null) "
            "AND c.executed_at >= @thirty_days_ago"
        )
        parameters = [{"name": "@thirty_days_ago", "value": thirty_days_ago}]
        records = list(audit_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        logger.warning("suggestion_engine: audit query failed | error=%s", exc)
        return []

    # --- Group by proposed_action (action_class) ---
    groups: dict[str, list[dict]] = {}
    for record in records:
        action_class = record.get("proposed_action", "")
        if not action_class:
            continue
        if action_class not in groups:
            groups[action_class] = []
        groups[action_class].append(record)

    new_suggestions: list[dict] = []

    for action_class, group in groups.items():
        total_count = len(group)
        rollback_count = sum(
            1 for r in group if r.get("verification_result") == "DEGRADED"
        )

        if total_count < SUGGESTION_APPROVAL_THRESHOLD or rollback_count > 0:
            continue

        # Check if a non-dismissed suggestion already exists for this action_class
        if _suggestion_exists(cosmos_client, action_class):
            logger.debug(
                "suggestion_engine: suggestion already exists for action_class=%s — skipping",
                action_class,
            )
            continue

        # Build and upsert a new suggestion
        suggestion: dict = {
            "id": str(uuid.uuid4()),
            "action_class": action_class,
            "resource_pattern": {},
            "approval_count": total_count,
            "rollback_count": 0,
            "suggested_at": now.isoformat(),
            "dismissed": False,
            "converted_to_policy_id": None,
            "message": (
                f"Consider creating a policy for '{action_class}' — "
                f"approved {total_count} times with 0 rollbacks in the last 30 days."
            ),
        }

        try:
            suggestions_container = _get_container(
                cosmos_client, COSMOS_POLICY_SUGGESTIONS_CONTAINER
            )
            suggestions_container.upsert_item(suggestion)
            new_suggestions.append(suggestion)
            logger.info(
                "suggestion_engine: created suggestion | action_class=%s approval_count=%d",
                action_class,
                total_count,
            )
        except Exception as exc:
            logger.warning(
                "suggestion_engine: upsert failed | action_class=%s error=%s",
                action_class,
                exc,
            )

    return new_suggestions


def _suggestion_exists(cosmos_client: Any, action_class: str) -> bool:
    """Return True if a non-dismissed, unconverted suggestion exists for the action_class."""
    try:
        container = _get_container(cosmos_client, COSMOS_POLICY_SUGGESTIONS_CONTAINER)
        query = (
            "SELECT c.id FROM c "
            "WHERE c.action_class = @action_class "
            "AND c.dismissed = false "
            "AND (NOT IS_DEFINED(c.converted_to_policy_id) OR c.converted_to_policy_id = null)"
        )
        parameters = [{"name": "@action_class", "value": action_class}]
        items = list(container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=False,  # action_class is the partition key
        ))
        return len(items) > 0
    except Exception as exc:
        logger.warning(
            "suggestion_engine: existence check failed | action_class=%s error=%s",
            action_class,
            exc,
        )
        return False


async def run_suggestion_sweep_loop(
    cosmos_client: Optional[Any],
    interval_seconds: int = SUGGESTION_SWEEP_INTERVAL_SECONDS,
) -> None:
    """Background asyncio task: run suggestion sweep every interval_seconds.

    Mirrors run_pattern_analysis_loop in pattern_analyzer.py:
    - Waits one full interval before first run (avoids startup contention).
    - Re-raises asyncio.CancelledError for clean shutdown.
    - Logs but does not raise on transient errors (loop continues).

    Args:
        cosmos_client:    CosmosClient instance (from app.state).
        interval_seconds: Sweep interval in seconds (default 21600 — 6 hours).
    """
    logger.info(
        "suggestion_engine: loop started | interval=%ds", interval_seconds
    )

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            new_suggestions = await run_suggestion_sweep(cosmos_client)
            logger.info(
                "suggestion_engine: sweep complete | new_suggestions=%d",
                len(new_suggestions),
            )
        except asyncio.CancelledError:
            logger.info("suggestion_engine: loop cancelled — shutting down")
            raise
        except Exception as exc:
            logger.error(
                "suggestion_engine: loop unexpected error | error=%s", exc, exc_info=True
            )
            # Continue loop — transient errors must not stop the background task


async def get_pending_suggestions(cosmos_client: Optional[Any]) -> list[dict]:
    """Return all non-dismissed suggestions not yet converted to a policy.

    Args:
        cosmos_client: CosmosClient instance, or None (returns empty list).

    Returns:
        List of suggestion dicts from the policy_suggestions container.
    """
    if cosmos_client is None:
        return []

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_pending_sync, cosmos_client
        )
    except Exception as exc:
        logger.warning("suggestion_engine: get_pending_suggestions failed | error=%s", exc)
        return []


def _get_pending_sync(cosmos_client: Any) -> list[dict]:
    """Synchronous query for pending suggestions — runs in executor."""
    try:
        container = _get_container(cosmos_client, COSMOS_POLICY_SUGGESTIONS_CONTAINER)
        query = (
            "SELECT * FROM c "
            "WHERE c.dismissed = false "
            "AND (NOT IS_DEFINED(c.converted_to_policy_id) OR c.converted_to_policy_id = null)"
        )
        return list(container.query_items(
            query=query,
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        logger.warning("suggestion_engine: pending query failed | error=%s", exc)
        return []


async def dismiss_suggestion(
    cosmos_client: Optional[Any],
    suggestion_id: str,
    action_class: str,
) -> bool:
    """Mark a suggestion as dismissed.

    Args:
        cosmos_client: CosmosClient instance.
        suggestion_id: The suggestion UUID.
        action_class:  Partition key value for the suggestion document.

    Returns:
        True on success, False on failure or not found.
    """
    if cosmos_client is None:
        return False

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _dismiss_sync, cosmos_client, suggestion_id, action_class
        )
    except Exception as exc:
        logger.warning(
            "suggestion_engine: dismiss_suggestion failed | id=%s error=%s",
            suggestion_id,
            exc,
        )
        return False


def _dismiss_sync(
    cosmos_client: Any, suggestion_id: str, action_class: str
) -> bool:
    """Synchronous dismiss — runs in executor."""
    try:
        container = _get_container(cosmos_client, COSMOS_POLICY_SUGGESTIONS_CONTAINER)
        item = container.read_item(item=suggestion_id, partition_key=action_class)
        item["dismissed"] = True
        container.replace_item(item=suggestion_id, body=item)
        return True
    except Exception as exc:
        logger.warning(
            "suggestion_engine: _dismiss_sync failed | id=%s error=%s",
            suggestion_id,
            exc,
        )
        return False


async def convert_suggestion_to_policy(
    cosmos_client: Optional[Any],
    suggestion_id: str,
    action_class: str,
    policy_id: str,
) -> bool:
    """Record that a suggestion was converted to a policy.

    Args:
        cosmos_client: CosmosClient instance.
        suggestion_id: The suggestion UUID.
        action_class:  Partition key value for the suggestion document.
        policy_id:     The created policy UUID to link.

    Returns:
        True on success, False on failure or not found.
    """
    if cosmos_client is None:
        return False

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _convert_sync, cosmos_client, suggestion_id, action_class, policy_id
        )
    except Exception as exc:
        logger.warning(
            "suggestion_engine: convert_suggestion_to_policy failed | id=%s error=%s",
            suggestion_id,
            exc,
        )
        return False


def _convert_sync(
    cosmos_client: Any,
    suggestion_id: str,
    action_class: str,
    policy_id: str,
) -> bool:
    """Synchronous convert — runs in executor."""
    try:
        container = _get_container(cosmos_client, COSMOS_POLICY_SUGGESTIONS_CONTAINER)
        item = container.read_item(item=suggestion_id, partition_key=action_class)
        item["converted_to_policy_id"] = policy_id
        container.replace_item(item=suggestion_id, body=item)
        return True
    except Exception as exc:
        logger.warning(
            "suggestion_engine: _convert_sync failed | id=%s error=%s",
            suggestion_id,
            exc,
        )
        return False
