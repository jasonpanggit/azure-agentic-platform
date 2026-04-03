"""Tests for remediation_executor.py — WAL, pre-flight, verification, rollback, orchestration."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# WAL write tests
# ---------------------------------------------------------------------------

class TestWriteWal:
    """Tests for _write_wal()."""

    async def test_write_wal_creates_pending_record(self):
        """_write_wal with base_record creates a pending record via create_item."""
        from services.api_gateway.remediation_executor import _write_wal

        mock_container = MagicMock()
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        execution_id = str(uuid.uuid4())
        base = {
            "incident_id": "inc-1",
            "approval_id": "appr-1",
            "thread_id": "thr-1",
            "action_type": "execute",
            "proposed_action": "restart_vm",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            "executed_by": "user@example.com",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "preflight_blast_radius_size": 3,
            "verification_result": None,
            "verified_at": None,
            "rolled_back": False,
            "rollback_execution_id": None,
        }
        await _write_wal(execution_id, mock_cosmos, status="pending", base_record=base)

        mock_container.create_item.assert_called_once()
        call_body = mock_container.create_item.call_args[1]["body"]
        assert call_body["status"] == "pending"
        assert call_body["wal_written_at"] is not None
        assert call_body["id"] == execution_id

    async def test_write_wal_updates_existing_record(self):
        """_write_wal with update_fields uses replace_item to update the record."""
        from services.api_gateway.remediation_executor import _write_wal

        existing_record = {
            "id": "exec-1",
            "status": "pending",
            "approval_id": "appr-1",
            "incident_id": "inc-1",
        }
        mock_container = MagicMock()
        mock_container.query_items.return_value = [existing_record]
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        await _write_wal("exec-1", mock_cosmos, update_fields={"status": "complete"})

        mock_container.replace_item.assert_called_once()
        replaced_body = mock_container.replace_item.call_args[1]["body"]
        assert replaced_body["status"] == "complete"
        mock_container.create_item.assert_not_called()

    async def test_write_wal_never_raises_on_cosmos_error(self):
        """_write_wal does not propagate exceptions from Cosmos operations."""
        from services.api_gateway.remediation_executor import _write_wal

        mock_container = MagicMock()
        mock_container.create_item.side_effect = Exception("Cosmos error")
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        # Should not raise
        await _write_wal(
            "exec-1",
            mock_cosmos,
            status="pending",
            base_record={"incident_id": "inc-1"},
        )


# ---------------------------------------------------------------------------
# Pre-flight tests
# ---------------------------------------------------------------------------

class TestRunPreflight:
    """Tests for _run_preflight()."""

    async def test_preflight_passes_when_no_new_incidents_and_small_blast_radius(self):
        """Pre-flight passes when blast radius is small and no new incidents exist."""
        from services.api_gateway.remediation_executor import _run_preflight

        mock_topology = MagicMock()
        mock_topology.get_blast_radius.return_value = {"total_affected": 5}

        mock_container = MagicMock()
        mock_container.query_items.return_value = []
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        passed, size, reason = await _run_preflight(resource_id, "2026-01-01T00:00:00Z", mock_topology, mock_cosmos)

        assert passed is True
        assert size == 5
        assert reason == "ok"

    async def test_preflight_fails_on_new_active_incident(self):
        """Pre-flight fails when new active incidents are detected post-approval."""
        from services.api_gateway.remediation_executor import _run_preflight

        mock_topology = MagicMock()
        mock_topology.get_blast_radius.return_value = {"total_affected": 3}

        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"incident_id": "inc-new", "status": "new"}]
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        passed, size, reason = await _run_preflight(resource_id, "2026-01-01T00:00:00Z", mock_topology, mock_cosmos)

        assert passed is False
        assert reason == "new_active_incidents_detected"

    async def test_preflight_fails_on_large_blast_radius(self):
        """Pre-flight fails when blast radius exceeds the limit of 50."""
        from services.api_gateway.remediation_executor import _run_preflight

        mock_topology = MagicMock()
        mock_topology.get_blast_radius.return_value = {"total_affected": 51}

        mock_cosmos = MagicMock()

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        passed, size, reason = await _run_preflight(resource_id, "2026-01-01T00:00:00Z", mock_topology, mock_cosmos)

        assert passed is False
        assert size == 51
        assert reason == "blast_radius_exceeds_limit"

    async def test_preflight_passes_when_topology_unavailable(self):
        """Pre-flight passes gracefully when topology_client is None."""
        from services.api_gateway.remediation_executor import _run_preflight

        mock_container = MagicMock()
        mock_container.query_items.return_value = []
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        passed, size, reason = await _run_preflight(resource_id, "2026-01-01T00:00:00Z", None, mock_cosmos)

        assert passed is True
        assert size == 0


# ---------------------------------------------------------------------------
# Verification classification tests
# ---------------------------------------------------------------------------

class TestClassifyVerification:
    """Tests for _classify_verification() pure function."""

    def test_classify_verification_resolved(self):
        from services.api_gateway.remediation_executor import _classify_verification
        assert _classify_verification("Available", "Unavailable") == "RESOLVED"

    def test_classify_verification_resolved_from_degraded(self):
        from services.api_gateway.remediation_executor import _classify_verification
        assert _classify_verification("Available", "Degraded") == "RESOLVED"

    def test_classify_verification_improved(self):
        from services.api_gateway.remediation_executor import _classify_verification
        assert _classify_verification("Available", "Available") == "IMPROVED"

    def test_classify_verification_degraded(self):
        from services.api_gateway.remediation_executor import _classify_verification
        assert _classify_verification("Unavailable", "Available") == "DEGRADED"

    def test_classify_verification_degraded_status(self):
        from services.api_gateway.remediation_executor import _classify_verification
        assert _classify_verification("Degraded", "Available") == "DEGRADED"

    def test_classify_verification_timeout(self):
        from services.api_gateway.remediation_executor import _classify_verification
        assert _classify_verification("Unknown", "Unknown") == "TIMEOUT"


# ---------------------------------------------------------------------------
# Rollback trigger tests
# ---------------------------------------------------------------------------

class TestRollback:
    """Tests for _rollback()."""

    async def test_rollback_triggered_on_degraded(self):
        """_rollback for deallocate_vm executes start (the rollback_op) and returns a UUID."""
        from services.api_gateway.remediation_executor import _rollback

        mock_cosmos = MagicMock()
        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"id": "exec-1", "status": "complete"}]
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"

        with patch(
            "services.api_gateway.remediation_executor._execute_arm_action",
            new_callable=AsyncMock,
        ) as mock_arm, patch(
            "services.api_gateway.remediation_executor._write_wal",
            new_callable=AsyncMock,
        ) as mock_wal:
            mock_arm.return_value = {"success": True, "arm_op": "start", "resource_id": resource_id, "error": None}

            result = await _rollback(
                execution_id="exec-1",
                resource_id=resource_id,
                incident_id="inc-1",
                approval_id="appr-1",
                thread_id="thr-1",
                executed_by="system",
                proposed_action="deallocate_vm",
                credential=MagicMock(),
                cosmos_client=mock_cosmos,
            )

        assert result is not None
        # Verify UUID format
        uuid.UUID(result)
        # Verify start (rollback_op for deallocate_vm) was called
        mock_arm.assert_called_once()
        call_kwargs = mock_arm.call_args[0]
        assert call_kwargs[0] == "start"

    async def test_rollback_skipped_for_idempotent_action(self):
        """_rollback for restart_vm (rollback_op=None) returns None without calling ARM."""
        from services.api_gateway.remediation_executor import _rollback

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"

        with patch(
            "services.api_gateway.remediation_executor._execute_arm_action",
            new_callable=AsyncMock,
        ) as mock_arm:
            result = await _rollback(
                execution_id="exec-1",
                resource_id=resource_id,
                incident_id="inc-1",
                approval_id="appr-1",
                thread_id="thr-1",
                executed_by="system",
                proposed_action="restart_vm",
                credential=MagicMock(),
                cosmos_client=MagicMock(),
            )

        assert result is None
        mock_arm.assert_not_called()


# ---------------------------------------------------------------------------
# execute_remediation orchestration tests
# ---------------------------------------------------------------------------

class TestExecuteRemediation:
    """Tests for execute_remediation() main orchestration function."""

    async def test_execute_remediation_returns_aborted_when_disabled(self, monkeypatch):
        """Returns aborted result when REMEDIATION_EXECUTION_ENABLED=false."""
        from services.api_gateway.remediation_executor import execute_remediation

        monkeypatch.setenv("REMEDIATION_EXECUTION_ENABLED", "false")

        result = await execute_remediation(
            approval_id="appr-1",
            credential=MagicMock(),
            cosmos_client=MagicMock(),
            topology_client=None,
            approval_record={"thread_id": "thr-1", "decided_by": "user@example.com"},
        )

        assert result.status == "aborted"
        assert result.preflight_passed is False
        assert "REMEDIATION_EXECUTION_ENABLED" in (result.abort_reason or "")

    async def test_execute_remediation_returns_aborted_on_preflight_failure(self, monkeypatch):
        """Returns aborted result when pre-flight fails."""
        from services.api_gateway.remediation_executor import execute_remediation

        monkeypatch.setenv("REMEDIATION_EXECUTION_ENABLED", "true")

        approval_record = {
            "thread_id": "thr-1",
            "incident_id": "inc-1",
            "decided_by": "user@example.com",
            "decided_at": "2026-01-01T00:00:00Z",
            "proposed_action": "restart_vm",
            "proposal": {
                "action": "restart_vm",
                "target_resources": [
                    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
                ],
                "tool_parameters": {},
            },
        }

        with patch(
            "services.api_gateway.remediation_executor._run_preflight",
            new_callable=AsyncMock,
        ) as mock_pf, patch(
            "services.api_gateway.remediation_executor._execute_arm_action",
            new_callable=AsyncMock,
        ) as mock_arm:
            mock_pf.return_value = (False, 5, "new_active_incidents_detected")

            result = await execute_remediation(
                approval_id="appr-1",
                credential=MagicMock(),
                cosmos_client=MagicMock(),
                topology_client=None,
                approval_record=approval_record,
            )

        assert result.status == "aborted"
        assert result.preflight_passed is False
        mock_arm.assert_not_called()

    async def test_execute_remediation_full_happy_path(self, monkeypatch):
        """Full happy path: pre-flight passes, ARM executes, returns complete result."""
        from services.api_gateway.remediation_executor import execute_remediation

        monkeypatch.setenv("REMEDIATION_EXECUTION_ENABLED", "true")

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        approval_record = {
            "thread_id": "thr-1",
            "incident_id": "inc-1",
            "decided_by": "user@example.com",
            "decided_at": "2026-01-01T00:00:00Z",
            "proposed_action": "restart_vm",
            "proposal": {
                "action": "restart_vm",
                "target_resources": [resource_id],
                "tool_parameters": {},
            },
        }

        with patch(
            "services.api_gateway.remediation_executor._run_preflight",
            new_callable=AsyncMock,
        ) as mock_pf, patch(
            "services.api_gateway.remediation_executor._execute_arm_action",
            new_callable=AsyncMock,
        ) as mock_arm, patch(
            "services.api_gateway.remediation_executor._write_wal",
            new_callable=AsyncMock,
        ) as mock_wal, patch(
            "asyncio.create_task",
        ) as mock_task:
            mock_pf.return_value = (True, 3, "ok")
            mock_arm.return_value = {
                "success": True, "arm_op": "restart",
                "resource_id": resource_id, "error": None
            }
            mock_wal.return_value = None

            result = await execute_remediation(
                approval_id="appr-1",
                credential=MagicMock(),
                cosmos_client=MagicMock(),
                topology_client=None,
                approval_record=approval_record,
            )

        assert result.status == "complete"
        assert result.preflight_passed is True
        assert result.verification_scheduled is True
        assert result.blast_radius_size == 3
        # Verify execution_id is a UUID
        uuid.UUID(result.execution_id)


# ---------------------------------------------------------------------------
# WAL stale monitor test
# ---------------------------------------------------------------------------

class TestWalStaleMonitor:
    """Tests for run_wal_stale_monitor()."""

    async def test_wal_stale_monitor_emits_alert_for_stale_records(self, monkeypatch):
        """Monitor detects stale pending WAL records and emits alerts."""
        from services.api_gateway.remediation_executor import run_wal_stale_monitor

        stale_record = {
            "id": "stale-exec-1",
            "incident_id": "inc-1",
            "approval_id": "appr-1",
            "wal_written_at": "2026-01-01T00:00:00Z",
            "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
        }

        mock_container = MagicMock()
        mock_container.query_items.return_value = [stale_record]
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        call_count = 0

        async def mock_emit_alert(record, cosmos):
            nonlocal call_count
            call_count += 1

        with patch(
            "services.api_gateway.remediation_executor._emit_wal_alert",
            side_effect=mock_emit_alert,
        ), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            iteration = 0

            async def sleep_and_cancel(seconds):
                nonlocal iteration
                iteration += 1
                if iteration >= 2:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_and_cancel

            try:
                await run_wal_stale_monitor(mock_cosmos, interval_seconds=0)
            except asyncio.CancelledError:
                pass

        assert call_count >= 1
