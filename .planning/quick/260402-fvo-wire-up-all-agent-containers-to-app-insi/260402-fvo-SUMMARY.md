# Quick Task 260402-fvo: Wire Up All Agent Containers to App Insights

**Status:** COMPLETE
**Branch:** `quick/260402-fvo-app-insights-wiring`
**Date:** 2026-04-02

---

## Summary

Closed the last observability gap: the Arc MCP Server had `azure-monitor-opentelemetry` in its dependencies and received `APPLICATIONINSIGHTS_CONNECTION_STRING` from Terraform, but never called `configure_azure_monitor()`. All 12 deployable containers now have active OTel auto-instrumentation.

## Tasks Completed

### Task 1: Add OTel initialization to Arc MCP Server
**Commit:** `39302d5`
**Files changed:** `services/arc-mcp-server/__main__.py`

Added `configure_azure_monitor()` call at module level (before uvicorn starts) following the same pattern as the API Gateway. Guarded with `if` check so local dev works without App Insights. Logs info/warning for OTel status.

### Task 2: Unit tests for OTel initialization
**Commit:** `f11ba58`
**Files changed:** `services/arc-mcp-server/tests/test_otel_init.py` (new)

Two tests verify both paths:
1. `test_otel_configured_when_env_var_present` — confirms `configure_azure_monitor()` called with correct connection string
2. `test_otel_disabled_when_env_var_missing` — confirms no call when env var absent

Uses `importlib.util.spec_from_file_location` to load `__main__.py` directly, avoiding sys.modules mock interference.

### Task 3: Observability audit checklist
**Commit:** `26ec859`
**Files changed:** `docs/observability-wiring.md` (new)

Documents all 12 containers with: runtime, OTel SDK, init call, Terraform env var source, and status. All 12 confirmed wired. Excludes web-ui (client-side) and detection plane (Fabric serverless).

## Verification

- 54/54 arc-mcp-server tests pass (52 existing + 2 new)
- Zero regressions
- `configure_azure_monitor()` properly called before uvicorn starts
- Graceful no-op when `APPLICATIONINSIGHTS_CONNECTION_STRING` is absent

## Files Changed

| File | Action |
|------|--------|
| `services/arc-mcp-server/__main__.py` | Modified — added OTel initialization |
| `services/arc-mcp-server/tests/test_otel_init.py` | Created — 2 unit tests |
| `docs/observability-wiring.md` | Created — audit checklist for all 12 containers |
