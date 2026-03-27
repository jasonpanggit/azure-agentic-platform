"""Tests for agents.shared.envelope (AGENT-002)."""
import pytest
from agents.shared.envelope import (
    IncidentMessage,
    VALID_MESSAGE_TYPES,
    validate_envelope,
)


class TestIncidentMessageTypedDict:
    """Verify IncidentMessage TypedDict has all required fields."""

    def test_has_correlation_id_field(self):
        assert "correlation_id" in IncidentMessage.__annotations__

    def test_has_thread_id_field(self):
        assert "thread_id" in IncidentMessage.__annotations__

    def test_has_source_agent_field(self):
        assert "source_agent" in IncidentMessage.__annotations__

    def test_has_target_agent_field(self):
        assert "target_agent" in IncidentMessage.__annotations__

    def test_has_message_type_field(self):
        assert "message_type" in IncidentMessage.__annotations__

    def test_has_payload_field(self):
        assert "payload" in IncidentMessage.__annotations__

    def test_has_timestamp_field(self):
        assert "timestamp" in IncidentMessage.__annotations__

    def test_exactly_seven_fields(self):
        assert len(IncidentMessage.__annotations__) == 7


class TestValidMessageTypes:
    """Verify valid message types match spec."""

    def test_incident_handoff_is_valid(self):
        assert "incident_handoff" in VALID_MESSAGE_TYPES

    def test_diagnosis_complete_is_valid(self):
        assert "diagnosis_complete" in VALID_MESSAGE_TYPES

    def test_remediation_proposal_is_valid(self):
        assert "remediation_proposal" in VALID_MESSAGE_TYPES

    def test_cross_domain_request_is_valid(self):
        assert "cross_domain_request" in VALID_MESSAGE_TYPES

    def test_status_update_is_valid(self):
        assert "status_update" in VALID_MESSAGE_TYPES

    def test_approval_request_is_valid(self):
        assert "approval_request" in VALID_MESSAGE_TYPES

    def test_approval_response_is_valid(self):
        assert "approval_response" in VALID_MESSAGE_TYPES

    def test_exactly_seven_message_types(self):
        assert len(VALID_MESSAGE_TYPES) == 7


class TestValidateEnvelope:
    """Verify envelope validation logic."""

    @pytest.fixture()
    def valid_message(self):
        return {
            "correlation_id": "inc-001",
            "thread_id": "thread-abc",
            "source_agent": "orchestrator",
            "target_agent": "compute",
            "message_type": "incident_handoff",
            "payload": {"severity": "Sev1"},
            "timestamp": "2026-03-26T14:00:00Z",
        }

    def test_valid_message_passes(self, valid_message):
        result = validate_envelope(valid_message)
        assert result["correlation_id"] == "inc-001"

    def test_missing_field_raises_value_error(self, valid_message):
        del valid_message["correlation_id"]
        with pytest.raises(ValueError, match="Missing required fields"):
            validate_envelope(valid_message)

    def test_wrong_type_raises_value_error(self, valid_message):
        valid_message["correlation_id"] = 123
        with pytest.raises(ValueError, match="expected str"):
            validate_envelope(valid_message)

    def test_invalid_message_type_raises_value_error(self, valid_message):
        valid_message["message_type"] = "invalid_type"
        with pytest.raises(ValueError, match="Invalid message_type"):
            validate_envelope(valid_message)
