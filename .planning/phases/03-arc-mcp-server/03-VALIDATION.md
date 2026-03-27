---
phase: 3
slug: arc-mcp-server
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-26
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (unit + integration), Playwright 1.58.2 (E2E), Terraform CLI (IaC) |
| **Config file** | `services/arc-mcp-server/pyproject.toml` (installed in Wave 0) |
| **Quick run command** | `cd services/arc-mcp-server && python -m pytest tests/ -m unit -x -q --tb=short` |
| **Full suite command** | `cd services/arc-mcp-server && python -m pytest tests/ -v --tb=short --cov=arc_mcp_server --cov-fail-under=80` |
| **Estimated runtime** | ~20 seconds (unit), ~60 seconds (integration with mocks) |

---

## Sampling Rate

- **After every task commit:** Run `cd services/arc-mcp-server && python -m pytest tests/ -m unit -x -q --tb=short`
- **After every plan wave:** Run full suite + `cd terraform/modules/arc-mcp-server && terraform validate`
- **Before `/gsd:verify-work`:** Full suite must be green; 80% coverage gate must pass
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | AGENT-005 | unit | `from arc_mcp_server.server import mcp` imports without error; 9 tools registered | ✅ | ✅ green |
| 3-01-02 | 01 | 1 | AGENT-006 | unit | Each list tool impl returns dict with `total_count` key | ✅ | ✅ green |
| 3-01-03 | 01 | 1 | INFRA-001 | terraform | `cd terraform/modules/arc-mcp-server && terraform validate` exits 0 | ✅ | ✅ green |
| 3-02-01 | 02 | 2 | AGENT-005 | unit | `ALLOWED_MCP_TOOLS` in `agents/arc/tools.py` has ≥9 tools, no wildcards | ✅ | ✅ green |
| 3-02-02 | 02 | 2 | TRIAGE-006 | unit | `ARC_AGENT_SYSTEM_PROMPT` contains all 7 TRIAGE-006 workflow steps | ✅ | ✅ green |
| 3-02-03 | 02 | 2 | TRIAGE-006 | unit | `create_arc_agent()` raises `ValueError` when `ARC_MCP_SERVER_URL` is absent | ✅ | ✅ green |
| 3-03-01 | 03 | 2 | AGENT-006 | unit | `pytest tests/test_pagination.py -v` — 120-machine estate: `total_count == 120`, `len(servers) == 120` | ✅ | ✅ green |
| 3-03-02 | 03 | 2 | MONITOR-004 | unit | `pytest tests/test_arc_servers.py -v` — 5 `_is_prolonged_disconnect` cases (Connected/recent/prolonged/None/Error) | ✅ | ✅ green |
| 3-03-03 | 03 | 2 | MONITOR-005 | unit | `pytest tests/test_arc_servers.py -v` — AMA Succeeded + ChangeTracking Failed extension serialisation | ✅ | ✅ green |
| 3-03-04 | 03 | 2 | MONITOR-006 | unit | `pytest tests/test_arc_k8s.py -v` — Flux Compliant/NonCompliant, `flux_detected=True`, `total_configurations==2` | ✅ | ✅ green |
| 3-03-05 | 03 | 2 | AGENT-006 | unit | `pytest tests/test_arc_k8s.py -v` — 105 mock clusters: `total_count == 105` | ✅ | ✅ green |
| 3-04-01 | 04 | 3 | TRIAGE-006 | integration | `pytest agents/tests/integration/test_arc_triage.py -v -m integration` — full triage workflow produces `TriageDiagnosis` with `confidence_score`, `evidence`, `activity_log_findings` | ✅ | ✅ green |
| 3-04-02 | 04 | 3 | MONITOR-004 | integration | `pytest agents/tests/integration/test_arc_triage.py -v -m integration` — `last_status_change` >1h triggers `prolonged_disconnection=True` | ✅ | ✅ green |
| 3-04-03 | 04 | 3 | E2E-006 | e2e | `npx playwright test e2e/arc-mcp-server.spec.ts` — `total_count >= 100`, `total_count == len(servers)`, all 9 tools in `tools/list` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 infrastructure created in Plan 03-03 before writing implementation tests:

- [x] `services/arc-mcp-server/tests/__init__.py` — package docstring (AGENT-005, AGENT-006, MONITOR-004–006 reference)
- [x] `services/arc-mcp-server/tests/conftest.py` — shared fixtures: `_make_machine`, `_make_cluster`, `_make_extension`, `sample_machines_120`, `sample_clusters_105`
- [x] `agents/tests/integration/__init__.py` — integration test package docstring
- [x] `agents/tests/integration/test_arc_triage.py` — 6 integration tests with `pytest.mark.integration`
- [x] `e2e/arc-mcp-server.spec.ts` — Playwright E2E with mock ARM server seeded with 120 Arc servers
- [x] `services/arc-mcp-server/pyproject.toml` — pytest config with `pythonpath=["."]` and `asyncio_mode`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Arc MCP Server resolves via internal DNS | AGENT-005 | Requires live Container Apps environment with VNet integration | `az containerapp exec` into Arc Agent → `curl http://<arc-mcp-fqdn>/mcp/tools/list` returns 9 tools |
| Live Arc estate connectivity | AGENT-006 | Requires real Arc-enabled servers/clusters in subscription | Run `scripts/verify-arc-connectivity.sh` with real `ARC_SUBSCRIPTION_ID` set; assert `total_count > 0` in `arc_servers_list` response |
| Prolonged disconnection alert fires | MONITOR-004 | Requires a real Arc server that has been disconnected for >1 hour | Set `ARC_DISCONNECT_ALERT_HOURS=1`; find a Disconnected server with `lastStatusChange` >1h; assert `prolonged_disconnection=True` in tool response |
| Real Foundry thread for Arc triage | TRIAGE-006 | Requires live Foundry project with `ARC_MCP_SERVER_URL` configured as MCP connection | Submit an Arc incident via API gateway; inspect Foundry thread for TRIAGE-006 workflow steps in agent trace |

---

## Validation Sign-Off

- [x] All tasks have automated verify (pytest unit/integration or Playwright E2E)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all test infrastructure (conftest, __init__.py, fixtures)
- [x] No watch-mode flags
- [x] Feedback latency < 20s (unit), < 60s (integration)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** complete
