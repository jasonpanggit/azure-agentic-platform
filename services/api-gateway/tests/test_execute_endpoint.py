"""Tests for POST /api/v1/approvals/{id}/execute, GET verification, and GET remediation-export."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_approval(
    approval_id: str = "appr-1",
    approval_status: str = "approved",
    expired: bool = False,
) -> dict:
    """Helper to create a minimal approval record for mocking."""
    expires_at = (
        (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        if expired
        else (datetime.now(timezone.utc) + timedelta(hours=23)).isoformat()
    )
    return {
        "id": approval_id,
        "thread_id": "thr-1",
        "incident_id": "inc-1",
        "status": approval_status,
        "proposed_action": "restart_vm",
        "decided_by": "user@example.com",
        "decided_at": "2026-01-01T00:00:00Z",
        "expires_at": expires_at,
        "proposal": {
            "action": "restart_vm",
            "target_resources": [
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
            ],
            "tool_parameters": {},
        },
    }


def _make_audit_record(
    approval_id: str = "appr-1",
    verification_result: Any = None,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "incident_id": "inc-1",
        "approval_id": approval_id,
        "thread_id": "thr-1",
        "action_type": "execute",
        "proposed_action": "restart_vm",
        "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        "executed_by": "user@example.com",
        "executed_at": "2026-01-01T00:05:00Z",
        "status": "complete" if verification_result else "pending",
        "verification_result": verification_result,
        "verified_at": "2026-01-01T00:15:00Z" if verification_result else None,
        "rolled_back": False,
        "rollback_execution_id": None,
        "preflight_blast_radius_size": 3,
        "wal_written_at": "2026-01-01T00:04:59Z",
    }


# ---------------------------------------------------------------------------
# Execute endpoint tests — unit-level, no TestClient
# ---------------------------------------------------------------------------


class TestExecuteApproval:
    """Unit tests for execute_approval endpoint handler."""

    @pytest.mark.asyncio
    async def test_execute_returns_404_for_missing_approval(self):
        """execute_approval raises 404 when approval is not found in Cosmos."""
        from fastapi import HTTPException
        from services.api_gateway.main import execute_approval

        mock_container = MagicMock()
        mock_container.query_items.return_value = []
        mock_cosmos = MagicMock()

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_container,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await execute_approval(
                    approval_id="missing-id",
                    request=MagicMock(app=MagicMock(state=MagicMock(topology_client=None))),
                    token={"sub": "user"},
                    cosmos_client=mock_cosmos,
                    credential=MagicMock(),
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_execute_returns_409_for_pending_status(self):
        """execute_approval raises 409 when approval status is 'pending'."""
        from fastapi import HTTPException
        from services.api_gateway.main import execute_approval

        approval = _make_approval(approval_status="pending")
        mock_container = MagicMock()
        mock_container.query_items.return_value = [approval]

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_container,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await execute_approval(
                    approval_id="appr-1",
                    request=MagicMock(app=MagicMock(state=MagicMock(topology_client=None))),
                    token={"sub": "user"},
                    cosmos_client=MagicMock(),
                    credential=MagicMock(),
                )
        assert exc_info.value.status_code == 409
        assert "approved" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_execute_returns_409_for_rejected_status(self):
        """execute_approval raises 409 when approval status is 'rejected'."""
        from fastapi import HTTPException
        from services.api_gateway.main import execute_approval

        approval = _make_approval(approval_status="rejected")
        mock_container = MagicMock()
        mock_container.query_items.return_value = [approval]

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_container,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await execute_approval(
                    approval_id="appr-1",
                    request=MagicMock(app=MagicMock(state=MagicMock(topology_client=None))),
                    token={"sub": "user"},
                    cosmos_client=MagicMock(),
                    credential=MagicMock(),
                )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_execute_returns_410_for_expired_approval(self):
        """execute_approval raises 410 when approval has expired."""
        from fastapi import HTTPException
        from services.api_gateway.main import execute_approval

        approval = _make_approval(approval_status="approved", expired=True)
        mock_container = MagicMock()
        mock_container.query_items.return_value = [approval]

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_container,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await execute_approval(
                    approval_id="appr-1",
                    request=MagicMock(app=MagicMock(state=MagicMock(topology_client=None))),
                    token={"sub": "user"},
                    cosmos_client=MagicMock(),
                    credential=MagicMock(),
                )
        assert exc_info.value.status_code == 410

    @pytest.mark.asyncio
    async def test_execute_returns_result_on_success(self):
        """execute_approval returns RemediationResult on success."""
        from services.api_gateway.main import execute_approval
        from services.api_gateway.models import RemediationResult

        approval = _make_approval(approval_status="approved")
        mock_container = MagicMock()
        mock_container.query_items.return_value = [approval]

        exec_id = str(uuid.uuid4())
        mock_result = RemediationResult(
            execution_id=exec_id,
            status="complete",
            verification_scheduled=True,
            preflight_passed=True,
            blast_radius_size=3,
        )

        with patch(
            "services.api_gateway.approvals._get_approvals_container",
            return_value=mock_container,
        ), patch(
            "services.api_gateway.main.execute_remediation",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await execute_approval(
                approval_id="appr-1",
                request=MagicMock(app=MagicMock(state=MagicMock(topology_client=None))),
                token={"sub": "user"},
                cosmos_client=MagicMock(),
                credential=MagicMock(),
            )

        assert result.execution_id == exec_id
        assert result.verification_scheduled is True
        assert result.preflight_passed is True


# ---------------------------------------------------------------------------
# Verification endpoint tests — unit-level
# ---------------------------------------------------------------------------


class TestGetVerificationResult:
    """Unit tests for get_verification_result endpoint handler."""

    @pytest.mark.asyncio
    async def test_verification_returns_404_when_no_execution_record(self):
        """get_verification_result raises 404 when no execution record exists."""
        from fastapi import HTTPException
        from services.api_gateway.main import get_verification_result

        mock_container = MagicMock()
        mock_container.query_items.return_value = []

        with patch(
            "services.api_gateway.remediation_executor._get_remediation_audit_container",
            return_value=mock_container,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_verification_result(
                    approval_id="appr-missing",
                    token={"sub": "user"},
                    cosmos_client=MagicMock(),
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_verification_returns_202_while_pending(self):
        """get_verification_result returns JSONResponse 202 while verification is pending."""
        from fastapi.responses import JSONResponse
        from services.api_gateway.main import get_verification_result

        audit_record = _make_audit_record(approval_id="appr-1", verification_result=None)
        mock_container = MagicMock()
        mock_container.query_items.return_value = [audit_record]

        with patch(
            "services.api_gateway.remediation_executor._get_remediation_audit_container",
            return_value=mock_container,
        ):
            result = await get_verification_result(
                approval_id="appr-1",
                token={"sub": "user"},
                cosmos_client=MagicMock(),
            )

        assert isinstance(result, JSONResponse)
        assert result.status_code == 202
        assert result.headers.get("retry-after") == "60"

    @pytest.mark.asyncio
    async def test_verification_returns_audit_record_when_complete(self):
        """get_verification_result returns RemediationAuditRecord when verification is complete."""
        from services.api_gateway.main import get_verification_result
        from services.api_gateway.models import RemediationAuditRecord

        audit_record = _make_audit_record(approval_id="appr-1", verification_result="RESOLVED")
        mock_container = MagicMock()
        mock_container.query_items.return_value = [audit_record]

        with patch(
            "services.api_gateway.remediation_executor._get_remediation_audit_container",
            return_value=mock_container,
        ):
            result = await get_verification_result(
                approval_id="appr-1",
                token={"sub": "user"},
                cosmos_client=MagicMock(),
            )

        assert isinstance(result, RemediationAuditRecord)
        assert result.verification_result == "RESOLVED"


# ---------------------------------------------------------------------------
# Audit export function tests — unit-level
# ---------------------------------------------------------------------------


class TestExportRemediationAudit:
    """Unit tests for generate_remediation_audit_export and the endpoint."""

    @pytest.mark.asyncio
    async def test_remediation_export_includes_cosmos_audit_records(self):
        """generate_remediation_audit_export includes Cosmos-only audit records."""
        from services.api_gateway.audit_export import generate_remediation_audit_export

        audit_record = _make_audit_record(
            approval_id="appr-unique-1", verification_result="RESOLVED"
        )

        with patch(
            "services.api_gateway.audit_export._read_onelake_events",
            new_callable=AsyncMock,
        ) as mock_onelake, patch(
            "services.api_gateway.audit_export._read_approval_records",
            new_callable=AsyncMock,
        ) as mock_approvals, patch(
            "services.api_gateway.audit_export._read_remediation_audit_records",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_onelake.return_value = []
            mock_approvals.return_value = {}
            mock_audit.return_value = [audit_record]

            result = await generate_remediation_audit_export(
                from_time="2026-01-01T00:00:00Z",
                to_time="2026-01-02T00:00:00Z",
                cosmos_client=MagicMock(),
            )

        assert len(result["remediation_events"]) == 1
        event = result["remediation_events"][0]
        assert event["execution_audit"]["execution_id"] == audit_record["id"]
        assert "cosmos_remediation_audit" in result["report_metadata"]["sources"]

    @pytest.mark.asyncio
    async def test_remediation_export_enriches_onelake_events(self):
        """generate_remediation_audit_export enriches OneLake events with WAL data."""
        from services.api_gateway.audit_export import generate_remediation_audit_export

        audit_record = _make_audit_record(
            approval_id="appr-shared", verification_result="IMPROVED"
        )
        onelake_event = {
            "timestamp": "2026-01-01T00:05:00Z",
            "agentId": "agent-compute",
            "toolName": "restart_vm",
            "toolParameters": {},
            "approvedBy": "user@example.com",
            "outcome": "complete",
            "durationMs": 5000,
            "correlationId": "",
            "threadId": "thr-1",
            "approvalId": "appr-shared",
        }

        with patch(
            "services.api_gateway.audit_export._read_onelake_events",
            new_callable=AsyncMock,
        ) as mock_onelake, patch(
            "services.api_gateway.audit_export._read_approval_records",
            new_callable=AsyncMock,
        ) as mock_approvals, patch(
            "services.api_gateway.audit_export._read_remediation_audit_records",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_onelake.return_value = [onelake_event]
            mock_approvals.return_value = {}
            mock_audit.return_value = [audit_record]

            result = await generate_remediation_audit_export(
                from_time="2026-01-01T00:00:00Z",
                to_time="2026-01-02T00:00:00Z",
                cosmos_client=MagicMock(),
            )

        # 1 OneLake event enriched — not duplicated
        assert len(result["remediation_events"]) == 1
        event = result["remediation_events"][0]
        assert event["execution_audit"]["verification_result"] == "IMPROVED"

    @pytest.mark.asyncio
    async def test_read_remediation_audit_records_returns_empty_when_cosmos_none(self):
        """_read_remediation_audit_records returns [] gracefully when cosmos_client is None."""
        from services.api_gateway.audit_export import _read_remediation_audit_records

        result = await _read_remediation_audit_records(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", None
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_export_endpoint_handler(self):
        """export_remediation_audit endpoint handler returns AuditExportResponse."""
        from services.api_gateway.main import export_remediation_audit
        from services.api_gateway.models import AuditExportResponse

        mock_report = {
            "report_metadata": {
                "generated_at": "2026-01-01T00:00:00Z",
                "period": {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"},
                "total_events": 0,
                "sources": ["onelake", "cosmos_approvals", "cosmos_remediation_audit"],
            },
            "remediation_events": [],
        }

        with patch(
            "services.api_gateway.main.generate_remediation_audit_export",
            new=AsyncMock(return_value=mock_report),
        ):
            result = await export_remediation_audit(
                from_time="2026-01-01T00:00:00Z",
                to_time="2026-01-02T00:00:00Z",
                token={"sub": "user"},
                cosmos_client=MagicMock(),
            )

        assert isinstance(result, AuditExportResponse)
        assert "cosmos_remediation_audit" in result.report_metadata["sources"]
