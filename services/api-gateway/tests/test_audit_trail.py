"""Tests for the dual-write audit trail (AUDIT-002, AUDIT-004)."""
import os
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _stub_filedatalake():
    """Install azure.storage.filedatalake stub into sys.modules."""
    stub = types.ModuleType("azure.storage.filedatalake")
    stub.DataLakeServiceClient = MagicMock
    import azure.storage
    azure.storage.filedatalake = stub  # type: ignore[attr-defined]
    sys.modules["azure.storage.filedatalake"] = stub
    return stub


def _stub_monitor_query():
    """Install azure.monitor.query stub into sys.modules.

    Returns the stub module so the caller can configure LogsQueryClient on it.
    """
    stub = types.ModuleType("azure.monitor.query")
    stub.LogsQueryClient = MagicMock  # will be overridden per-test

    # Build azure.monitor parent if missing
    if "azure.monitor" not in sys.modules:
        parent = types.ModuleType("azure.monitor")
        sys.modules["azure.monitor"] = parent

    # Attach to azure.monitor so attribute access works
    import azure
    if not hasattr(azure, "monitor"):
        azure.monitor = sys.modules["azure.monitor"]  # type: ignore[attr-defined]
    sys.modules["azure.monitor"].query = stub  # type: ignore[attr-defined]
    sys.modules["azure.monitor.query"] = stub
    return stub


def _call_upload(mock_file_client, record):
    """Helper: simulate a OneLake write by calling upload_data on the mock."""
    import json
    data = json.dumps(record, default=str).encode("utf-8")
    mock_file_client.upload_data(data, overwrite=True)


class TestAuditTrail:
    """Tests for dual-write audit trail (Cosmos DB + OneLake)."""

    @pytest.mark.asyncio
    async def test_approval_written_to_cosmos(self, mock_cosmos_approvals):
        """Cosmos create_item is called when an approval record is created."""
        from agents.shared.approval_manager import create_approval_record

        proposal = {
            "description": "Restart VM",
            "target_resources": [
                "/subscriptions/sub-1/rgs/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1"
            ],
            "estimated_impact": "~2 min",
            "risk_level": "high",
            "reversibility": "reversible",
            "action_type": "restart",
        }
        snapshot = {
            "resource_id": "/subscriptions/sub-1/rgs/rg-1/providers/Microsoft.Compute/virtualMachines/vm-1",
            "provisioning_state": "Succeeded",
            "tags": {},
            "resource_health": "Available",
            "snapshot_hash": "b" * 64,
        }

        await create_approval_record(
            container=mock_cosmos_approvals,
            thread_id="thread-test-001",
            incident_id="inc-test-001",
            agent_name="compute",
            proposal=proposal,
            resource_snapshot=snapshot,
            risk_level="high",
        )

        mock_cosmos_approvals.create_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_approval_written_to_onelake(self, mock_cosmos_approvals):
        """OneLake write fires after Cosmos write (upload_data called)."""
        _stub_filedatalake()
        from services.api_gateway.audit_trail import write_audit_record

        mock_file_client = MagicMock()
        approval_record = {
            "id": "appr_test-001",
            "status": "approved",
            "thread_id": "thread-test-001",
        }

        # Patch _write_to_onelake to call our mock upload
        async def fake_write(rec):
            _call_upload(mock_file_client, rec)

        with patch("services.api_gateway.audit_trail._write_to_onelake", side_effect=fake_write):
            await write_audit_record(approval_record)

        mock_file_client.upload_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_onelake_failure_non_blocking(self, mock_cosmos_approvals):
        """OneLake write error is logged but does not raise an exception."""
        from services.api_gateway.audit_trail import write_audit_record

        approval_record = {"id": "appr_test-001", "status": "approved"}

        async def failing_write(record):
            raise ConnectionError("OneLake unavailable")

        with patch("services.api_gateway.audit_trail._write_to_onelake", side_effect=failing_write):
            # Must NOT raise — OneLake failure is non-blocking
            await write_audit_record(approval_record)

    @pytest.mark.asyncio
    async def test_audit_query_filters_by_agent(self, client):
        """Audit log query with agent=compute includes AppRoleName KQL filter."""
        monitor_stub = _stub_monitor_query()

        captured_kql: list = []
        mock_response = MagicMock()
        mock_response.tables = []
        mock_logs_client = MagicMock()
        def _capture_kql(workspace_id, query, timespan=None):
            captured_kql.append(query)
            return mock_response

        mock_logs_client.query_workspace.side_effect = _capture_kql
        monitor_stub.LogsQueryClient = MagicMock(return_value=mock_logs_client)

        # Reimport the module with LOG_ANALYTICS_WORKSPACE_ID set so the
        # module-level constant is populated with a non-empty value.
        if "services.api_gateway.audit" in sys.modules:
            del sys.modules["services.api_gateway.audit"]

        old_val = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")
        os.environ["LOG_ANALYTICS_WORKSPACE_ID"] = "ws-test-001"
        try:
            with patch("azure.identity.DefaultAzureCredential", return_value=MagicMock()):
                from services.api_gateway.audit import query_audit_log
                await query_audit_log(agent="compute")
        finally:
            if old_val:
                os.environ["LOG_ANALYTICS_WORKSPACE_ID"] = old_val
            else:
                os.environ.pop("LOG_ANALYTICS_WORKSPACE_ID", None)
            if "services.api_gateway.audit" in sys.modules:
                del sys.modules["services.api_gateway.audit"]

        assert len(captured_kql) == 1, f"Expected 1 KQL call, got {len(captured_kql)}"
        kql = captured_kql[0]
        assert "AppRoleName == 'agent-compute'" in kql, (
            f"Expected \"AppRoleName == 'agent-compute'\" in KQL, got:\n{kql}"
        )

    @pytest.mark.asyncio
    async def test_audit_query_filters_by_time_range(self, client):
        """Audit log query with from/to parameters includes datetime() KQL filters."""
        monitor_stub = _stub_monitor_query()

        captured_kql: list = []
        mock_response = MagicMock()
        mock_response.tables = []
        mock_logs_client = MagicMock()
        def _capture_kql2(workspace_id, query, timespan=None):
            captured_kql.append(query)
            return mock_response

        mock_logs_client.query_workspace.side_effect = _capture_kql2
        monitor_stub.LogsQueryClient = MagicMock(return_value=mock_logs_client)

        if "services.api_gateway.audit" in sys.modules:
            del sys.modules["services.api_gateway.audit"]

        from_time = "2026-03-27T00:00:00Z"
        to_time = "2026-03-27T23:59:59Z"

        old_val = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")
        os.environ["LOG_ANALYTICS_WORKSPACE_ID"] = "ws-test-001"
        try:
            with patch("azure.identity.DefaultAzureCredential", return_value=MagicMock()):
                from services.api_gateway.audit import query_audit_log
                await query_audit_log(from_time=from_time, to_time=to_time)
        finally:
            if old_val:
                os.environ["LOG_ANALYTICS_WORKSPACE_ID"] = old_val
            else:
                os.environ.pop("LOG_ANALYTICS_WORKSPACE_ID", None)
            if "services.api_gateway.audit" in sys.modules:
                del sys.modules["services.api_gateway.audit"]

        assert len(captured_kql) == 1, f"Expected 1 KQL call, got {len(captured_kql)}"
        kql = captured_kql[0]
        assert "datetime(" in kql, (
            f"Expected 'datetime(' in KQL for time range, got:\n{kql}"
        )
        assert from_time in kql, (
            f"Expected from_time '{from_time}' in KQL, got:\n{kql}"
        )
        assert to_time in kql, (
            f"Expected to_time '{to_time}' in KQL, got:\n{kql}"
        )
