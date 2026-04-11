---
wave: 2
depends_on:
  - 36-1-guest-diagnostic-tools-PLAN.md
files_modified:
  - agents/tests/compute/test_compute_guest_diagnostics.py
autonomous: true
---

# Plan 36-3: Tests for In-Guest Diagnostic Tools

## Goal

Create comprehensive tests for all 4 new Phase 36 tools in `agents/tests/compute/test_compute_guest_diagnostics.py`. Follow the established test pattern from `test_compute_new_tools.py` — mock SDK clients, test happy paths, error paths, and safety constraints.

## must_haves

- Test file exists at `agents/tests/compute/test_compute_guest_diagnostics.py`
- `TestExecuteRunCommand` class with tests: happy path Linux, happy path Windows, blocked command rejected, script too long, SDK missing, unknown OS type
- `TestParseBootDiagnosticsSerialLog` class with tests: kernel panic detected, OOM kill detected, clean log, download failure, truncation indicator
- `TestQueryVmGuestHealth` class with tests: healthy heartbeat, stale heartbeat, offline heartbeat, empty workspace_id, SDK missing
- `TestQueryAmaGuestMetrics` class with tests: happy path with buckets, empty results, empty workspace_id
- All tests pass via `python -m pytest agents/tests/compute/test_compute_guest_diagnostics.py -v`
- At least 18 test functions total

## Tasks

<task id="36-3-01">
<title>Create test file with TestExecuteRunCommand class</title>
<read_first>
- agents/tests/compute/test_compute_new_tools.py (the _instrument_mock helper and test patterns)
- agents/compute/tools.py (read execute_run_command, BLOCKED_COMMANDS_LINUX, MAX_SCRIPT_LENGTH)
</read_first>
<action>
Create `agents/tests/compute/test_compute_guest_diagnostics.py` with:

```python
"""Tests for Phase 36 in-guest VM diagnostic tools."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _instrument_mock():
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=MagicMock())
    m.__exit__ = MagicMock(return_value=False)
    return m


class TestExecuteRunCommand:

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_linux_happy_path(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        stdout_status = MagicMock()
        stdout_status.code = "ComponentStatus/StdOut/succeeded"
        stdout_status.message = "Filesystem      Size  Used Avail Use%\n/dev/sda1       30G   15G   14G  52%"
        stderr_status = MagicMock()
        stderr_status.code = "ComponentStatus/StdErr/succeeded"
        stderr_status.message = ""
        run_result = MagicMock()
        run_result.value = [stdout_status, stderr_status]
        mock_compute.virtual_machines.begin_run_command.return_value.result.return_value = run_result

        from agents.compute.tools import execute_run_command
        result = execute_run_command(
            resource_group="rg1", vm_name="vm1", subscription_id="sub1",
            script="df -h", os_type="Linux", thread_id="t1",
        )
        assert result["query_status"] == "success"
        assert "Filesystem" in result["stdout"]
        assert result["os_type"] == "Linux"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient")
    @patch("agents.compute.tools.get_credential")
    def test_windows_happy_path(self, mock_cred, mock_compute_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_compute = MagicMock()
        mock_compute_cls.return_value = mock_compute
        stdout_status = MagicMock()
        stdout_status.code = "ComponentStatus/StdOut/succeeded"
        stdout_status.message = "C: 100GB free"
        run_result = MagicMock()
        run_result.value = [stdout_status]
        mock_compute.virtual_machines.begin_run_command.return_value.result.return_value = run_result

        from agents.compute.tools import execute_run_command
        result = execute_run_command(
            resource_group="rg1", vm_name="vm1", subscription_id="sub1",
            script="Get-PSDrive", os_type="Windows", thread_id="t1",
        )
        assert result["query_status"] == "success"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    def test_blocked_command_rejected(self, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command
        result = execute_run_command(
            resource_group="rg1", vm_name="vm1", subscription_id="sub1",
            script="rm -rf /tmp/data", os_type="Linux", thread_id="t1",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower() or "blocked_command" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    def test_script_too_long_rejected(self, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command
        result = execute_run_command(
            resource_group="rg1", vm_name="vm1", subscription_id="sub1",
            script="x" * 1501, os_type="Linux", thread_id="t1",
        )
        assert "error" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.ComputeManagementClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_sdk_missing(self, mock_cred, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command
        result = execute_run_command(
            resource_group="rg1", vm_name="vm1", subscription_id="sub1",
            script="df -h", os_type="Linux", thread_id="t1",
        )
        assert "error" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    def test_unknown_os_type_rejected(self, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command
        result = execute_run_command(
            resource_group="rg1", vm_name="vm1", subscription_id="sub1",
            script="df -h", os_type="FreeBSD", thread_id="t1",
        )
        assert "error" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    def test_windows_blocked_command_rejected(self, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import execute_run_command
        result = execute_run_command(
            resource_group="rg1", vm_name="vm1", subscription_id="sub1",
            script="Remove-Item C:\\important", os_type="Windows", thread_id="t1",
        )
        assert "error" in result
```

This gives 7 tests for `execute_run_command`.
</action>
<acceptance_criteria>
- File exists at `agents/tests/compute/test_compute_guest_diagnostics.py`
- `grep -c "def test_" agents/tests/compute/test_compute_guest_diagnostics.py` returns >= 7
- `grep "class TestExecuteRunCommand" agents/tests/compute/test_compute_guest_diagnostics.py` returns a match
- `grep "blocked" agents/tests/compute/test_compute_guest_diagnostics.py` returns matches (blocked command tests)
</acceptance_criteria>
</task>

<task id="36-3-02">
<title>Add TestParseBootDiagnosticsSerialLog class</title>
<read_first>
- agents/tests/compute/test_compute_guest_diagnostics.py (verify task 36-3-01 output)
- agents/compute/tools.py (read parse_boot_diagnostics_serial_log and SERIAL_LOG_PATTERNS)
</read_first>
<action>
Append the following test class to `test_compute_guest_diagnostics.py`:

```python
class TestParseBootDiagnosticsSerialLog:

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_detects_kernel_panic(self, mock_urlopen, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        log_content = b"[  123.456] Normal boot\n[  234.567] Kernel panic - not syncing: Fatal exception\n[  345.678] end trace"
        mock_response = MagicMock()
        mock_response.read.return_value = log_content
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        from agents.compute.tools import parse_boot_diagnostics_serial_log
        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage/serial.txt", thread_id="t1",
        )
        assert result["query_status"] == "success"
        assert result["summary"]["kernel_panic"] >= 1
        assert any(e["type"] == "kernel_panic" for e in result["detected_events"])

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_detects_oom_kill(self, mock_urlopen, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        log_content = b"[  100.000] Starting services\n[  200.000] Out of memory: Kill process 1234 (java)\n"
        mock_response = MagicMock()
        mock_response.read.return_value = log_content
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        from agents.compute.tools import parse_boot_diagnostics_serial_log
        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage/serial.txt", thread_id="t1",
        )
        assert result["summary"]["oom_kill"] >= 1

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_clean_log_no_events(self, mock_urlopen, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        log_content = b"[  1.000] Booting Linux\n[  2.000] All systems nominal\n"
        mock_response = MagicMock()
        mock_response.read.return_value = log_content
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        from agents.compute.tools import parse_boot_diagnostics_serial_log
        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage/serial.txt", thread_id="t1",
        )
        assert result["total_events"] == 0
        assert all(v == 0 for v in result["summary"].values())

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.urllib.request.urlopen")
    def test_download_failure_returns_error(self, mock_urlopen, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_urlopen.side_effect = Exception("404 Not Found")

        from agents.compute.tools import parse_boot_diagnostics_serial_log
        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="https://storage/expired.txt", thread_id="t1",
        )
        assert "error" in result
        assert "duration_ms" in result

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    def test_empty_uri_returns_error(self, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import parse_boot_diagnostics_serial_log
        result = parse_boot_diagnostics_serial_log(
            serial_log_uri="", thread_id="t1",
        )
        assert "error" in result
```

This gives 5 tests for `parse_boot_diagnostics_serial_log`.
</action>
<acceptance_criteria>
- `grep "class TestParseBootDiagnosticsSerialLog" agents/tests/compute/test_compute_guest_diagnostics.py` returns a match
- `grep -c "def test_" agents/tests/compute/test_compute_guest_diagnostics.py` returns >= 12
- `grep "kernel_panic" agents/tests/compute/test_compute_guest_diagnostics.py` returns matches
- `grep "oom_kill" agents/tests/compute/test_compute_guest_diagnostics.py` returns matches
</acceptance_criteria>
</task>

<task id="36-3-03">
<title>Add TestQueryVmGuestHealth class</title>
<read_first>
- agents/tests/compute/test_compute_guest_diagnostics.py (verify prior tasks)
- agents/compute/tools.py (read query_vm_guest_health)
</read_first>
<action>
Append the following test class to `test_compute_guest_diagnostics.py`:

```python
class TestQueryVmGuestHealth:

    def _mock_logs_response(self, rows, columns):
        """Helper to build a mock LogsQueryClient response."""
        from unittest.mock import MagicMock, PropertyMock
        resp = MagicMock()
        resp.status = "Success"
        table = MagicMock()
        col_objects = [MagicMock(name=c) for c in columns]
        for col_obj, col_name in zip(col_objects, columns):
            type(col_obj).name = PropertyMock(return_value=col_name)
        table.columns = col_objects
        table.rows = rows
        resp.tables = [table]
        return resp

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.get_credential")
    def test_healthy_heartbeat(self, mock_cred, mock_status_cls, mock_logs_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_status_cls.SUCCESS = "Success"
        mock_logs = MagicMock()
        mock_logs_cls.return_value = mock_logs

        # First call: heartbeat query (MinutesAgo=2)
        heartbeat_resp = self._mock_logs_response([[" 2026-04-11T10:00:00Z", "2"]], ["LastHeartbeat", "MinutesAgo"])
        # Second call: metrics query
        metrics_resp = self._mock_logs_response([["45.2", "2048", "75.5"]], ["cpu_pct", "available_memory_mb", "disk_free_pct"])
        mock_logs.query_workspace.side_effect = [heartbeat_resp, metrics_resp]

        from agents.compute.tools import query_vm_guest_health
        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-123",
            thread_id="t1",
        )
        assert result["heartbeat_status"] == "healthy"
        assert result["query_status"] == "success"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.get_credential")
    def test_stale_heartbeat(self, mock_cred, mock_status_cls, mock_logs_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_status_cls.SUCCESS = "Success"
        mock_logs = MagicMock()
        mock_logs_cls.return_value = mock_logs

        heartbeat_resp = self._mock_logs_response([["2026-04-11T09:50:00Z", "10"]], ["LastHeartbeat", "MinutesAgo"])
        metrics_resp = self._mock_logs_response([], ["cpu_pct", "available_memory_mb", "disk_free_pct"])
        mock_logs.query_workspace.side_effect = [heartbeat_resp, metrics_resp]

        from agents.compute.tools import query_vm_guest_health
        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-123",
            thread_id="t1",
        )
        assert result["heartbeat_status"] == "stale"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.get_credential")
    def test_offline_no_heartbeat(self, mock_cred, mock_status_cls, mock_logs_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_status_cls.SUCCESS = "Success"
        mock_logs = MagicMock()
        mock_logs_cls.return_value = mock_logs

        heartbeat_resp = self._mock_logs_response([], ["LastHeartbeat", "MinutesAgo"])
        metrics_resp = self._mock_logs_response([], ["cpu_pct", "available_memory_mb", "disk_free_pct"])
        mock_logs.query_workspace.side_effect = [heartbeat_resp, metrics_resp]

        from agents.compute.tools import query_vm_guest_health
        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-123",
            thread_id="t1",
        )
        assert result["heartbeat_status"] == "offline"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    def test_empty_workspace_id_skips(self, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_vm_guest_health
        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/...", workspace_id="", thread_id="t1",
        )
        assert result["query_status"] == "skipped"

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient", None)
    @patch("agents.compute.tools.get_credential")
    def test_sdk_missing(self, mock_cred, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_vm_guest_health
        result = query_vm_guest_health(
            resource_id="/subscriptions/sub/...", workspace_id="ws-123", thread_id="t1",
        )
        assert "error" in result
```

This gives 5 tests for `query_vm_guest_health`.
</action>
<acceptance_criteria>
- `grep "class TestQueryVmGuestHealth" agents/tests/compute/test_compute_guest_diagnostics.py` returns a match
- `grep -c "def test_" agents/tests/compute/test_compute_guest_diagnostics.py` returns >= 17
- `grep "heartbeat_status" agents/tests/compute/test_compute_guest_diagnostics.py` returns matches
- Tests cover healthy, stale, and offline heartbeat states
</acceptance_criteria>
</task>

<task id="36-3-04">
<title>Add TestQueryAmaGuestMetrics class</title>
<read_first>
- agents/tests/compute/test_compute_guest_diagnostics.py (verify prior tasks)
- agents/compute/tools.py (read query_ama_guest_metrics)
</read_first>
<action>
Append the following test class to `test_compute_guest_diagnostics.py`:

```python
class TestQueryAmaGuestMetrics:

    def _mock_logs_response(self, rows, columns):
        """Helper to build a mock LogsQueryClient response."""
        from unittest.mock import MagicMock, PropertyMock
        resp = MagicMock()
        resp.status = "Success"
        table = MagicMock()
        col_objects = [MagicMock(name=c) for c in columns]
        for col_obj, col_name in zip(col_objects, columns):
            type(col_obj).name = PropertyMock(return_value=col_name)
        table.columns = col_objects
        table.rows = rows
        resp.tables = [table]
        return resp

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.get_credential")
    def test_happy_path_with_buckets(self, mock_cred, mock_status_cls, mock_logs_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_status_cls.SUCCESS = "Success"
        mock_logs = MagicMock()
        mock_logs_cls.return_value = mock_logs

        rows = [
            ["2026-04-11T00:00:00Z", "12.3", "45.6", "2048", "120"],
            ["2026-04-11T01:00:00Z", "15.1", "52.3", "1990", "135"],
        ]
        columns = ["TimeGenerated", "cpu_p50", "cpu_p95", "memory_avg_mb", "disk_iops"]
        mock_logs.query_workspace.return_value = self._mock_logs_response(rows, columns)

        from agents.compute.tools import query_ama_guest_metrics
        result = query_ama_guest_metrics(
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            workspace_id="ws-123",
            thread_id="t1",
        )
        assert result["query_status"] == "success"
        assert result["total_buckets"] == 2
        assert len(result["buckets"]) == 2

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    @patch("agents.compute.tools.LogsQueryClient")
    @patch("agents.compute.tools.LogsQueryStatus")
    @patch("agents.compute.tools.get_credential")
    def test_empty_results_no_ama(self, mock_cred, mock_status_cls, mock_logs_cls, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()
        mock_status_cls.SUCCESS = "Success"
        mock_logs = MagicMock()
        mock_logs_cls.return_value = mock_logs

        columns = ["TimeGenerated", "cpu_p50", "cpu_p95", "memory_avg_mb", "disk_iops"]
        mock_logs.query_workspace.return_value = self._mock_logs_response([], columns)

        from agents.compute.tools import query_ama_guest_metrics
        result = query_ama_guest_metrics(
            resource_id="/subscriptions/sub/...", workspace_id="ws-123", thread_id="t1",
        )
        assert result["query_status"] == "success"
        assert result["total_buckets"] == 0

    @patch("agents.compute.tools.instrument_tool_call")
    @patch("agents.compute.tools.get_agent_identity", return_value="id-test")
    def test_empty_workspace_id_skips(self, mock_identity, mock_instr):
        mock_instr.return_value = _instrument_mock()

        from agents.compute.tools import query_ama_guest_metrics
        result = query_ama_guest_metrics(
            resource_id="/subscriptions/sub/...", workspace_id="", thread_id="t1",
        )
        assert result["query_status"] == "skipped"
```

This gives 3 tests for `query_ama_guest_metrics`.

**Total test count: 7 + 5 + 5 + 3 = 20 tests.**
</action>
<acceptance_criteria>
- `grep "class TestQueryAmaGuestMetrics" agents/tests/compute/test_compute_guest_diagnostics.py` returns a match
- `grep -c "def test_" agents/tests/compute/test_compute_guest_diagnostics.py` returns >= 20
- `grep "total_buckets" agents/tests/compute/test_compute_guest_diagnostics.py` returns a match
- `grep "query_status.*skipped" agents/tests/compute/test_compute_guest_diagnostics.py` returns matches
- `python3 -c "import ast; ast.parse(open('agents/tests/compute/test_compute_guest_diagnostics.py').read()); print('OK')"` exits 0
</acceptance_criteria>
</task>

<task id="36-3-05">
<title>Run tests and verify all pass</title>
<read_first>
- agents/tests/compute/test_compute_guest_diagnostics.py
- pyproject.toml (for pythonpath config)
</read_first>
<action>
Run the test suite:
```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m pytest agents/tests/compute/test_compute_guest_diagnostics.py -v --tb=short
```

All 20 tests must pass. If any fail, fix the root cause in the test or tool implementation (tools are in plan 36-1, tests are in this plan). Common issues to check:
- Mock patch paths must be `agents.compute.tools.X` (not `compute.tools.X`)
- `_instrument_mock()` must be used for `instrument_tool_call`
- `LogsQueryStatus.SUCCESS` mock must match the string comparison in the tool
</action>
<acceptance_criteria>
- `python -m pytest agents/tests/compute/test_compute_guest_diagnostics.py -v --tb=short` exits 0
- Output shows >= 20 tests passed
- No test shows FAILED or ERROR status
</acceptance_criteria>
</task>

## Verification

```bash
# All tests pass
python -m pytest agents/tests/compute/test_compute_guest_diagnostics.py -v --tb=short

# Test count
grep -c "def test_" agents/tests/compute/test_compute_guest_diagnostics.py
# Expected: >= 20

# All 4 tool classes exist
grep "class Test" agents/tests/compute/test_compute_guest_diagnostics.py
# Expected: TestExecuteRunCommand, TestParseBootDiagnosticsSerialLog, TestQueryVmGuestHealth, TestQueryAmaGuestMetrics

# Existing tests still pass (no regressions)
python -m pytest agents/tests/compute/ -v --tb=short
```
