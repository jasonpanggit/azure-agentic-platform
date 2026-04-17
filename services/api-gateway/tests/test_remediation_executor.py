from __future__ import annotations
"""Tests for remediation_executor.py — WAL, pre-flight, verification, rollback, orchestration."""
import os

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


# ---------------------------------------------------------------------------
# Verification feedback loop tests (Phase 35)
# ---------------------------------------------------------------------------

class TestBuildVerificationInstruction:
    """Tests for _build_verification_instruction()."""

    def test_build_verification_instruction_resolved(self):
        """RESOLVED instruction contains expected keywords."""
        from services.api_gateway.remediation_executor import _build_verification_instruction
        result = _build_verification_instruction("RESOLVED")
        assert "RESOLVED the issue" in result
        assert "recommend this incident be closed" in result

    def test_build_verification_instruction_degraded(self):
        """DEGRADED instruction contains expected keywords."""
        from services.api_gateway.remediation_executor import _build_verification_instruction
        result = _build_verification_instruction("DEGRADED")
        assert "DEGRADED" in result
        assert "Do NOT re-propose" in result

    def test_build_verification_instruction_unknown_falls_back_to_timeout(self):
        """Unknown result falls back to TIMEOUT instruction."""
        from services.api_gateway.remediation_executor import _build_verification_instruction
        result = _build_verification_instruction("UNKNOWN")
        assert "timed out" in result


class TestCancelActiveRuns:
    """Tests for _cancel_active_runs()."""

    async def test_cancel_active_runs_cancels_in_progress(self):
        """Cancels runs with status 'in_progress'."""
        from services.api_gateway.remediation_executor import _cancel_active_runs

        mock_run = MagicMock()
        mock_run.status = "in_progress"
        mock_run.id = "run-1"

        mock_client = MagicMock()
        mock_client.runs.list.return_value = [mock_run]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await _cancel_active_runs(mock_client, "thread-1")

        mock_client.runs.cancel.assert_called_once_with(thread_id="thread-1", run_id="run-1")

    async def test_cancel_active_runs_skips_completed(self):
        """Does not cancel runs with status 'completed'."""
        from services.api_gateway.remediation_executor import _cancel_active_runs

        mock_run = MagicMock()
        mock_run.status = "completed"
        mock_run.id = "run-2"

        mock_client = MagicMock()
        mock_client.runs.list.return_value = [mock_run]

        await _cancel_active_runs(mock_client, "thread-1")

        mock_client.runs.cancel.assert_not_called()


class TestInjectVerificationResult:
    """Tests for _inject_verification_result()."""

    async def test_inject_verification_result_respects_max_re_diagnosis(self, monkeypatch):
        """Does not call Foundry when re_diagnosis_count has reached the cap."""
        from services.api_gateway.remediation_executor import _inject_verification_result

        monkeypatch.setenv("MAX_RE_DIAGNOSIS_COUNT", "3")

        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"re_diagnosis_count": 3}]
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        with patch(
            "services.api_gateway.remediation_executor._cancel_active_runs",
            new_callable=AsyncMock,
        ) as mock_cancel:
            await _inject_verification_result(
                thread_id="thread-1",
                execution_id="exec-1",
                verification_result="IMPROVED",
                resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                proposed_action="restart_vm",
                rolled_back=False,
                incident_id="inc-1",
                cosmos_client=mock_cosmos,
            )

        # Should NOT have attempted Foundry injection
        mock_cancel.assert_not_called()

    async def test_inject_verification_result_increments_count(self, monkeypatch):
        """Increments re_diagnosis_count after successful injection."""
        from services.api_gateway.remediation_executor import _inject_verification_result

        monkeypatch.setenv("MAX_RE_DIAGNOSIS_COUNT", "3")
        monkeypatch.setenv("ORCHESTRATOR_AGENT_ID", "asst_123")

        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"re_diagnosis_count": 1}]
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        mock_foundry_client = MagicMock()
        mock_foundry_client.runs.list.return_value = []

        with patch(
            "services.api_gateway.remediation_executor._cancel_active_runs",
            new_callable=AsyncMock,
        ), patch(
            "services.api_gateway.foundry._get_foundry_client",
            return_value=mock_foundry_client,
        ), patch(
            "services.api_gateway.instrumentation.foundry_span",
        ) as mock_fspan, patch(
            "services.api_gateway.instrumentation.agent_span",
        ) as mock_aspan:
            # Make context managers work
            mock_fspan.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_fspan.return_value.__exit__ = MagicMock(return_value=False)
            mock_aspan.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_aspan.return_value.__exit__ = MagicMock(return_value=False)

            await _inject_verification_result(
                thread_id="thread-1",
                execution_id="exec-1",
                verification_result="IMPROVED",
                resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                proposed_action="restart_vm",
                rolled_back=False,
                incident_id="inc-1",
                cosmos_client=mock_cosmos,
            )

        # Verify patch_item was called with incr operation
        mock_container.patch_item.assert_called_once()
        call_kwargs = mock_container.patch_item.call_args
        ops = call_kwargs[1]["patch_operations"] if "patch_operations" in (call_kwargs[1] or {}) else call_kwargs[0][2] if len(call_kwargs[0]) > 2 else call_kwargs[1].get("patch_operations", [])
        assert any(
            op.get("op") == "incr" and op.get("path") == "/re_diagnosis_count" and op.get("value") == 1
            for op in ops
        )


class TestVerifyRemediationFeedback:
    """Tests for _verify_remediation thread injection wiring."""

    async def test_verify_remediation_calls_inject_when_thread_id_present(self):
        """_verify_remediation calls _inject_verification_result when thread_id is non-empty."""
        from services.api_gateway.remediation_executor import _verify_remediation

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"

        mock_cosmos = MagicMock()
        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"id": "exec-1", "status": "complete"}]
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        with patch(
            "services.api_gateway.remediation_executor._inject_verification_result",
            new_callable=AsyncMock,
        ) as mock_inject, patch(
            "services.api_gateway.remediation_executor._write_wal",
            new_callable=AsyncMock,
        ), patch(
            "asyncio.get_running_loop",
        ) as mock_loop:
            # Mock run_in_executor to return "Available" health
            mock_loop_instance = MagicMock()

            async def fake_run_in_executor(executor, fn):
                return "Available"

            mock_loop_instance.run_in_executor = fake_run_in_executor
            mock_loop.return_value = mock_loop_instance

            result = await _verify_remediation(
                execution_id="exec-1",
                resource_id=resource_id,
                incident_id="inc-1",
                thread_id="thread-123",
                proposed_action="restart_vm",
                credential=MagicMock(),
                cosmos_client=mock_cosmos,
            )

        mock_inject.assert_called_once()
        call_kwargs = mock_inject.call_args[1]
        assert call_kwargs["thread_id"] == "thread-123"
        # Available + Unknown pre-execution = IMPROVED
        assert call_kwargs["verification_result"] == "IMPROVED"

    async def test_verify_remediation_skips_inject_when_no_thread_id(self):
        """_verify_remediation does NOT call _inject_verification_result when thread_id is empty."""
        from services.api_gateway.remediation_executor import _verify_remediation

        resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"

        mock_cosmos = MagicMock()
        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"id": "exec-1", "status": "complete"}]
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        with patch(
            "services.api_gateway.remediation_executor._inject_verification_result",
            new_callable=AsyncMock,
        ) as mock_inject, patch(
            "services.api_gateway.remediation_executor._write_wal",
            new_callable=AsyncMock,
        ), patch(
            "asyncio.get_running_loop",
        ) as mock_loop:
            mock_loop_instance = MagicMock()

            async def fake_run_in_executor(executor, fn):
                return "Available"

            mock_loop_instance.run_in_executor = fake_run_in_executor
            mock_loop.return_value = mock_loop_instance

            result = await _verify_remediation(
                execution_id="exec-1",
                resource_id=resource_id,
                incident_id="inc-1",
                thread_id="",
                proposed_action="restart_vm",
                credential=MagicMock(),
                cosmos_client=mock_cosmos,
            )

        mock_inject.assert_not_called()


class TestMissedVerificationSweep:
    """Tests for run_missed_verification_sweep()."""

    async def test_run_missed_verification_sweep_processes_stale_records(self):
        """Sweep finds stale records and calls _verify_remediation for each."""
        from services.api_gateway.remediation_executor import run_missed_verification_sweep

        stale_record = {
            "id": "exec-stale-1",
            "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            "incident_id": "inc-stale-1",
            "thread_id": "thread-stale-1",
            "proposed_action": "restart_vm",
        }

        mock_container = MagicMock()
        mock_container.query_items.return_value = [stale_record]
        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = mock_container

        with patch(
            "services.api_gateway.remediation_executor._verify_remediation",
            new_callable=AsyncMock,
        ) as mock_verify:
            await run_missed_verification_sweep(
                cosmos_client=mock_cosmos,
                credential=MagicMock(),
            )

        mock_verify.assert_called_once()
        call_kwargs = mock_verify.call_args[1]
        assert call_kwargs["execution_id"] == "exec-stale-1"
        assert call_kwargs["thread_id"] == "thread-stale-1"
        assert call_kwargs["incident_id"] == "inc-stale-1"


# ---------------------------------------------------------------------------
# Auto-resolve tests (LOOP-003)
# ---------------------------------------------------------------------------


class TestAutoResolveOnVerification:
    """Tests for auto-resolve logic in _inject_verification_result (LOOP-003)."""

    async def test_auto_resolve_sets_resolved_at(self):
        """RESOLVED verification result patches resolved_at and auto_resolved=True on the incident."""
        from services.api_gateway.remediation_executor import _inject_verification_result

        # Mock Cosmos: re_diagnosis_count query returns count=0, patch_item records calls
        mock_incidents_container = MagicMock()
        mock_incidents_container.query_items.return_value = [{"re_diagnosis_count": 0}]
        mock_incidents_container.patch_item.return_value = None

        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value.get_container_client.return_value = (
            mock_incidents_container
        )

        mock_foundry_client = MagicMock()
        mock_foundry_client.runs.list.return_value = []

        with patch(
            "services.api_gateway.remediation_executor._cancel_active_runs",
            new_callable=AsyncMock,
        ), patch(
            "services.api_gateway.foundry._get_foundry_client",
            return_value=mock_foundry_client,
        ), patch(
            "services.api_gateway.instrumentation.foundry_span",
        ) as mock_fspan, patch(
            "services.api_gateway.instrumentation.agent_span",
        ) as mock_aspan, patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "asst_test123"}):
            mock_fspan.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_fspan.return_value.__exit__ = MagicMock(return_value=False)
            mock_aspan.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_aspan.return_value.__exit__ = MagicMock(return_value=False)

            await _inject_verification_result(
                thread_id="thread-test-1",
                execution_id="exec-test-1",
                verification_result="RESOLVED",
                resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                proposed_action="restart_vm",
                rolled_back=False,
                incident_id="inc-test-1",
                cosmos_client=mock_cosmos,
            )

        # patch_item should have been called at least twice:
        # once for re_diagnosis_count increment, once for auto-resolve
        assert mock_incidents_container.patch_item.call_count >= 2

        # Find the auto-resolve call — it contains /resolved_at and /auto_resolved paths
        all_calls = mock_incidents_container.patch_item.call_args_list
        auto_resolve_call = None
        for call in all_calls:
            ops = call[1].get("patch_operations", [])
            paths = [op.get("path") for op in ops]
            if "/resolved_at" in paths and "/auto_resolved" in paths:
                auto_resolve_call = call
                break

        assert auto_resolve_call is not None, "No patch_item call found with /resolved_at and /auto_resolved"

        # Verify the ops values
        ops = auto_resolve_call[1]["patch_operations"]
        ops_by_path = {op["path"]: op["value"] for op in ops}
        assert ops_by_path["/auto_resolved"] is True
        assert ops_by_path["/status"] == "resolved"
        assert "/resolved_at" in ops_by_path
        assert ops_by_path["/resolved_at"] is not None
