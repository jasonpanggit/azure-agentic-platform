"""Teams Adaptive Card posting for high-risk remediation proposals (REMEDI-002).

Phase 5 only posts cards to Teams (outbound). The full Teams bot
(bidirectional conversation) is Phase 6.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL", "")
API_GATEWAY_PUBLIC_URL = os.environ.get("API_GATEWAY_PUBLIC_URL", "http://localhost:8000")


async def post_approval_card(
    approval_id: str,
    thread_id: str,
    proposal: dict,
    risk_level: str,
    expires_at: str,
) -> Optional[dict]:
    """Post an Adaptive Card to Teams for a high-risk remediation proposal."""
    if not TEAMS_WEBHOOK_URL:
        logger.warning("TEAMS_WEBHOOK_URL not configured; skipping Teams card posting")
        return None

    card_payload = _build_adaptive_card(
        approval_id=approval_id,
        thread_id=thread_id,
        proposal=proposal,
        risk_level=risk_level,
        expires_at=expires_at,
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                TEAMS_WEBHOOK_URL,
                json=card_payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return {"message_id": response.headers.get("x-ms-message-id", "unknown")}
    except Exception as exc:
        logger.error("Failed to post Teams card for approval %s: %s", approval_id, exc)
        return None


def _build_adaptive_card(
    approval_id: str,
    thread_id: str,
    proposal: dict,
    risk_level: str,
    expires_at: str,
) -> dict:
    """Build an Adaptive Card v1.5 payload for a remediation proposal."""
    risk_color = "attention" if risk_level == "critical" else "warning"

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.5",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"Remediation Approval Required ({risk_level.upper()})",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": risk_color,
                        },
                        {
                            "type": "TextBlock",
                            "text": proposal.get("description", ""),
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Target", "value": ", ".join(proposal.get("target_resources", []))},
                                {"title": "Impact", "value": proposal.get("estimated_impact", "Unknown")},
                                {"title": "Risk Level", "value": risk_level},
                                {"title": "Reversibility", "value": proposal.get("reversibility", "Unknown")},
                                {"title": "Expires", "value": expires_at},
                            ],
                        },
                    ],
                    "actions": [
                        {
                            "type": "Action.Http",
                            "title": "Approve",
                            "method": "POST",
                            "url": f"{API_GATEWAY_PUBLIC_URL}/api/v1/approvals/{approval_id}/approve",
                            "body": json.dumps({"decided_by": "{{userName}}"}),
                            "style": "positive",
                        },
                        {
                            "type": "Action.Http",
                            "title": "Reject",
                            "method": "POST",
                            "url": f"{API_GATEWAY_PUBLIC_URL}/api/v1/approvals/{approval_id}/reject",
                            "body": json.dumps({"decided_by": "{{userName}}"}),
                            "style": "destructive",
                        },
                    ],
                },
            }
        ],
    }
