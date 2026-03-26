"""Unit tests for DetectionResults -> IncidentPayload mapping (DETECT-003)."""
from __future__ import annotations

import pytest

from payload_mapper import map_detection_result_to_incident_payload


class TestMapDetectionResultToIncidentPayload:
    def test_valid_mapping(self) -> None:
        dr = {
            "alert_id": "abc-123",
            "severity": "Sev1",
            "domain": "compute",
            "fired_at": "2026-03-26T12:00:00Z",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "subscription_id": "sub-1",
            "resource_name": "vm-1",
            "alert_rule": "High CPU",
            "description": "CPU above 90%",
            "kql_evidence": "Alert: High CPU on vm-1",
            "classified_at": "2026-03-26T12:00:05Z",
        }
        result = map_detection_result_to_incident_payload(dr)
        assert result["incident_id"] == "det-abc-123"
        assert result["severity"] == "Sev1"
        assert result["domain"] == "compute"
        assert len(result["affected_resources"]) == 1
        assert result["affected_resources"][0]["resource_id"] == dr["resource_id"]
        assert result["affected_resources"][0]["subscription_id"] == "sub-1"
        assert result["detection_rule"] == "High CPU"
        assert result["kql_evidence"] == "Alert: High CPU on vm-1"
        assert result["title"] == "High CPU on vm-1"

    def test_missing_alert_id_raises(self) -> None:
        with pytest.raises(ValueError, match="alert_id"):
            map_detection_result_to_incident_payload({"resource_id": "res-1"})

    def test_missing_resource_id_raises(self) -> None:
        with pytest.raises(ValueError, match="resource_id"):
            map_detection_result_to_incident_payload({"alert_id": "a-1"})

    def test_subscription_id_extracted_from_resource_id(self) -> None:
        dr = {
            "alert_id": "a-1",
            "resource_id": "/subscriptions/sub-99/resourceGroups/rg/providers/P/T/name",
            "resource_type": "P/T",
            "subscription_id": "",
            "severity": "Sev2",
            "domain": "sre",
            "alert_rule": "rule",
        }
        result = map_detection_result_to_incident_payload(dr)
        assert result["affected_resources"][0]["subscription_id"] == "sub-99"

    def test_all_severity_levels(self) -> None:
        for sev in ["Sev0", "Sev1", "Sev2", "Sev3"]:
            dr = {
                "alert_id": "a-1", "severity": sev, "domain": "compute",
                "resource_id": "/subscriptions/s/resourceGroups/r/providers/P/T/n",
                "resource_type": "P/T", "subscription_id": "s", "alert_rule": "r",
            }
            result = map_detection_result_to_incident_payload(dr)
            assert result["severity"] == sev

    def test_all_domains(self) -> None:
        for domain in ["compute", "network", "storage", "security", "arc", "sre"]:
            dr = {
                "alert_id": "a-1", "severity": "Sev1", "domain": domain,
                "resource_id": "/subscriptions/s/resourceGroups/r/providers/P/T/n",
                "resource_type": "P/T", "subscription_id": "s", "alert_rule": "r",
            }
            result = map_detection_result_to_incident_payload(dr)
            assert result["domain"] == domain

    def test_optional_fields_missing(self) -> None:
        dr = {
            "alert_id": "a-1", "severity": "Sev3", "domain": "sre",
            "resource_id": "/subscriptions/s/resourceGroups/r/providers/P/T/n",
            "resource_type": "P/T", "subscription_id": "s", "alert_rule": "r",
        }
        result = map_detection_result_to_incident_payload(dr)
        assert result["kql_evidence"] is None
        assert result["description"] is None

    def test_incident_id_has_det_prefix(self) -> None:
        dr = {
            "alert_id": "xyz-789",
            "resource_id": "/subscriptions/s/resourceGroups/r/providers/P/T/n",
            "resource_type": "P/T", "subscription_id": "s",
            "severity": "Sev0", "domain": "network", "alert_rule": "r",
        }
        result = map_detection_result_to_incident_payload(dr)
        assert result["incident_id"].startswith("det-")
        assert result["incident_id"] == "det-xyz-789"

    def test_affected_resources_has_exactly_one_entry(self) -> None:
        dr = {
            "alert_id": "a-1",
            "resource_id": "/subscriptions/s/resourceGroups/r/providers/P/T/n",
            "resource_type": "P/T", "subscription_id": "s",
            "severity": "Sev1", "domain": "compute", "alert_rule": "r",
        }
        result = map_detection_result_to_incident_payload(dr)
        assert isinstance(result["affected_resources"], list)
        assert len(result["affected_resources"]) == 1

    def test_title_built_from_rule_and_resource_name(self) -> None:
        dr = {
            "alert_id": "a-1",
            "resource_id": "/subscriptions/s/resourceGroups/r/providers/P/T/n",
            "resource_type": "P/T", "subscription_id": "s",
            "severity": "Sev1", "domain": "compute",
            "alert_rule": "High CPU", "resource_name": "my-vm",
        }
        result = map_detection_result_to_incident_payload(dr)
        assert result["title"] == "High CPU on my-vm"
