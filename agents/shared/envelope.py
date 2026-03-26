"""Typed message envelope for agent-to-agent communication (AGENT-002)."""
from __future__ import annotations

from typing import Any, Literal, TypedDict


class IncidentMessage(TypedDict):
    """Typed JSON envelope for all inter-agent messages.

    Every agent-to-agent message MUST use this envelope.
    Raw strings between agents are prohibited (AGENT-002).
    """

    correlation_id: str
    thread_id: str
    source_agent: str
    target_agent: str
    message_type: Literal[
        "incident_handoff",
        "diagnosis_complete",
        "remediation_proposal",
        "cross_domain_request",
        "status_update",
    ]
    payload: dict[str, Any]
    timestamp: str  # ISO 8601


VALID_MESSAGE_TYPES = frozenset({
    "incident_handoff",
    "diagnosis_complete",
    "remediation_proposal",
    "cross_domain_request",
    "status_update",
})


def validate_envelope(message: dict[str, Any]) -> IncidentMessage:
    """Validate that a dict conforms to the IncidentMessage schema.

    Raises ValueError if any required field is missing or has wrong type.
    Returns the message cast to IncidentMessage on success.
    """
    required_fields = {
        "correlation_id": str,
        "thread_id": str,
        "source_agent": str,
        "target_agent": str,
        "message_type": str,
        "payload": dict,
        "timestamp": str,
    }

    missing = [f for f in required_fields if f not in message]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    for field, expected_type in required_fields.items():
        if not isinstance(message[field], expected_type):
            raise ValueError(
                f"Field '{field}' expected {expected_type.__name__}, "
                f"got {type(message[field]).__name__}"
            )

    if message["message_type"] not in VALID_MESSAGE_TYPES:
        raise ValueError(
            f"Invalid message_type '{message['message_type']}'. "
            f"Must be one of: {', '.join(sorted(VALID_MESSAGE_TYPES))}"
        )

    return IncidentMessage(**{k: message[k] for k in required_fields})
