---
plan: 36-3
name: guest-diagnostic-tests
status: complete
one_liner: Created 20 unit tests for 4 new guest diagnostic tool functions
key-files:
  created:
    - agents/tests/compute/test_compute_guest_diagnostics.py
tasks-completed: 5
tests-added: 20
---

## Summary

Created test_compute_guest_diagnostics.py with 20 tests across 4 classes: TestExecuteRunCommand (7 tests covering Linux/Windows execution, blocked commands, script length limits, missing subscription, SDK unavailable, SDK exception), TestParseBootDiagnosticsSerialLog (5 tests covering kernel panic, OOM kill, disk error, clean log, download failure), TestQueryVmGuestHealth (5 tests covering healthy/stale/offline heartbeat classification, missing workspace, SDK exception), TestQueryAmaGuestMetrics (3 tests covering success with metrics, missing workspace, SDK exception). All tests pass.

## Fix Notes

Two issues resolved during implementation:
- `RunCommandInput` is `None` at module level when `azure-mgmt-compute` is not installed; tests that exercise the SDK call path must patch `agents.compute.tools.RunCommandInput` alongside `ComputeManagementClient` to avoid `NoneType is not callable` errors.
- `LogsQueryStatus` must be patched via `@patch("agents.compute.tools.LogsQueryStatus")` rather than imported directly from `azure.monitor.query`, since that package is not installed in the local test environment. The patched mock sentinel is passed through `_make_logs_client_mock(mock_status_cls=...)` so the `response.status == LogsQueryStatus.SUCCESS` comparison resolves correctly.
