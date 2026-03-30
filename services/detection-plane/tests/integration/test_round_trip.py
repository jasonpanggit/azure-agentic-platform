"""Detection plane round-trip — payload mapping mock-based tests (CONCERNS 3.1).

Tests map_detection_result_to_incident_payload() with mock alert data.
Import-safe: payload_mapper.py has no Azure SDK at module level.
"""
from __future__ import annotations

import pytest

from payload_mapper import map_detection_result_to_incident_payload

pytestmark = pytest.mark.integration


SAMPLE_DETECTION_RESULT = {
    "alert_id": "alert-test-001",
    "severity": "Sev2",
    "resource_type": "Microsoft.Compute/virtualMachines",
    "resource_id": "/subscriptions/sub-123/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm-01",
    "subscription_id": "sub-123",
    "resource_name": "vm-01",
    "alert_rule": "HighCpuUtilization",
    "domain": "compute",
    "description": "CPU utilization exceeded 95% for 15 minutes",
    "kql_evidence": "Perf | where ObjectName == 'Processor' | where CounterValue > 95",
    "fired_at": "2026-03-30T10:00:00Z",
    "classified_at": "2026-03-30T10:00:05Z",
}


class TestRoundTrip:
    """Tests for detection result -> incident payload mapping."""

    def test_mapped_payload_has_required_fields(self) -> None:
        """map_detection_result_to_incident_payload returns all required IncidentPayload fields."""
        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        required_fields = ["incident_id", "severity", "domain", "detection_rule", "affected_resources"]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

    def test_incident_id_prefixed_with_det(self) -> None:
        """Incident ID is prefixed with 'det-' for traceability."""
        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        assert result["incident_id"] == "det-alert-test-001"

    def test_severity_preserved_from_input(self) -> None:
        """Severity from detection result is preserved in the mapped payload."""
        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        assert result["severity"] == "Sev2"

    def test_affected_resources_populated(self) -> None:
        """Mapped payload includes at least one affected_resource."""
        result = map_detection_result_to_incident_payload(SAMPLE_DETECTION_RESULT)
        assert "affected_resources" in result
        assert len(result["affected_resources"]) >= 1

    def test_missing_alert_id_raises_value_error(self) -> None:
        """map_detection_result_to_incident_payload raises ValueError for empty alert_id."""
        bad_input = dict(SAMPLE_DETECTION_RESULT, alert_id="")
        with pytest.raises(ValueError, match="alert_id"):
            map_detection_result_to_incident_payload(bad_input)
