"""Pydantic models for the detection plane (DETECT-005, DETECT-006).

Defines the Cosmos DB incident record schema and alert state transitions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AlertStatus(str, Enum):
    """Valid alert status values (D-14 state machine)."""
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


class StatusHistoryEntry(BaseModel):
    """A single status transition record."""
    status: AlertStatus
    actor: str = Field(..., description="Agent ID or operator UPN who caused the transition")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of the transition",
    )


class CorrelatedAlert(BaseModel):
    """A correlated alert appended to an existing incident (D-12)."""
    alert_id: str
    severity: str
    detection_rule: str
    correlated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class IncidentRecord(BaseModel):
    """Cosmos DB incident record schema (D-13).

    Partition key: resource_id
    """
    id: str = Field(..., description="Cosmos DB document ID (same as incident_id)")
    resource_id: str = Field(..., description="ARM resource ID — Cosmos DB partition key")
    incident_id: str
    severity: str = Field(..., pattern=r"^Sev[0-3]$")
    domain: str = Field(..., pattern=r"^(compute|network|storage|security|arc|sre)$")
    detection_rule: str
    kql_evidence: Optional[str] = None
    status: AlertStatus = AlertStatus.NEW
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)
    thread_id: Optional[str] = None
    correlated_alerts: list[CorrelatedAlert] = Field(default_factory=list)
    affected_resources: list[dict] = Field(default_factory=list)
    title: Optional[str] = None
    description: Optional[str] = None
    duplicate_count: int = 0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


# Valid state transitions (D-14 state machine):
# new -> acknowledged, new -> closed, acknowledged -> closed
VALID_TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.NEW: {AlertStatus.ACKNOWLEDGED, AlertStatus.CLOSED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.CLOSED},
    AlertStatus.CLOSED: set(),  # Terminal state
}
