"""Tests for remediation_logger.py (REMEDI-007)."""
import sys
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.remediation_logger import (
    build_remediation_event,
    log_remediation_event,
)


def test_build_remediation_event_approved():
    record = {
        "id": "appr-001",
        "agent_name": "agent-compute",
        "thread_id": "thread-123",
        "decided_by": "ops@contoso.com",
        "proposal": {
            "tool_name": "restart_vm",
            "tool_parameters": {"vm_name": "vm-prod-01"},
        },
    }
    event = build_remediation_event(record, outcome="approved", correlation_id="corr-1")
    assert event["agentId"] == "agent-compute"
    assert event["toolName"] == "restart_vm"
    assert event["toolParameters"] == {"vm_name": "vm-prod-01"}
    assert event["approvedBy"] == "ops@contoso.com"
    assert event["outcome"] == "approved"
    assert event["threadId"] == "thread-123"
    assert event["approvalId"] == "appr-001"
    assert event["correlationId"] == "corr-1"
    assert "timestamp" in event


def test_build_remediation_event_rejected():
    record = {
        "id": "appr-002",
        "agent_name": "agent-network",
        "thread_id": "thread-456",
        "decided_by": "admin@contoso.com",
        "proposal": {"action": "reset_nsg", "parameters": {"nsg_id": "nsg-1"}},
    }
    event = build_remediation_event(record, outcome="rejected")
    assert event["outcome"] == "rejected"
    assert event["durationMs"] == 0
    assert event["toolName"] == "reset_nsg"


def test_build_remediation_event_expired_no_decided_by():
    record = {
        "id": "appr-003",
        "agent_name": "agent-storage",
        "thread_id": "thread-789",
        "proposal": {"tool_name": "expand_disk"},
    }
    event = build_remediation_event(record, outcome="expired")
    assert event["outcome"] == "expired"
    assert event["approvedBy"] == ""


def test_build_remediation_event_all_ten_schema_fields():
    """Ensure all 10 REMEDI-007 schema fields are present."""
    record = {
        "id": "appr-004",
        "agent_name": "agent-sre",
        "thread_id": "thread-abc",
        "decided_by": "sre@contoso.com",
        "proposal": {"tool_name": "scale_aks", "tool_parameters": {"cluster": "aks-1"}},
    }
    event = build_remediation_event(
        record, outcome="success", duration_ms=1234, correlation_id="corr-xyz"
    )
    required_fields = {
        "timestamp", "agentId", "toolName", "toolParameters",
        "approvedBy", "outcome", "durationMs", "correlationId",
        "threadId", "approvalId",
    }
    assert required_fields == set(event.keys())
    assert event["durationMs"] == 1234


class TestLogRemediationEventAsync:
    """Async tests for log_remediation_event (must be in class for strict asyncio mode)."""

    @pytest.mark.asyncio
    @patch("services.api_gateway.remediation_logger.FABRIC_WORKSPACE_NAME", "")
    @patch("services.api_gateway.remediation_logger.FABRIC_LAKEHOUSE_NAME", "")
    async def test_log_remediation_event_skips_when_not_configured(self):
        """Should silently skip when OneLake env vars are empty."""
        event = {"approvalId": "test", "outcome": "approved"}
        await log_remediation_event(event)  # Should not raise

    @pytest.mark.asyncio
    @patch("services.api_gateway.remediation_logger.FABRIC_WORKSPACE_NAME", "ws-test")
    @patch("services.api_gateway.remediation_logger.FABRIC_LAKEHOUSE_NAME", "lh-test")
    async def test_log_remediation_event_writes_to_onelake(self):
        """Should write JSON to OneLake when configured (mocks azure SDK via sys.modules)."""
        mock_fs = MagicMock()
        mock_dir = MagicMock()
        mock_file = MagicMock()
        mock_service = MagicMock()
        mock_service.get_file_system_client.return_value = mock_fs
        mock_fs.get_directory_client.return_value = mock_dir
        mock_dir.create_file.return_value = mock_file

        mock_datalake_cls = MagicMock(return_value=mock_service)
        mock_cred_cls = MagicMock()

        # Inject mock modules so the lazy imports inside log_remediation_event find them
        mock_identity_mod = MagicMock()
        mock_identity_mod.DefaultAzureCredential = mock_cred_cls
        mock_filedatalake_mod = MagicMock()
        mock_filedatalake_mod.DataLakeServiceClient = mock_datalake_cls

        with patch.dict(sys.modules, {
            "azure.identity": mock_identity_mod,
            "azure.storage.filedatalake": mock_filedatalake_mod,
        }):
            event = {"approvalId": "appr-test", "outcome": "approved", "agentId": "compute"}
            await log_remediation_event(event)

        mock_dir.create_directory.assert_called_once()
        mock_dir.create_file.assert_called_once()
        mock_file.append_data.assert_called_once()
        mock_file.flush_data.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.api_gateway.remediation_logger.FABRIC_WORKSPACE_NAME", "ws-test")
    @patch("services.api_gateway.remediation_logger.FABRIC_LAKEHOUSE_NAME", "lh-test")
    async def test_log_remediation_event_does_not_raise_on_error(self):
        """Should catch exceptions and never raise — fire-and-forget pattern."""
        # Inject a mock module that raises on DefaultAzureCredential instantiation
        mock_identity_mod = MagicMock()
        mock_identity_mod.DefaultAzureCredential.side_effect = RuntimeError("auth failure")

        with patch.dict(sys.modules, {"azure.identity": mock_identity_mod}):
            event = {"approvalId": "appr-err", "outcome": "rejected"}
            # Must not raise even when OneLake write fails
            await log_remediation_event(event)
