"""Tests for audit_export.py (AUDIT-006)."""
from unittest.mock import patch, MagicMock

import pytest

from services.api_gateway.audit_export import generate_remediation_report


class TestGenerateRemediationReport:
    """Tests for generate_remediation_report (must be in class for strict asyncio mode)."""

    @pytest.mark.asyncio
    @patch("services.api_gateway.audit_export._read_onelake_events", return_value=[])
    @patch("services.api_gateway.audit_export._read_approval_records", return_value={
        "appr-001": {
            "id": "appr-001",
            "agent_name": "agent-compute",
            "thread_id": "thread-1",
            "status": "approved",
            "proposed_at": "2026-03-01T10:00:00Z",
            "decided_at": "2026-03-01T10:05:00Z",
            "decided_by": "ops@contoso.com",
            "expires_at": "2026-03-01T10:30:00Z",
            "proposal": {"tool_name": "restart_vm", "tool_parameters": {"vm": "vm-1"}},
        }
    })
    async def test_generate_report_from_cosmos_fallback(self, mock_approvals, mock_onelake):
        report = await generate_remediation_report(
            from_time="2026-03-01T00:00:00Z",
            to_time="2026-03-31T23:59:59Z",
        )
        assert report["report_metadata"]["total_events"] == 1
        assert report["remediation_events"][0]["agentId"] == "agent-compute"
        assert report["remediation_events"][0]["approval_chain"]["status"] == "approved"
        assert report["remediation_events"][0]["approval_chain"]["decided_by"] == "ops@contoso.com"

    @pytest.mark.asyncio
    @patch("services.api_gateway.audit_export._read_onelake_events", return_value=[])
    @patch("services.api_gateway.audit_export._read_approval_records", return_value={})
    async def test_generate_report_empty(self, mock_approvals, mock_onelake):
        report = await generate_remediation_report(
            from_time="2026-03-01T00:00:00Z",
            to_time="2026-03-31T23:59:59Z",
        )
        assert report["report_metadata"]["total_events"] == 0
        assert report["remediation_events"] == []
        assert "generated_at" in report["report_metadata"]

    @pytest.mark.asyncio
    @patch("services.api_gateway.audit_export._read_onelake_events", return_value=[
        {
            "timestamp": "2026-03-15T14:00:00Z",
            "agentId": "agent-network",
            "toolName": "reset_nsg",
            "toolParameters": {"nsg_id": "nsg-1"},
            "approvedBy": "admin@contoso.com",
            "outcome": "approved",
            "durationMs": 500,
            "correlationId": "corr-abc",
            "threadId": "thread-net-1",
            "approvalId": "appr-net-001",
        }
    ])
    @patch("services.api_gateway.audit_export._read_approval_records", return_value={
        "appr-net-001": {
            "id": "appr-net-001",
            "agent_name": "agent-network",
            "thread_id": "thread-net-1",
            "status": "approved",
            "proposed_at": "2026-03-15T13:55:00Z",
            "decided_at": "2026-03-15T14:00:00Z",
            "decided_by": "admin@contoso.com",
            "expires_at": "2026-03-15T14:25:00Z",
            "proposal": {"tool_name": "reset_nsg", "tool_parameters": {"nsg_id": "nsg-1"}},
        }
    })
    async def test_generate_report_enriches_onelake_events_with_approval_chain(
        self, mock_approvals, mock_onelake
    ):
        """OneLake events should be enriched with approval chain data from Cosmos."""
        report = await generate_remediation_report(
            from_time="2026-03-01T00:00:00Z",
            to_time="2026-03-31T23:59:59Z",
        )
        assert report["report_metadata"]["total_events"] == 1
        event = report["remediation_events"][0]
        assert event["agentId"] == "agent-network"
        assert event["toolName"] == "reset_nsg"
        assert "approval_chain" in event
        assert event["approval_chain"]["decided_by"] == "admin@contoso.com"
        assert event["approval_chain"]["status"] == "approved"

    @pytest.mark.asyncio
    @patch("services.api_gateway.audit_export._read_onelake_events", return_value=[])
    @patch("services.api_gateway.audit_export._read_approval_records", return_value={
        "appr-multi-1": {
            "id": "appr-multi-1",
            "agent_name": "agent-storage",
            "thread_id": "thread-s1",
            "status": "rejected",
            "proposed_at": "2026-03-10T09:00:00Z",
            "decided_at": "2026-03-10T09:05:00Z",
            "decided_by": "reviewer@contoso.com",
            "expires_at": "2026-03-10T09:30:00Z",
            "proposal": {"tool_name": "expand_disk", "tool_parameters": {}},
        },
        "appr-multi-2": {
            "id": "appr-multi-2",
            "agent_name": "agent-compute",
            "thread_id": "thread-c1",
            "status": "expired",
            "proposed_at": "2026-03-12T10:00:00Z",
            "decided_at": "",
            "decided_by": "",
            "expires_at": "2026-03-12T10:30:00Z",
            "proposal": {"tool_name": "restart_vm", "tool_parameters": {}},
        },
    })
    async def test_generate_report_multiple_events_from_cosmos(self, mock_approvals, mock_onelake):
        """Multiple Cosmos records should produce multiple report events."""
        report = await generate_remediation_report(
            from_time="2026-03-01T00:00:00Z",
            to_time="2026-03-31T23:59:59Z",
        )
        assert report["report_metadata"]["total_events"] == 2
        outcomes = {e["outcome"] for e in report["remediation_events"]}
        assert "rejected" in outcomes
        assert "expired" in outcomes

    @pytest.mark.asyncio
    @patch("services.api_gateway.audit_export._read_onelake_events", return_value=[])
    @patch("services.api_gateway.audit_export._read_approval_records", return_value={})
    async def test_generate_report_metadata_structure(self, mock_approvals, mock_onelake):
        """report_metadata must contain generated_at, period, and total_events."""
        report = await generate_remediation_report(
            from_time="2026-03-01T00:00:00Z",
            to_time="2026-03-31T23:59:59Z",
        )
        metadata = report["report_metadata"]
        assert "generated_at" in metadata
        assert metadata["period"]["from"] == "2026-03-01T00:00:00Z"
        assert metadata["period"]["to"] == "2026-03-31T23:59:59Z"
        assert metadata["total_events"] == 0
