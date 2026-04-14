"""Integration tests for HandoffOrchestrator routing (AGENT-001, TRIAGE-001).

Validates ROADMAP Phase 2 Success Criterion 2:
POST /api/v1/incidents with synthetic payload creates a Foundry thread,
dispatches to Orchestrator, and Orchestrator routes to correct domain agent
via HandoffOrchestrator — confirmed by tracing the handoff chain.
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.orchestrator.agent import (
    DOMAIN_AGENT_MAP,
    classify_incident_domain,
    create_orchestrator,
)
from agents.shared.envelope import IncidentMessage, validate_envelope


@pytest.mark.integration
class TestHandoffOrchestrator:
    """Verify Orchestrator classifies and routes incidents correctly."""

    def test_domain_agent_map_has_all_eight_domains(self):
        """DOMAIN_AGENT_MAP must contain all 12 domains (including messaging added in Phase 49)."""
        expected_domains = {
            "compute", "network", "storage", "security", "sre", "arc", "patch", "eol",
            "database", "app-service", "container-apps", "messaging",
        }
        assert set(DOMAIN_AGENT_MAP.keys()) == expected_domains

    def test_classify_compute_resource(self):
        """Compute resource is classified to compute domain."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"
            ],
            detection_rule="high-cpu-alert",
        )
        assert result["domain"] == "compute"

    def test_classify_network_resource(self):
        """Network resource is classified to network domain."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Network/virtualNetworks/vnet-1"
            ],
            detection_rule="nsg-block-alert",
        )
        assert result["domain"] == "network"

    def test_classify_storage_resource(self):
        """Storage resource is classified to storage domain."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Storage/storageAccounts/sa1"
            ],
            detection_rule="storage-throttle",
        )
        assert result["domain"] == "storage"

    def test_classify_security_resource(self):
        """Security resource (Key Vault) is classified to security domain."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.KeyVault/vaults/kv-1"
            ],
            detection_rule="key-vault-anomaly",
        )
        assert result["domain"] == "security"

    def test_classify_arc_resource(self):
        """Arc resource is classified to arc domain."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.HybridCompute/machines/arc-vm-1"
            ],
            detection_rule="arc-disconnect",
        )
        assert result["domain"] == "arc"

    def test_classify_unknown_defaults_to_sre(self):
        """Unknown resource type defaults to SRE domain."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Custom/things/thing-1"
            ],
            detection_rule="unknown-alert",
        )
        assert result["domain"] == "sre"

    def test_classify_returns_confidence_field(self):
        """Classification result includes confidence field."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"
            ],
            detection_rule="high-cpu-alert",
        )
        assert "confidence" in result
        assert result["confidence"] in {"high", "medium", "low"}

    def test_classify_returns_reason_field(self):
        """Classification result includes a reason field."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Storage/storageAccounts/sa1"
            ],
            detection_rule="storage-throttle",
        )
        assert "reason" in result
        assert isinstance(result["reason"], str)

    def test_handoff_message_uses_typed_envelope(self):
        """Handoff message conforms to IncidentMessage envelope (AGENT-002)."""
        envelope = {
            "correlation_id": "inc-001",
            "thread_id": "thread-abc",
            "source_agent": "orchestrator",
            "target_agent": "compute-agent",
            "message_type": "incident_handoff",
            "payload": {"severity": "Sev1", "domain": "compute"},
            "timestamp": "2026-03-26T14:00:00Z",
        }
        result = validate_envelope(envelope)
        assert result["message_type"] == "incident_handoff"
        assert result["target_agent"] == "compute-agent"

    def test_cross_domain_rerouting_envelope(self):
        """Cross-domain re-routing uses typed envelope with cross_domain_request type."""
        envelope = {
            "correlation_id": "inc-001",
            "thread_id": "thread-abc",
            "source_agent": "compute-agent",
            "target_agent": "orchestrator",
            "message_type": "cross_domain_request",
            "payload": {
                "needs_cross_domain": True,
                "original_domain": "compute",
                "suspected_domain": "network",
                "evidence": "NIC disconnected events in activity log",
            },
            "timestamp": "2026-03-26T14:05:00Z",
        }
        result = validate_envelope(envelope)
        assert result["message_type"] == "cross_domain_request"
        assert result["payload"]["needs_cross_domain"] is True

    def test_classify_empty_resources_defaults_to_sre(self):
        """Empty affected_resources list defaults to SRE domain with low confidence."""
        result = classify_incident_domain(
            affected_resources=[],
            detection_rule="unknown",
        )
        assert result["domain"] == "sre"
        assert result["confidence"] == "low"

    def test_classify_arc_enabled_servers_query_to_arc(self):
        """Conversational Arc server queries must not be routed to compute."""
        result = classify_incident_domain(
            affected_resources=[],
            detection_rule="show my arc enabled servers",
        )
        assert result["domain"] == "arc"
        assert result["confidence"] == "medium"

    @pytest.mark.parametrize(
        "query_text",
        [
            "list my arc servers",
            "show azure arc machines",
            "find connected clusters managed by arc",
        ],
    )
    def test_classify_arc_conversational_variants(self, query_text: str):
        """Arc-specific conversational variants must classify to arc."""
        result = classify_incident_domain(
            affected_resources=[],
            detection_rule=query_text,
        )
        assert result["domain"] == "arc"

    def test_domain_agent_map_values_are_agent_names(self):
        """Each domain maps to a properly named agent tool string (underscore format)."""
        for domain, agent_name in DOMAIN_AGENT_MAP.items():
            assert isinstance(agent_name, str)
            assert agent_name.endswith("_agent"), (
                f"Domain '{domain}' maps to '{agent_name}' — expected '_agent' suffix"
            )

    def test_classify_maintenance_resource(self):
        """Maintenance resource (Update Manager) is classified to patch domain."""
        result = classify_incident_domain(
            affected_resources=[
                "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Maintenance/maintenanceConfigurations/mc-1"
            ],
            detection_rule="patch-compliance-drift",
        )
        assert result["domain"] == "patch"

    @pytest.mark.parametrize(
        "query_text",
        [
            "show patch compliance status",
            "which machines have missing patches",
            "check update manager assessment results",
            "find machines pending reboot after patching",
        ],
    )
    def test_classify_patch_conversational_variants(self, query_text: str):
        """Patch-related conversational variants must classify to patch."""
        result = classify_incident_domain(
            affected_resources=[],
            detection_rule=query_text,
        )
        assert result["domain"] == "patch"

    def test_classify_generic_update_does_not_route_to_patch(self):
        """Generic 'update' should NOT route to patch (D-12 exclusion)."""
        result = classify_incident_domain(
            affected_resources=[],
            detection_rule="update my vm size to standard_d4",
        )
        # Should route to compute (mentions "vm") or sre, NOT patch
        assert result["domain"] != "patch"
