"""SOP notification tool — dispatches Teams + email notifications (Phase 30).

Provides the ``sop_notify`` @ai_function that agents call whenever a SOP
step is marked [NOTIFY]. Supports Teams and email channels independently.
Notification failures are logged but never raised — they must not interrupt
the agent's triage workflow.

Add to each agent's tools list::

    from shared.sop_notify import sop_notify
    tools=[..., sop_notify]
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from agent_framework import ai_function

logger = logging.getLogger(__name__)


@ai_function
async def sop_notify(
    message: str,
    severity: Literal["info", "warning", "critical"],
    channels: list[Literal["teams", "email"]],
    incident_id: str,
    resource_name: str,
    sop_step: str,
) -> dict:
    """Send a notification as required by the active SOP.

    Call this whenever the SOP specifies a [NOTIFY] step.
    Always use this tool — never skip notification steps.

    Args:
        message: Human-readable notification message.
        severity: Notification severity level.
        channels: List of channels to notify. Pass ["teams", "email"] for both.
            Valid values: "teams", "email". Do NOT pass "both".
        incident_id: Incident identifier (e.g. "inc-001").
        resource_name: Affected resource name (e.g. "vm-prod-01").
        sop_step: Current SOP step description (e.g. "Step 2: Notify operator").

    Returns:
        Dict with status, channels (results per channel), and sop_step.
    """
    results: dict[str, object] = {}
    any_success = False

    if "teams" in channels:
        try:
            results["teams"] = await _send_teams_notification(
                message=message,
                severity=severity,
                incident_id=incident_id,
                resource_name=resource_name,
                sop_step=sop_step,
            )
            any_success = True
        except Exception as exc:
            logger.warning("sop_notify: Teams notification failed: %s", exc)
            results["teams"] = {"ok": False, "error": str(exc)}

    if "email" in channels:
        try:
            results["email"] = await _send_email_notification(
                message=message,
                severity=severity,
                incident_id=incident_id,
                resource_name=resource_name,
                sop_step=sop_step,
            )
            any_success = True
        except Exception as exc:
            logger.warning("sop_notify: Email notification failed: %s", exc)
            results["email"] = {"ok": False, "error": str(exc)}

    all_failed = bool(results) and all(
        isinstance(v, dict) and v.get("ok") is False for v in results.values()
    )
    status = "error" if all_failed else ("partial" if not any_success else "sent")

    return {"status": status, "channels": results, "sop_step": sop_step}


async def _send_teams_notification(
    message: str,
    severity: str,
    incident_id: str,
    resource_name: str,
    sop_step: str,
) -> dict:
    """Send a SOP notification card to the Teams bot internal endpoint."""
    import httpx

    teams_bot_url = os.environ.get("TEAMS_BOT_INTERNAL_URL", "")
    channel_id = os.environ.get("TEAMS_CHANNEL_ID", "")

    if not teams_bot_url or not channel_id:
        logger.warning("sop_notify: TEAMS_BOT_INTERNAL_URL or TEAMS_CHANNEL_ID not set")
        return {"ok": False, "error": "Teams not configured"}

    payload = {
        "card_type": "sop_notification",
        "channel_id": channel_id,
        "payload": {
            "incident_id": incident_id,
            "resource_name": resource_name,
            "message": message,
            "severity": severity,
            "sop_step": sop_step,
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{teams_bot_url}/teams/internal/notify",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def _send_email_notification(
    message: str,
    severity: str,
    incident_id: str,
    resource_name: str,
    sop_step: str,
) -> dict:
    """Send a notification email via Azure Communication Services (ACS)."""
    acs_connection_string = os.environ.get("ACS_CONNECTION_STRING", "")
    from_address = os.environ.get("NOTIFICATION_EMAIL_FROM", "")
    to_address = os.environ.get("NOTIFICATION_EMAIL_TO", "")

    if not all([acs_connection_string, from_address, to_address]):
        logger.warning("sop_notify: ACS email not configured (missing env vars)")
        return {"ok": False, "error": "ACS email not configured"}

    try:
        from azure.communication.email import EmailClient
    except ImportError:
        return {"ok": False, "error": "azure-communication-email not installed"}

    subject = f"[{severity.upper()}] AIOps SOP Notification -- {incident_id}"
    body_text = (
        f"Incident: {incident_id}\n"
        f"Resource: {resource_name}\n"
        f"SOP Step: {sop_step}\n\n"
        f"{message}"
    )
    body_html = (
        f"<p><strong>Incident:</strong> {incident_id}</p>"
        f"<p><strong>Resource:</strong> {resource_name}</p>"
        f"<p><strong>SOP Step:</strong> {sop_step}</p>"
        f"<p>{message}</p>"
    )

    email_client = EmailClient.from_connection_string(acs_connection_string)
    message_obj = {
        "senderAddress": from_address,
        "recipients": {"to": [{"address": to_address}]},
        "content": {"subject": subject, "plainText": body_text, "html": body_html},
    }

    poller = email_client.begin_send(message_obj)
    result = poller.result()
    return {"ok": True, "message_id": result.get("id")}
