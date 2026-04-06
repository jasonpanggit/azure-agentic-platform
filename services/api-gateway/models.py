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
        pattern=r"^(compute|network|storage|security|arc|sre|patch|eol)$",
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
    blast_radius_summary: Optional[dict] = Field(
        default=None,
        description=(
            "Topology blast-radius summary for the primary affected resource. "
            "Populated when topology service is available (TOPO-004). "
            "Fields: resource_id, total_affected, hop_counts, affected_resources."
        ),
    )
    suppressed: Optional[bool] = Field(
        default=None,
        description="True when this incident was suppressed as a downstream cascade (INTEL-001).",
    )
    parent_incident_id: Optional[str] = Field(
        default=None,
        description="incident_id of the parent incident that caused suppression.",
    )
    composite_severity: Optional[str] = Field(
        default=None,
        description=(
            "Re-weighted severity combining base severity, blast radius size, "
            "and domain SLO risk (INTEL-001). One of: Sev0, Sev1, Sev2, Sev3."
        ),
    )


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
    run_id: Optional[str] = None
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
    """Payload for approve/reject actions (D-09, TEAMS-003, PLATINT-003)."""

    decided_by: str = Field(..., description="UPN or object ID of the operator")
    scope_confirmed: Optional[bool] = Field(
        default=None, description="Required True for prod subscriptions (REMEDI-006)"
    )
    thread_id: Optional[str] = Field(
        default=None, description="Thread ID from card data (TEAMS-003 Action.Execute)"
    )
    feedback_text: Optional[str] = Field(
        default=None, description="Free-text operator feedback on the proposal quality (PLATINT-003)"
    )
    feedback_tags: Optional[list[str]] = Field(
        default=None, description="Structured feedback tags, e.g. ['false_positive', 'not_useful'] (PLATINT-003)"
    )


class ApprovalResponse(BaseModel):
    """Response returned after approve/reject."""

    approval_id: str
    status: str  # approved, rejected, expired, error


class ApprovalCreateRequest(BaseModel):
    """Request body for POST /api/v1/approvals (synthetic approval injection for ops/demos)."""

    thread_id: str
    incident_id: str
    agent_name: str = "compute-agent"
    proposal: dict
    resource_snapshot: dict = {}
    risk_level: str = "low"
    timeout_minutes: Optional[int] = None


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


class ChangeCorrelation(BaseModel):
    """A single Azure resource change correlated with an incident (INTEL-002)."""

    change_id: str = Field(
        ...,
        description="Activity Log event ID (correlationId or eventDataId)",
    )
    operation_name: str = Field(
        ...,
        description="ARM operation name, e.g. 'Microsoft.Compute/virtualMachines/write'",
    )
    resource_id: str = Field(
        ...,
        description="Full ARM resource ID of the changed resource",
    )
    resource_name: str = Field(
        ...,
        description="Last path segment of resource_id (human-readable name)",
    )
    caller: Optional[str] = Field(
        default=None,
        description="UPN or object ID of the principal who made the change",
    )
    changed_at: str = Field(
        ...,
        description="ISO 8601 timestamp when the change occurred",
    )
    delta_minutes: float = Field(
        ...,
        description="Minutes before the incident was created (positive = before incident)",
    )
    topology_distance: int = Field(
        ...,
        description="BFS hop count from incident resource: 0 = same resource, 1 = direct neighbor, etc.",
    )
    change_type_score: float = Field(
        ...,
        description="Score 0.0–1.0 based on the operation type",
    )
    correlation_score: float = Field(
        ...,
        description="Overall weighted score 0.0–1.0: w_temporal*temporal + w_topology*topology + w_change_type*change_type",
    )
    status: str = Field(
        ...,
        description="Activity Log event status: 'Succeeded' | 'Failed' | 'Started'",
    )


class HistoricalMatch(BaseModel):
    """A single historical incident match from pgvector cosine similarity (INTEL-003)."""

    incident_id: str = Field(..., description="ID of the matching historical incident")
    domain: str = Field(..., description="Domain of the historical incident")
    severity: str = Field(..., description="Severity of the historical incident")
    title: Optional[str] = Field(default=None, description="Title of the historical incident")
    similarity: float = Field(..., description="Cosine similarity score (0.0–1.0)")
    resolution_excerpt: Optional[str] = Field(
        default=None, description="First 300 chars of the resolution that fixed it"
    )
    resolved_at: str = Field(..., description="ISO 8601 timestamp when the incident was resolved")


class IncidentSummary(BaseModel):
    """Summary of an incident for the alert feed (UI-006)."""

    incident_id: str
    severity: str
    domain: str
    status: str
    created_at: str
    title: Optional[str] = None
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None        # last segment of resource_id
    resource_group: Optional[str] = None       # resource group from resource_id
    resource_type: Optional[str] = None        # e.g. "microsoft.compute/virtualmachines"
    subscription_id: Optional[str] = None
    investigation_status: Optional[str] = None  # pending | evidence_ready | investigating | resolved
    evidence_collected_at: Optional[str] = None
    top_changes: Optional[list["ChangeCorrelation"]] = Field(
        default=None,
        description=(
            "Top-3 Azure resource changes correlated with this incident. "
            "Populated by the change_correlator BackgroundTask within 30 seconds "
            "of incident ingestion (INTEL-002)."
        ),
    )
    composite_severity: Optional[str] = Field(
        default=None,
        description=(
            "Re-weighted severity combining base severity, blast radius size, "
            "and domain SLO risk (INTEL-001). One of: Sev0, Sev1, Sev2, Sev3."
        ),
    )
    suppressed: Optional[bool] = Field(
        default=None,
        description="True when this incident was suppressed as a downstream cascade.",
    )
    parent_incident_id: Optional[str] = Field(
        default=None,
        description="incident_id of the parent incident that caused suppression.",
    )
    historical_matches: Optional[list[HistoricalMatch]] = Field(
        default=None,
        description=(
            "Top-3 historical incidents with similar pattern. "
            "Populated within 10s of ingestion by BackgroundTask (INTEL-003)."
        ),
    )
    slo_escalated: Optional[bool] = Field(
        default=None,
        description="True when severity was escalated to Sev0 due to domain SLO burn-rate alert.",
    )


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


class SLODefinition(BaseModel):
    """A Service Level Objective definition with current health metrics (INTEL-004)."""

    id: str = Field(..., description="Unique SLO identifier (UUID)")
    name: str = Field(..., description="Human-readable SLO name, e.g. 'Compute API Availability'")
    domain: str = Field(..., description="Domain this SLO applies to (compute, network, etc.)")
    metric: str = Field(
        ..., description="Metric type: error_rate | latency_p99 | availability"
    )
    target_pct: float = Field(..., description="Target percentage, e.g. 99.9")
    window_hours: int = Field(..., description="Rolling evaluation window in hours")
    current_value: Optional[float] = Field(
        default=None, description="Last measured metric value"
    )
    error_budget_pct: Optional[float] = Field(
        default=None,
        description="Remaining error budget as percentage: (current_value / target_pct) * 100",
    )
    burn_rate_1h: Optional[float] = Field(
        default=None, description="Error budget consumption rate over last 1 hour"
    )
    burn_rate_15min: Optional[float] = Field(
        default=None, description="Error budget consumption rate over last 15 minutes"
    )
    status: str = Field(
        default="healthy",
        description="healthy | burn_rate_alert | budget_exhausted",
    )
    created_at: Optional[str] = Field(default=None, description="ISO 8601 creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="ISO 8601 last-updated timestamp")


class SLOHealth(BaseModel):
    """SLO health snapshot returned by GET /api/v1/slos/{slo_id}/health (INTEL-004)."""

    slo_id: str
    status: str  # healthy | burn_rate_alert | budget_exhausted
    error_budget_pct: Optional[float] = None
    burn_rate_1h: Optional[float] = None
    burn_rate_15min: Optional[float] = None
    alert: bool = Field(
        ...,
        description="True when burn_rate_1h > 2.0 OR burn_rate_15min > 3.0",
    )


class SLOCreateRequest(BaseModel):
    """Request body for POST /api/v1/slos."""

    name: str = Field(..., min_length=1)
    domain: str = Field(..., description="compute | network | storage | security | arc | sre")
    metric: str = Field(..., description="error_rate | latency_p99 | availability")
    target_pct: float = Field(..., gt=0.0, le=100.0)
    window_hours: int = Field(..., gt=0)


class MetricForecast(BaseModel):
    """Capacity forecast for a single metric on a single resource (INTEL-005)."""

    metric_name: str = Field(..., description="Azure Monitor metric name")
    current_value: float = Field(..., description="Smoothed current level from Holt's method")
    threshold: float = Field(..., description="Capacity threshold that triggers a breach")
    trend_per_interval: float = Field(
        ..., description="Trend per 5-minute interval from Holt smoothing"
    )
    time_to_breach_minutes: Optional[float] = Field(
        default=None,
        description=(
            "Estimated minutes until threshold breach. "
            "None when metric is stable or declining away from threshold."
        ),
    )
    confidence: str = Field(
        ...,
        description="Forecast confidence based on hold-out MAPE: high (<15%) | medium (<30%) | low",
    )
    mape: float = Field(
        ..., description="Mean Absolute Percentage Error from hold-out validation (0–100)"
    )
    last_updated: str = Field(..., description="ISO 8601 UTC timestamp of last sweep")
    breach_imminent: bool = Field(
        ...,
        description="True when time_to_breach_minutes < FORECAST_BREACH_ALERT_MINUTES (60 min)",
    )


class ForecastResult(BaseModel):
    """All capacity forecasts for a single Azure resource (INTEL-005)."""

    resource_id: str = Field(..., description="ARM resource ID")
    resource_type: str = Field(..., description="ARM resource type (lowercased)")
    forecasts: list[MetricForecast] = Field(
        default_factory=list, description="Per-metric forecasts"
    )
    has_imminent_breach: bool = Field(
        ...,
        description="True when any metric has breach_imminent=True",
    )


class RemediationAuditRecord(BaseModel):
    """WAL and immutable audit record written to Cosmos remediation_audit (REMEDI-011, REMEDI-013)."""

    id: str                                       # execution_id (UUID)
    incident_id: str
    approval_id: str
    thread_id: str
    action_type: str                              # "execute" | "rollback"
    proposed_action: str                          # "restart_vm" | "deallocate_vm" | "start_vm" | "resize_vm"
    resource_id: str
    executed_by: str                              # UPN from approval record (decided_by)
    executed_at: str                              # ISO 8601 UTC
    status: str                                   # "pending" | "complete" | "failed"
    verification_result: Optional[str] = None    # "RESOLVED" | "IMPROVED" | "DEGRADED" | "TIMEOUT"
    verified_at: Optional[str] = None
    rolled_back: bool = False
    rollback_execution_id: Optional[str] = None
    preflight_blast_radius_size: int
    wal_written_at: str                           # ISO 8601 UTC — written BEFORE ARM call


class RemediationResult(BaseModel):
    """Result returned by execute_remediation to the API endpoint (REMEDI-009, REMEDI-010)."""

    execution_id: str
    status: str                                   # "complete" | "failed" | "aborted"
    verification_scheduled: bool
    preflight_passed: bool
    blast_radius_size: int
    abort_reason: Optional[str] = None           # populated when status="aborted"


class BusinessTier(BaseModel):
    """Operator-configured revenue tier for FinOps cost impact tracking (PLATINT-004)."""

    id: str
    tier_name: str
    monthly_revenue_usd: float
    resource_tags: dict
    created_at: str
    updated_at: str


class IncidentPattern(BaseModel):
    """A single recurring incident pattern identified by the pattern analyzer (PLATINT-001)."""

    pattern_id: str
    domain: str
    resource_type: Optional[str] = None
    detection_rule: Optional[str] = None
    incident_count: int
    frequency_per_week: float
    avg_severity_score: float
    top_title_words: list[str]
    first_seen: str
    last_seen: str
    operator_flagged: bool = False
    common_feedback: list[str] = []


class PatternAnalysisResult(BaseModel):
    """Weekly pattern analysis output stored in Cosmos pattern_analysis container (PLATINT-001)."""

    analysis_id: str
    analysis_date: str
    period_days: int
    total_incidents_analyzed: int
    top_patterns: list[IncidentPattern]
    finops_summary: dict
    generated_at: str


class PlatformHealth(BaseModel):
    """Platform-wide health metrics aggregated from existing data sources (PLATINT-004)."""

    detection_pipeline_lag_seconds: Optional[float] = None
    auto_remediation_success_rate: Optional[float] = None
    noise_reduction_pct: Optional[float] = None
    slo_compliance_pct: Optional[float] = None
    automation_savings_count: int = 0
    agent_p50_ms: Optional[float] = None
    agent_p95_ms: Optional[float] = None
    error_budget_portfolio: list[dict] = []
    generated_at: str


class BusinessTiersResponse(BaseModel):
    """Response wrapper for GET /api/v1/admin/business-tiers (PLATINT-004)."""

    tiers: list[BusinessTier]
