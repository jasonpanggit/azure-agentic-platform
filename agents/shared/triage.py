"""Triage diagnosis and remediation proposal data structures (TRIAGE-002, TRIAGE-003, TRIAGE-004).

Provides typed containers for structured domain-agent diagnoses and remediation
proposals. All domain agents (compute, network, storage, security, sre) MUST
return a TriageDiagnosis with a confidence score and evidence list before
proposing any remediation action.

Requirements:
    TRIAGE-002: Mandatory Log Analytics + Resource Health before diagnosis.
    TRIAGE-003: Activity Log check as the first RCA step (prior 2 hours).
    TRIAGE-004: Confidence score (0.0–1.0) required in every diagnosis.
    REMEDI-001: All remediation proposals require explicit human approval.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from agents.shared.envelope import IncidentMessage


class TriageDiagnosis:
    """Structured root-cause diagnosis produced by a domain agent.

    Every domain agent MUST produce a TriageDiagnosis before proposing
    any remediation action. The diagnosis encapsulates the hypothesis,
    supporting evidence, confidence score, and cross-domain routing
    signals (TRIAGE-002, TRIAGE-003, TRIAGE-004).

    Attributes:
        hypothesis: Natural-language description of the root cause.
        evidence: List of supporting evidence items (log excerpts, metric
            values, resource health states, Activity Log entries).
        confidence_score: Float between 0.0 and 1.0 inclusive (TRIAGE-004).
        domain: Originating domain agent name (e.g., "compute", "network").
        affected_resources: List of Azure resource IDs under investigation.
        activity_log_findings: Activity Log entries from the prior 2 hours
            checked as the mandatory first RCA step (TRIAGE-003).
        resource_health_status: Azure Resource Health AvailabilityState
            (e.g., "Available", "Degraded", "Unavailable"). Required before
            finalizing diagnosis (TRIAGE-002).
        needs_cross_domain: True if evidence points to a root cause in
            another domain. The Orchestrator will re-route accordingly.
        suspected_domain: The domain to route to when needs_cross_domain
            is True (e.g., "network", "storage", "sre").
        remediation_proposal: Optional RemediationProposal dict produced
            when a clear remediation path exists (REMEDI-001).
    """

    def __init__(
        self,
        hypothesis: str,
        evidence: List[str],
        confidence_score: float,
        domain: str,
        affected_resources: List[str],
        activity_log_findings: Optional[List[str]] = None,
        resource_health_status: Optional[str] = None,
        needs_cross_domain: bool = False,
        suspected_domain: Optional[str] = None,
        remediation_proposal: Optional[dict] = None,
    ) -> None:
        if not (0.0 <= confidence_score <= 1.0):
            raise ValueError(
                f"confidence_score must be between 0.0 and 1.0 inclusive, "
                f"got {confidence_score}"
            )
        self.hypothesis = hypothesis
        self.evidence = evidence
        self.confidence_score = confidence_score
        self.domain = domain
        self.affected_resources = affected_resources
        self.activity_log_findings = activity_log_findings or []
        self.resource_health_status = resource_health_status
        self.needs_cross_domain = needs_cross_domain
        self.suspected_domain = suspected_domain
        self.remediation_proposal = remediation_proposal

    def to_dict(self) -> dict:
        """Return plain dict representation of this diagnosis."""
        return {
            "hypothesis": self.hypothesis,
            "evidence": self.evidence,
            "confidence_score": self.confidence_score,
            "domain": self.domain,
            "affected_resources": self.affected_resources,
            "activity_log_findings": self.activity_log_findings,
            "resource_health_status": self.resource_health_status,
            "needs_cross_domain": self.needs_cross_domain,
            "suspected_domain": self.suspected_domain,
            "remediation_proposal": self.remediation_proposal,
        }

    def to_envelope(
        self,
        correlation_id: str,
        thread_id: str,
        source_agent: str,
        target_agent: str = "orchestrator",
    ) -> IncidentMessage:
        """Return this diagnosis as a typed IncidentMessage envelope.

        Args:
            correlation_id: Incident correlation ID preserved from the
                original incident handoff (AUDIT-001).
            thread_id: Foundry thread ID for this conversation.
            source_agent: Name of the agent that produced this diagnosis.
            target_agent: Recipient agent (default: "orchestrator").

        Returns:
            IncidentMessage with message_type="diagnosis_complete" and
            all diagnosis fields serialised into the payload.
        """
        return IncidentMessage(
            correlation_id=correlation_id,
            thread_id=thread_id,
            source_agent=source_agent,
            target_agent=target_agent,
            message_type="diagnosis_complete",
            payload=self.to_dict(),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class RemediationProposal:
    """A proposed remediation action for a diagnosed incident.

    All remediation proposals MUST set requires_approval=True and
    MUST NOT be executed without explicit human approval (REMEDI-001).

    Attributes:
        description: Human-readable description of the proposed action.
        target_resources: List of Azure resource IDs to be affected.
        estimated_impact: Human-readable impact description
            (e.g., "~2 min downtime", "rolling restart ~5 min").
        risk_level: One of "low", "medium", "high", "critical".
        reversibility: Human-readable reversibility description
            (e.g., "reversible", "irreversible — credentials must be reissued").
        action_type: Machine-readable action category
            (e.g., "restart", "rollback", "rbac_change", "scale").
    """

    VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

    def __init__(
        self,
        description: str,
        target_resources: List[str],
        estimated_impact: str,
        risk_level: str,
        reversibility: str,
        action_type: str,
    ) -> None:
        if risk_level not in self.VALID_RISK_LEVELS:
            raise ValueError(
                f"risk_level must be one of {sorted(self.VALID_RISK_LEVELS)}, "
                f"got '{risk_level}'"
            )
        self.description = description
        self.target_resources = target_resources
        self.estimated_impact = estimated_impact
        self.risk_level = risk_level
        self.reversibility = reversibility
        self.action_type = action_type

    def to_dict(self) -> dict:
        """Return proposal dict with mandatory requires_approval flag (REMEDI-001)."""
        return {
            "description": self.description,
            "target_resources": self.target_resources,
            "estimated_impact": self.estimated_impact,
            "risk_level": self.risk_level,
            "reversibility": self.reversibility,
            "action_type": self.action_type,
            # REMEDI-001: All remediation proposals require explicit human approval.
            # No remediation action may be executed without operator confirmation.
            "requires_approval": True,
        }


class ResourceSnapshot:
    """Pre-execution resource state snapshot for Resource Identity Certainty (REMEDI-004).

    Captures 2+ independent signals about a resource at proposal time.
    Before execution, the snapshot is re-verified. If any signal has diverged,
    the action is aborted with stale_approval.
    """

    def __init__(
        self,
        resource_id: str,
        provisioning_state: str,
        tags: dict,
        resource_health: str,
        captured_at: Optional[str] = None,
    ) -> None:
        self.resource_id = resource_id
        self.provisioning_state = provisioning_state
        self.tags = tags
        self.resource_health = resource_health
        self.captured_at = captured_at or datetime.now(timezone.utc).isoformat()
        self.snapshot_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute SHA-256 hash of resource state fields."""
        state_string = (
            f"{self.resource_id}|"
            f"{self.provisioning_state}|"
            f"{json.dumps(self.tags, sort_keys=True)}|"
            f"{self.resource_health}"
        )
        return hashlib.sha256(state_string.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "resource_id": self.resource_id,
            "provisioning_state": self.provisioning_state,
            "tags": self.tags,
            "resource_health": self.resource_health,
            "snapshot_hash": self.snapshot_hash,
            "captured_at": self.captured_at,
        }
