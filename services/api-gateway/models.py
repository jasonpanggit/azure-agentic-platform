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


class RunbookResult(BaseModel):
    """Runbook search result from pgvector cosine similarity (TRIAGE-005)."""

    id: str
    title: str
    domain: str
    version: str
    similarity: float
    content_excerpt: str


class ChatRequest(BaseModel):
    """Operator-initiated chat message (D-06, TEAMS-004)."""

    message: str = Field(..., description="Operator message text", min_length=1)
    incident_id: Optional[str] = Field(
        default=None, description="Optionally attach to existing incident"
    )
    thread_id: Optional[str] = Field(
        default=None, description="Continue an existing Foundry thread (TEAMS-004)"
    )
    user_id: Optional[str] = Field(
        default=None, description="Operator UPN from Teams activity (D-07)"
    )
    subscription_ids: Optional[list[str]] = Field(
        default=None,
        description="Azure subscription IDs selected in the UI (injected as context)",
    )


class ChatResponse(BaseModel):
    """Response returned after chat thread creation."""

    thread_id: str
    status: str = "created"


class ChatResultResponse(BaseModel):
    """Response returned by GET /api/v1/chat/{thread_id}/result.

    Indicates whether the Foundry run is still in progress or has
    completed, and includes the assistant's reply when done.
    """

    thread_id: str
    run_status: str  # queued | in_progress | completed | failed | cancelled | expired
    reply: Optional[str] = None  # populated when run_status == "completed"


class ApprovalAction(BaseModel):
    """Payload for approve/reject actions (D-09, TEAMS-003)."""

    decided_by: str = Field(..., description="UPN or object ID of the operator")
    scope_confirmed: Optional[bool] = Field(
        default=None, description="Required True for prod subscriptions (REMEDI-006)"
    )
    thread_id: Optional[str] = Field(
        default=None, description="Thread ID from card data (TEAMS-003 Action.Execute)"
    )


class ApprovalResponse(BaseModel):
    """Response returned after approve/reject."""

    approval_id: str
    status: str  # approved, rejected, expired, error


class ApprovalRecord(BaseModel):
    """Full approval record from Cosmos DB (D-12)."""

    id: str
    action_id: str
    thread_id: str
    incident_id: Optional[str] = None
    agent_name: str
    status: str  # pending, approved, rejected, expired, executed, aborted
    risk_level: str
    proposed_at: str
    expires_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    executed_at: Optional[str] = None
    abort_reason: Optional[str] = None
    resource_snapshot: Optional[dict] = None
    proposal: dict


class IncidentSummary(BaseModel):
    """Summary of an incident for the alert feed (UI-006)."""

    incident_id: str
    severity: str
    domain: str
    status: str
    created_at: str
    title: Optional[str] = None
    resource_id: Optional[str] = None
    subscription_id: Optional[str] = None


class AuditEntry(BaseModel):
    """Single audit log entry from Application Insights (AUDIT-004)."""

    timestamp: str
    agent: str
    tool: str
    outcome: str
    duration_ms: float
    properties: Optional[str] = None


class AuditExportResponse(BaseModel):
    """Remediation activity report for SOC 2 audit (AUDIT-006)."""

    report_metadata: dict
    remediation_events: list[dict]
