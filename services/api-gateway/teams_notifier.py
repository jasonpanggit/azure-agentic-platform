from __future__ import annotations
"""Teams notification proxy -- sends card requests to the Teams bot (D-04, D-11).

Phase 5 posted directly to a Teams webhook URL (now deprecated).
Phase 6 sends structured payloads to the Teams bot Container App's
internal notify endpoint, which renders cards and posts to Teams.
"""
import os

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TEAMS_BOT_INTERNAL_URL = os.environ.get("TEAMS_BOT_INTERNAL_URL", "")
TEAMS_CHANNEL_ID = os.environ.get("TEAMS_CHANNEL_ID", "")


async def notify_teams(
    card_type: str,
    payload: dict,
    channel_id: Optional[str] = None,
) -> Optional[dict]:
    """Send a notification request to the Teams bot internal endpoint.

    Args:
        card_type: One of "alert", "approval", "outcome", "reminder".
        payload: Card-specific payload matching the NotifyRequest schema.
        channel_id: Target Teams channel (defaults to TEAMS_CHANNEL_ID env var).

    Returns:
        NotifyResponse dict on success, None on failure.
    """
    target_url = TEAMS_BOT_INTERNAL_URL
    if not target_url:
        logger.warning(
            "TEAMS_BOT_INTERNAL_URL not configured; skipping Teams notification"
        )
        return None

    effective_channel_id = channel_id or TEAMS_CHANNEL_ID
    if not effective_channel_id:
        logger.warning(
            "TEAMS_CHANNEL_ID not configured; skipping Teams notification"
        )
        return None

    notify_request = {
        "card_type": card_type,
        "channel_id": effective_channel_id,
        "payload": payload,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{target_url}/teams/internal/notify",
                json=notify_request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.error("Failed to notify Teams bot (%s): %s", card_type, exc)
        return None


async def post_approval_card(
    approval_id: str,
    thread_id: str,
    proposal: dict,
    risk_level: str,
    expires_at: str,
) -> Optional[dict]:
    """Post an approval card to Teams (backward-compatible wrapper).

    Maintains the same function signature as Phase 5 for callers
    that already use this function (e.g., approval lifecycle code).
    """
    return await notify_teams(
        card_type="approval",
        payload={
            "approval_id": approval_id,
            "thread_id": thread_id,
            "proposal": proposal,
            "risk_level": risk_level,
            "expires_at": expires_at,
        },
    )


async def post_alert_card(
    incident_id: str,
    alert_title: str,
    resource_name: str,
    severity: str,
    subscription_name: str,
    domain: str,
    timestamp: str,
) -> Optional[dict]:
    """Post an alert card to Teams (TEAMS-002)."""
    return await notify_teams(
        card_type="alert",
        payload={
            "incident_id": incident_id,
            "alert_title": alert_title,
            "resource_name": resource_name,
            "severity": severity,
            "subscription_name": subscription_name,
            "domain": domain,
            "timestamp": timestamp,
        },
    )


async def post_outcome_card(
    incident_id: str,
    approval_id: str,
    action_description: str,
    outcome_status: str,
    duration_seconds: int,
    resulting_resource_state: str,
    approver_upn: str,
    executed_at: str,
) -> Optional[dict]:
    """Post a remediation outcome card to Teams (TEAMS-006)."""
    return await notify_teams(
        card_type="outcome",
        payload={
            "incident_id": incident_id,
            "approval_id": approval_id,
            "action_description": action_description,
            "outcome_status": outcome_status,
            "duration_seconds": duration_seconds,
            "resulting_resource_state": resulting_resource_state,
            "approver_upn": approver_upn,
            "executed_at": executed_at,
        },
    )
