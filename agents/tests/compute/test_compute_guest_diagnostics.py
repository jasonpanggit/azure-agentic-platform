"""Tests for Phase 36 in-guest diagnostic tool functions.

Covers: execute_run_command, parse_boot_diagnostics_serial_log,
query_vm_guest_health, query_ama_guest_metrics.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    """Return a context-manager-compatible MagicMock."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


# ---------------------------------------------------------------------------
# TestExecuteRunCommand
# ---------------------------------------------------------------------------


class TestExecuteRunCommand:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.RunCommandInput")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_execute_run_command_linux_success(
        self, mock_cred, mock_compute_cls, mock_run_input_cls, mock_identity, mock_instr
    ):
        """Linux VM: RunShellScript command_id used and stdout returned."""
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute

        stdout_msg = MagicMock()
        stdout_msg.message = "Linux output"
        run_result = MagicMock()
        run_result.value = [stdout_msg]
        poller = MagicMock()
        poller.result.return_value = run_result
        mock_compute.virtual_machines.begin_run_command.return_value = poller

        from agents.compute.tools import execute_run_command

        result = execute_run_command(
            resource_group="rg1",
            vm_name="vm-linux",
            subscription_id="sub-1",
            script="df -h",
            os_type="Linux",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["stdout"] == "Linux output"
        assert result["command_id"] == "RunShellScript"
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.RunCommandInput")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_execute_run_command_windows_success(
        self, mock_cred, mock_compute_cls, mock_run_input_cls, mock_identity, mock_instr
    ):
        """Windows VM: RunPowerShellScript command_id used and stdout returned."""
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute

        stdout_msg = MagicMock()
        stdout_msg.message = "Windows output"
        run_result = MagicMock()
        run_result.value = [stdout_msg]
        poller = MagicMock()
        poller.result.return_value = run_result
        mock_compute.virtual_machines.begin_run_command.return_value = poller

        from agents.compute.tools import execute_run_command

        result = execute_run_command(
            resource_group="rg1",
            vm_name="vm-win",
            subscription_id="sub-1",
            script="Get-Disk",
            os_type="Windows",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["stdout"] == "Windows output"
        assert result["command_id"] == "RunPowerShellScript"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_execute_run_command_blocked_command(
        self, mock_cred, mock_compute_cls, mock_identity, mock_instr
    ):
        """Script containing 'rm -rf' is blocked before any SDK call."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command

        result = execute_run_command(
            resource_group="rg1",
            vm_name="vm-linux",
            subscription_id="sub-1",
            script="rm -rf /tmp/data",
            os_type="Linux",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "blocked" in result["error"].lower() or "blocked_command" in result
        # SDK must NOT have been called
        mock_compute_cls.return_value.virtual_machines.begin_run_command.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_execute_run_command_script_too_long(
        self, mock_cred, mock_compute_cls, mock_identity, mock_instr
    ):
        """Script exceeding 1500 characters is rejected."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command

        long_script = "echo hello\n" * 200  # well over 1500 chars

        result = execute_run_command(
            resource_group="rg1",
            vm_name="vm-linux",
            subscription_id="sub-1",
            script=long_script,
            os_type="Linux",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "exceed" in result["error"].lower() or "1500" in result["error"]

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_execute_run_command_missing_subscription(
        self, mock_cred, mock_compute_cls, mock_identity, mock_instr
    ):
        """Empty subscription_id should result in an SDK-level error dict."""
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        mock_compute.virtual_machines.begin_run_command.side_effect = Exception(
            "SubscriptionNotFound"
        )

        from agents.compute.tools import execute_run_command

        result = execute_run_command(
            resource_group="rg1",
            vm_name="vm-linux",
            subscription_id="",
            script="df -h",
            os_type="Linux",
            thread_id="thread-1",
        )

        assert "error" in result
        assert result["query_status"] == "error"
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_execute_run_command_sdk_unavailable(self, mock_cred, mock_identity, mock_instr):
        """When ComputeManagementClient is None (ImportError path), return graceful error."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command

        result = execute_run_command(
            resource_group="rg1",
            vm_name="vm-linux",
            subscription_id="sub-1",
            script="df -h",
            os_type="Linux",
            thread_id="thread-1",
        )

        assert "error" in result
        assert result["query_status"] == "error"
        assert "not installed" in result["error"]

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.RunCommandInput")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_execute_run_command_sdk_exception(
        self, mock_cred, mock_compute_cls, mock_run_input_cls, mock_identity, mock_instr
    ):
        """SDK raises exception → error dict with duration_ms, no re-raise."""
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        mock_compute.virtual_machines.begin_run_command.side_effect = RuntimeError(
            "Azure API unavailable"
        )

        from agents.compute.tools import execute_run_command

        result = execute_run_command(
            resource_group="rg1",
            vm_name="vm-linux",
            subscription_id="sub-1",
            script="df -h",
            os_type="Linux",
            thread_id="thread-1",
        )

        assert "error" in result
        assert result["query_status"] == "error"
        assert "duration_ms" in result
        assert "Azure API unavailable" in result["error"]


# ---------------------------------------------------------------------------
# TestParseBootDiagnosticsSerialLog
# ---------------------------------------------------------------------------


class TestParseBootDiagnosticsSerialLog:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_parse_serial_log_kernel_panic(self, mock_urlopen, mock_identity, mock_instr):
        """Log containing 'Kernel panic' is detected as kernel_panic event."""
        mock_instr.return_value = _instrument_mock()
        log_content = "[ 0.000000] Booting Linux\n[ 2.345678] Kernel panic - not syncing: VFS: Unable to mount root fs\n"
        mock_response = MagicMock()
        mock_response.read.return_value = log_content.encode("utf-8")
        mock_urlopen.return_value = mock_response

        from agents.compute.tools import parse_boot_diagnostics_serial_log

        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage.blob.core.windows.net/bootdiag/serial.txt?sas=token",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["summary"]["kernel_panic"] >= 1
        types = [e["type"] for e in result["detected_events"]]
        assert "kernel_panic" in types

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_parse_serial_log_oom_kill(self, mock_urlopen, mock_identity, mock_instr):
        """Log containing 'Out of memory: Kill process' is detected as oom_kill."""
        mock_instr.return_value = _instrument_mock()
        log_content = "[ 12.300000] Out of memory: Kill process 1234 (httpd) score 900 or sacrifice child\n"
        mock_response = MagicMock()
        mock_response.read.return_value = log_content.encode("utf-8")
        mock_urlopen.return_value = mock_response

        from agents.compute.tools import parse_boot_diagnostics_serial_log

        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage.blob.core.windows.net/bootdiag/serial.txt?sas=token",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["summary"]["oom_kill"] >= 1

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_parse_serial_log_disk_error(self, mock_urlopen, mock_identity, mock_instr):
        """Log containing 'I/O error' is detected as disk_error."""
        mock_instr.return_value = _instrument_mock()
        log_content = "[ 5.500000] blk_update_request: I/O error, dev sda, sector 123456\n"
        mock_response = MagicMock()
        mock_response.read.return_value = log_content.encode("utf-8")
        mock_urlopen.return_value = mock_response

        from agents.compute.tools import parse_boot_diagnostics_serial_log

        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage.blob.core.windows.net/bootdiag/serial.txt?sas=token",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["summary"]["disk_error"] >= 1

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_parse_serial_log_clean(self, mock_urlopen, mock_identity, mock_instr):
        """Clean log with no errors produces zero anomalies."""
        mock_instr.return_value = _instrument_mock()
        log_content = "[ 0.000000] Linux version 5.15.0\n[ 1.000000] Booting in normal mode\n[ 2.000000] Login prompt ready\n"
        mock_response = MagicMock()
        mock_response.read.return_value = log_content.encode("utf-8")
        mock_urlopen.return_value = mock_response

        from agents.compute.tools import parse_boot_diagnostics_serial_log

        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage.blob.core.windows.net/bootdiag/serial.txt?sas=token",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["total_events"] == 0
        assert all(v == 0 for v in result["summary"].values())

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_parse_serial_log_download_failure(self, mock_urlopen, mock_identity, mock_instr):
        """urllib raises an exception → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()
        mock_urlopen.side_effect = OSError("Connection timed out")

        from agents.compute.tools import parse_boot_diagnostics_serial_log

        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage.blob.core.windows.net/bootdiag/serial.txt?sas=token",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# TestQueryVmGuestHealth
# ---------------------------------------------------------------------------


class TestQueryVmGuestHealth:
    def _make_logs_client_mock(self, minutes_ago: int, mock_status_cls):
        """Build a LogsQueryClient mock returning a heartbeat minutes_ago rows."""
        mock_client = MagicMock()

        # Heartbeat response
        heartbeat_col = MagicMock()
        heartbeat_col.name = "MinutesAgo"
        heartbeat_table = MagicMock()
        heartbeat_table.columns = [heartbeat_col]
        heartbeat_table.rows = [[minutes_ago]]
        heartbeat_resp = MagicMock()
        heartbeat_resp.status = mock_status_cls.SUCCESS
        heartbeat_resp.tables = [heartbeat_table]

        # Metrics response (empty)
        metrics_resp = MagicMock()
        metrics_resp.status = mock_status_cls.SUCCESS
        metrics_resp.tables = []

        mock_client.query_workspace.side_effect = [heartbeat_resp, metrics_resp]
        return mock_client

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_guest_health_healthy(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """Heartbeat 2 minutes ago → heartbeat_status = 'healthy'."""
        mock_instr.return_value = _instrument_mock()
        mock_logs_cls.return_value = self._make_logs_client_mock(
            minutes_ago=2, mock_status_cls=mock_status_cls
        )

        from agents.compute.tools import query_vm_guest_health

        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["heartbeat_status"] == "healthy"
        assert result["last_heartbeat_minutes_ago"] == 2

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_guest_health_stale(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """Heartbeat 10 minutes ago → heartbeat_status = 'stale'."""
        mock_instr.return_value = _instrument_mock()
        mock_logs_cls.return_value = self._make_logs_client_mock(
            minutes_ago=10, mock_status_cls=mock_status_cls
        )

        from agents.compute.tools import query_vm_guest_health

        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["heartbeat_status"] == "stale"
        assert result["last_heartbeat_minutes_ago"] == 10

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_guest_health_offline(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """Heartbeat 20 minutes ago → heartbeat_status = 'offline'."""
        mock_instr.return_value = _instrument_mock()
        mock_logs_cls.return_value = self._make_logs_client_mock(
            minutes_ago=20, mock_status_cls=mock_status_cls
        )

        from agents.compute.tools import query_vm_guest_health

        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["heartbeat_status"] == "offline"
        assert result["last_heartbeat_minutes_ago"] == 20

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_guest_health_missing_workspace(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """Empty workspace_id returns skipped status — no SDK call made."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_vm_guest_health

        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="",
            thread_id="thread-1",
        )

        assert result["query_status"] == "skipped"
        assert "duration_ms" in result
        mock_logs_cls.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_guest_health_sdk_exception(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """LogsQueryClient raises → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = RuntimeError("workspace unavailable")
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import query_vm_guest_health

        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-abc",
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# TestQueryAmaGuestMetrics
# ---------------------------------------------------------------------------


class TestQueryAmaGuestMetrics:
    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_ama_metrics_success(
        self, mock_cred, mock_logs_cls, mock_status_cls, mock_identity, mock_instr
    ):
        """InsightsMetrics rows for cpu/memory/disk returned as structured buckets."""
        mock_instr.return_value = _instrument_mock()

        # Build mock rows
        col_tg = MagicMock()
        col_tg.name = "TimeGenerated"
        col_cpu_p50 = MagicMock()
        col_cpu_p50.name = "cpu_p50"
        col_cpu_p95 = MagicMock()
        col_cpu_p95.name = "cpu_p95"
        col_mem = MagicMock()
        col_mem.name = "memory_avg_mb"
        col_disk = MagicMock()
        col_disk.name = "disk_iops"

        mock_table = MagicMock()
        mock_table.columns = [col_tg, col_cpu_p50, col_cpu_p95, col_mem, col_disk]
        mock_table.rows = [
            ["2026-04-11T00:00:00Z", "45.0", "72.5", "2048.0", "150.0"],
            ["2026-04-11T01:00:00Z", "55.0", "80.0", "1900.0", "200.0"],
        ]

        mock_resp = MagicMock()
        mock_resp.status = mock_status_cls.SUCCESS
        mock_resp.tables = [mock_table]

        mock_client = MagicMock()
        mock_client.query_workspace.return_value = mock_resp
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import query_ama_guest_metrics

        result = query_ama_guest_metrics(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-abc",
            timespan_hours=24,
            thread_id="thread-1",
        )

        assert result["query_status"] == "success"
        assert result["total_buckets"] == 2
        assert len(result["buckets"]) == 2
        bucket = result["buckets"][0]
        assert bucket["cpu_p50"] == 45.0
        assert bucket["cpu_p95"] == 72.5
        assert bucket["memory_avg_mb"] == 2048.0
        assert bucket["disk_iops"] == 150.0

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_ama_metrics_missing_workspace(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """Empty workspace_id returns skipped status — no SDK call made."""
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_ama_guest_metrics

        result = query_ama_guest_metrics(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="",
            timespan_hours=24,
            thread_id="thread-1",
        )

        assert result["query_status"] == "skipped"
        assert "duration_ms" in result
        mock_logs_cls.assert_not_called()

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.get_credential")
    def test_query_ama_metrics_sdk_exception(
        self, mock_cred, mock_logs_cls, mock_identity, mock_instr
    ):
        """LogsQueryClient raises → error dict returned, no re-raise."""
        mock_instr.return_value = _instrument_mock()
        mock_client = MagicMock()
        mock_client.query_workspace.side_effect = RuntimeError("Log Analytics timeout")
        mock_logs_cls.return_value = mock_client

        from agents.compute.tools import query_ama_guest_metrics

        result = query_ama_guest_metrics(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-abc",
            timespan_hours=24,
            thread_id="thread-1",
        )

        assert result["query_status"] == "error"
        assert "error" in result
        assert "duration_ms" in result
        assert "Log Analytics timeout" in result["error"]
