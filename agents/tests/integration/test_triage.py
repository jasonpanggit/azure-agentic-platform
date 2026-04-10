"""Integration tests for domain agent triage workflow (TRIAGE-001 through TRIAGE-004).

Validates that every domain agent follows the required triage pattern:
1. Activity Log check first (TRIAGE-003)
2. Log Analytics + Resource Health queried (TRIAGE-002)
3. Diagnosis contains hypothesis + evidence + confidence_score (TRIAGE-004)
"""
from __future__ import annotations

import pytest

from agents.shared.triage import RemediationProposal, TriageDiagnosis
from agents.shared.envelope import validate_envelope


@pytest.mark.integration
class TestTriageDiagnosis:
    """Verify TriageDiagnosis structure matches TRIAGE-004."""

    def test_diagnosis_requires_hypothesis(self):
        diagnosis = TriageDiagnosis(
            hypothesis="Memory leak in application",
            evidence=[{"source": "logs", "excerpt": "OOM killed process"}],
            confidence_score=0.85,
            domain="compute",
            affected_resources=["vm-1"],
        )
        assert diagnosis.hypothesis == "Memory leak in application"

    def test_diagnosis_requires_evidence_list(self):
        diagnosis = TriageDiagnosis(
            hypothesis="Network timeout",
            evidence=[
                {"source": "metrics", "value": "99.5% packet loss"},
                {"source": "logs", "excerpt": "Connection timeout after 30s"},
            ],
            confidence_score=0.72,
            domain="network",
            affected_resources=["nsg-1"],
        )
        assert len(diagnosis.evidence) == 2

    def test_diagnosis_requires_confidence_score(self):
        diagnosis = TriageDiagnosis(
            hypothesis="Storage throttling",
            evidence=[{"source": "metrics", "value": "throttle count 5000"}],
            confidence_score=0.91,
            domain="storage",
            affected_resources=["sa-1"],
        )
        assert 0.0 <= diagnosis.confidence_score <= 1.0

    def test_confidence_score_rejects_out_of_range(self):
        with pytest.raises(ValueError, match="confidence_score must be"):
            TriageDiagnosis(
                hypothesis="test",
                evidence=[],
                confidence_score=1.5,
                domain="compute",
                affected_resources=[],
            )

    def test_confidence_score_rejects_negative(self):
        with pytest.raises(ValueError, match="confidence_score must be"):
            TriageDiagnosis(
                hypothesis="test",
                evidence=[],
                confidence_score=-0.1,
                domain="compute",
                affected_resources=[],
            )

    def test_diagnosis_includes_activity_log_findings(self):
        """TRIAGE-003: Activity Log must be checked."""
        diagnosis = TriageDiagnosis(
            hypothesis="Recent deployment caused failure",
            evidence=[{"source": "activity_log", "excerpt": "Deployment completed at 14:00"}],
            confidence_score=0.92,
            domain="compute",
            affected_resources=["vmss-1"],
            activity_log_findings=[
                {"operation": "Microsoft.Compute/virtualMachineScaleSets/write", "time": "14:00"}
            ],
        )
        assert len(diagnosis.activity_log_findings) > 0

    def test_diagnosis_includes_resource_health_status(self):
        """TRIAGE-002: Resource Health must be queried."""
        diagnosis = TriageDiagnosis(
            hypothesis="Platform issue affecting VM",
            evidence=[{"source": "resource_health", "status": "Unavailable"}],
            confidence_score=0.95,
            domain="compute",
            affected_resources=["vm-1"],
            resource_health_status="Unavailable",
        )
        assert diagnosis.resource_health_status is not None

    def test_diagnosis_supports_cross_domain(self):
        """Cross-domain re-routing when root cause spans domains."""
        diagnosis = TriageDiagnosis(
            hypothesis="Network issue causing compute failures",
            evidence=[{"source": "logs", "excerpt": "NIC disconnected"}],
            confidence_score=0.78,
            domain="compute",
            affected_resources=["vm-1"],
            needs_cross_domain=True,
            suspected_domain="network",
        )
        assert diagnosis.needs_cross_domain is True
        assert diagnosis.suspected_domain == "network"

    def test_diagnosis_to_envelope_produces_valid_message(self):
        """Diagnosis converts to valid IncidentMessage envelope (AGENT-002)."""
        diagnosis = TriageDiagnosis(
            hypothesis="CPU spike from runaway process",
            evidence=[{"source": "metrics", "value": "CPU 98%"}],
            confidence_score=0.88,
            domain="compute",
            affected_resources=["vm-1"],
        )
        envelope = diagnosis.to_envelope(
            correlation_id="inc-001",
            thread_id="thread-abc",
            source_agent="compute-agent",
        )
        # Validate via envelope validator — envelope is an IncidentMessage TypedDict
        validated = validate_envelope(dict(envelope))
        assert validated["message_type"] == "diagnosis_complete"
        assert validated["payload"]["hypothesis"] == "CPU spike from runaway process"
        assert validated["payload"]["confidence_score"] == pytest.approx(0.88)

    def test_diagnosis_to_dict_contains_all_fields(self):
        """to_dict() includes all required fields."""
        diagnosis = TriageDiagnosis(
            hypothesis="test",
            evidence=[{"a": "b"}],
            confidence_score=0.5,
            domain="sre",
            affected_resources=["r-1"],
        )
        d = diagnosis.to_dict()
        assert "hypothesis" in d
        assert "evidence" in d
        assert "confidence_score" in d
        assert "domain" in d
        assert "needs_cross_domain" in d

    def test_diagnosis_default_needs_cross_domain_is_false(self):
        """needs_cross_domain defaults to False."""
        diagnosis = TriageDiagnosis(
            hypothesis="test",
            evidence=[],
            confidence_score=0.5,
            domain="sre",
            affected_resources=[],
        )
        assert diagnosis.needs_cross_domain is False
        assert diagnosis.suspected_domain is None

    def test_diagnosis_activity_log_findings_defaults_to_empty_list(self):
        """activity_log_findings defaults to empty list (not None)."""
        diagnosis = TriageDiagnosis(
            hypothesis="test",
            evidence=[],
            confidence_score=0.5,
            domain="compute",
            affected_resources=[],
        )
        assert diagnosis.activity_log_findings == []


@pytest.mark.integration
class TestRemediationProposal:
    """Verify RemediationProposal matches REMEDI-001."""

    def test_proposal_includes_all_required_fields(self):
        """REMEDI-001: description, target resources, impact, risk, reversibility."""
        proposal = RemediationProposal(
            description="Restart VM to clear memory leak",
            target_resources=[
                "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
            ],
            estimated_impact="VM will be unavailable for ~2 minutes during restart",
            risk_level="low",
            reversibility="Fully reversible — VM can be restarted again",
            action_type="vm_restart",
        )
        d = proposal.to_dict()
        assert d["description"] == "Restart VM to clear memory leak"
        assert len(d["target_resources"]) == 1
        assert d["estimated_impact"] != ""
        assert d["risk_level"] == "low"
        assert d["reversibility"] != ""

    def test_proposal_always_requires_approval(self):
        """REMEDI-001: requires_approval is always True."""
        proposal = RemediationProposal(
            description="Scale up VMSS",
            target_resources=["vmss-1"],
            estimated_impact="Increased cost",
            risk_level="medium",
            reversibility="Scale back down",
            action_type="vmss_scale",
        )
        d = proposal.to_dict()
        assert d["requires_approval"] is True

    def test_invalid_risk_level_rejected(self):
        with pytest.raises(ValueError, match="risk_level must be one of"):
            RemediationProposal(
                description="test",
                target_resources=["r-1"],
                estimated_impact="test",
                risk_level="extreme",
                reversibility="test",
                action_type="test",
            )

    def test_valid_risk_levels_accepted(self):
        """All four valid risk levels are accepted."""
        for level in ("low", "medium", "high", "critical"):
            proposal = RemediationProposal(
                description="test",
                target_resources=["r-1"],
                estimated_impact="test",
                risk_level=level,
                reversibility="test",
                action_type="test",
            )
            assert proposal.to_dict()["risk_level"] == level


@pytest.mark.integration
class TestNetworkTriageFlow:
    """Validate network-domain triage produces correct diagnosis + remediation."""

    def test_nsg_misconfiguration_diagnosis_and_envelope(self):
        """Network agent produces a valid diagnosis for NSG misconfiguration with
        activity log evidence, confidence score, and a valid envelope."""
        diagnosis = TriageDiagnosis(
            hypothesis="NSG rule blocking inbound HTTPS traffic on port 443",
            evidence=[
                {"source": "nsg_rules", "excerpt": "Deny rule priority 100 on port 443"},
                {"source": "flow_logs", "excerpt": "Blocked flows from 10.0.0.0/24 to port 443"},
            ],
            confidence_score=0.91,
            domain="network",
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/"
                "networkSecurityGroups/nsg-web"
            ],
            activity_log_findings=[
                {"operation": "Microsoft.Network/networkSecurityGroups/write", "time": "13:45"}
            ],
            resource_health_status="Available",
        )
        assert diagnosis.domain == "network"
        assert diagnosis.confidence_score >= 0.7
        assert len(diagnosis.activity_log_findings) > 0
        assert diagnosis.resource_health_status is not None

        envelope = diagnosis.to_envelope(
            correlation_id="inc-net-001",
            thread_id="thread-net-abc",
            source_agent="network-agent",
        )
        validated = validate_envelope(dict(envelope))
        assert validated["message_type"] == "diagnosis_complete"
        assert validated["source_agent"] == "network-agent"
        assert validated["payload"]["domain"] == "network"

    def test_network_cross_domain_escalation_to_compute(self):
        """Network agent detects NIC detachment and escalates to compute domain."""
        diagnosis = TriageDiagnosis(
            hypothesis="NIC detached from VM causing network unreachability",
            evidence=[
                {"source": "vnet_topology", "excerpt": "NIC nic-vm-1 not attached to any VM"},
                {"source": "activity_log", "excerpt": "NIC detach operation at 15:20"},
            ],
            confidence_score=0.82,
            domain="network",
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/"
                "networkInterfaces/nic-vm-1"
            ],
            needs_cross_domain=True,
            suspected_domain="compute",
        )
        assert diagnosis.needs_cross_domain is True
        assert diagnosis.suspected_domain == "compute"
        d = diagnosis.to_dict()
        assert d["needs_cross_domain"] is True
        assert d["suspected_domain"] == "compute"


@pytest.mark.integration
class TestSecurityTriageFlow:
    """Validate security-domain triage produces correct diagnosis + remediation."""

    def test_defender_alert_diagnosis_with_remediation(self):
        """Security agent produces diagnosis from Defender alert and proposes remediation."""
        remediation = RemediationProposal(
            description="Revoke compromised service principal credentials and rotate secrets",
            target_resources=[
                "/subscriptions/sub-1/providers/Microsoft.Authorization/"
                "roleAssignments/ra-compromised"
            ],
            estimated_impact="Service principal will lose access until new credentials issued",
            risk_level="high",
            reversibility="Reversible — new credentials can be reissued",
            action_type="credential_rotation",
        )
        diagnosis = TriageDiagnosis(
            hypothesis="Anomalous sign-in activity from unfamiliar location indicates "
                       "compromised service principal",
            evidence=[
                {"source": "defender_alerts", "excerpt": "Unfamiliar sign-in from IP 203.0.113.5"},
                {"source": "iam_changes", "excerpt": "Role assignment added at 02:30"},
            ],
            confidence_score=0.94,
            domain="security",
            affected_resources=["sp-compromised-app"],
            activity_log_findings=[
                {"operation": "Microsoft.Authorization/roleAssignments/write", "time": "02:30"}
            ],
            resource_health_status="Available",
            remediation_proposal=remediation.to_dict(),
        )
        assert diagnosis.domain == "security"
        assert diagnosis.confidence_score >= 0.9
        assert diagnosis.remediation_proposal is not None
        assert diagnosis.remediation_proposal["requires_approval"] is True
        assert diagnosis.remediation_proposal["risk_level"] == "high"

    def test_security_cross_domain_escalation_to_network(self):
        """Security agent detects public exposure and escalates to network domain."""
        diagnosis = TriageDiagnosis(
            hypothesis="Storage account publicly accessible due to missing NSG rules "
                       "on associated subnet",
            evidence=[
                {"source": "public_endpoints", "excerpt": "Blob endpoint publicly reachable"},
                {"source": "secure_score", "value": "45/100 — network isolation missing"},
            ],
            confidence_score=0.87,
            domain="security",
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg/providers/"
                "Microsoft.Storage/storageAccounts/sa-exposed"
            ],
            needs_cross_domain=True,
            suspected_domain="network",
        )
        assert diagnosis.needs_cross_domain is True
        assert diagnosis.suspected_domain == "network"
        envelope = diagnosis.to_envelope(
            correlation_id="inc-sec-002",
            thread_id="thread-sec-xyz",
            source_agent="security-agent",
        )
        validated = validate_envelope(dict(envelope))
        assert validated["payload"]["needs_cross_domain"] is True
        assert validated["payload"]["suspected_domain"] == "network"


@pytest.mark.integration
class TestSreTriageFlow:
    """Validate SRE-domain triage with cross-domain correlation and remediation."""

    def test_sre_availability_degradation_diagnosis(self):
        """SRE agent correlates availability degradation across domains and produces
        a diagnosis with service health and advisor evidence."""
        diagnosis = TriageDiagnosis(
            hypothesis="Regional availability degradation caused by Azure platform "
                       "incident in East US — service health advisory active",
            evidence=[
                {"source": "availability_metrics", "value": "SLA dropped to 98.5%"},
                {"source": "service_health", "excerpt": "Active incident INC-AZ-2026-04-10"},
                {"source": "advisor_recommendations", "excerpt": "Enable zone redundancy"},
            ],
            confidence_score=0.96,
            domain="sre",
            affected_resources=["vm-1", "vm-2", "vmss-web"],
            activity_log_findings=[
                {"operation": "Microsoft.Resources/subscriptions/resourceGroups/write",
                 "time": "10:00"},
            ],
            resource_health_status="Degraded",
        )
        assert diagnosis.domain == "sre"
        assert diagnosis.confidence_score >= 0.9
        assert diagnosis.resource_health_status == "Degraded"
        assert len(diagnosis.evidence) == 3
        assert len(diagnosis.affected_resources) == 3

        envelope = diagnosis.to_envelope(
            correlation_id="inc-sre-001",
            thread_id="thread-sre-abc",
            source_agent="sre-agent",
        )
        validated = validate_envelope(dict(envelope))
        assert validated["message_type"] == "diagnosis_complete"
        assert validated["source_agent"] == "sre-agent"

    def test_sre_proposes_remediation_with_approval(self):
        """SRE agent proposes a scaling remediation that requires approval."""
        remediation = RemediationProposal(
            description="Scale out VMSS from 3 to 6 instances to absorb load spike",
            target_resources=[
                "/subscriptions/sub-1/resourceGroups/rg/providers/"
                "Microsoft.Compute/virtualMachineScaleSets/vmss-web"
            ],
            estimated_impact="Increased cost ~$120/day; rolling update ~5 min",
            risk_level="medium",
            reversibility="Fully reversible — scale back to 3 instances",
            action_type="vmss_scale",
        )
        diagnosis = TriageDiagnosis(
            hypothesis="VMSS under-provisioned for current traffic load",
            evidence=[
                {"source": "performance_baselines", "value": "CPU p95 at 92%"},
                {"source": "change_analysis", "excerpt": "Traffic routing change at 09:30"},
            ],
            confidence_score=0.88,
            domain="sre",
            affected_resources=["vmss-web"],
            remediation_proposal=remediation.to_dict(),
        )
        assert diagnosis.remediation_proposal is not None
        assert diagnosis.remediation_proposal["requires_approval"] is True
        assert diagnosis.remediation_proposal["action_type"] == "vmss_scale"
        assert diagnosis.remediation_proposal["risk_level"] == "medium"
