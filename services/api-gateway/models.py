"""Pydantic models for the AAP API Gateway (DETECT-004)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AffectedResource(BaseModel):
    """A single Azure resource affected by an incident."""

    resource_id: str = Field(
        ...,
        description="Full ARM resource ID (e.g., /subscriptions/.../resourceGroups/.../providers/...)",
        min_length=1,
    )
    subscription_id: str = Field(
        ...,
        description="Azure subscription ID containing the resource",
    )
    resource_type: str = Field(
        ...,
        description="ARM resource type (e.g., Microsoft.Compute/virtualMachines)",
    )


class IncidentPayload(BaseModel):
    """Structured incident payload for POST /api/v1/incidents.

    Matches the DETECT-004 contract: incident_id, severity, domain,
    affected_resources, detection_rule, kql_evidence.
    """

    incident_id: str = Field(
        ...,
        description="Unique incident identifier",
        min_length=1,
    )
    severity: str = Field(
        ...,
        description="Incident severity level",
        pattern=r"^Sev[0-3]$",
    )
    domain: str = Field(
        ...,
        description="Target domain for routing",
        pattern=r"^(compute|network|storage|security|arc|sre)$",
    )
    affected_resources: list[AffectedResource] = Field(
        ...,
        description="List of affected Azure resources",
        min_length=1,
    )
    detection_rule: str = Field(
        ...,
        description="Name of the detection rule that fired",
    )
    kql_evidence: Optional[str] = Field(
        default=None,
        description="KQL query results that triggered the alert",
    )
    title: Optional[str] = Field(
        default=None,
        description="Human-readable incident title",
    )
    description: Optional[str] = Field(
        default=None,
        description="Detailed incident description",
    )


class IncidentResponse(BaseModel):
    """Response returned after incident ingestion."""

    thread_id: str
    status: str = "dispatched"


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "1.0.0"
