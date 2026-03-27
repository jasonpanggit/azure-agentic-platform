---
phase: 4
slug: detection-plane
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (Python), Terraform test (IaC) |
| **Config file** | `services/detection-plane/pyproject.toml` (Wave 0 installs) |
| **Quick run command** | `cd services/detection-plane && python -m pytest tests/unit/ -x -q` |
| **Full suite command** | `cd services/detection-plane && python -m pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds (unit), ~120 seconds (integration) |

---

## Sampling Rate

- **After every task commit:** Run `cd services/detection-plane && python -m pytest tests/unit/ -x -q`
- **After every plan wave:** Run `cd services/detection-plane && python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 1 | INFRA-007 | terraform | `cd terraform/modules/fabric && terraform validate` | ❌ W0 | ⬜ pending |
| 4-01-02 | 01 | 1 | DETECT-001 | terraform | `cd terraform/modules/eventhub && terraform validate` | ❌ W0 | ⬜ pending |
| 4-02-01 | 02 | 1 | DETECT-002 | unit | `pytest tests/unit/test_classify_domain.py -v` | ❌ W0 | ⬜ pending |
| 4-02-02 | 02 | 1 | DETECT-002 | unit | `pytest tests/unit/test_kql_pipeline.py -v` | ❌ W0 | ⬜ pending |
| 4-03-01 | 03 | 2 | DETECT-003 | unit | `pytest tests/unit/test_user_data_function.py -v` | ❌ W0 | ⬜ pending |
| 4-03-02 | 03 | 2 | DETECT-005 | unit | `pytest tests/unit/test_deduplication.py -v` | ❌ W0 | ⬜ pending |
| 4-03-03 | 03 | 2 | DETECT-006 | unit | `pytest tests/unit/test_alert_state.py -v` | ❌ W0 | ⬜ pending |
| 4-04-01 | 04 | 3 | DETECT-002 | integration | `pytest tests/integration/test_pipeline_flow.py -v -m integration` | ❌ W0 | ⬜ pending |
| 4-04-02 | 04 | 3 | DETECT-005 | integration | `pytest tests/integration/test_dedup_load.py -v -m integration` | ❌ W0 | ⬜ pending |
| 4-04-03 | 04 | 3 | AUDIT-003 | integration | `pytest tests/integration/test_activity_log.py -v -m integration` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `services/detection-plane/tests/__init__.py` — test package init
- [ ] `services/detection-plane/tests/unit/__init__.py` — unit test package
- [ ] `services/detection-plane/tests/integration/__init__.py` — integration test package
- [ ] `services/detection-plane/tests/conftest.py` — shared fixtures (mock Cosmos client, mock Azure Monitor client, mock Event Hub client)
- [ ] `services/detection-plane/tests/unit/test_classify_domain.py` — stubs for classify_domain() function (DETECT-002)
- [ ] `services/detection-plane/tests/unit/test_deduplication.py` — stubs for two-layer dedup logic (DETECT-005)
- [ ] `services/detection-plane/tests/unit/test_user_data_function.py` — stubs for UDF payload mapping (DETECT-003)
- [ ] `services/detection-plane/tests/unit/test_alert_state.py` — stubs for state transition logic (DETECT-006)
- [ ] `services/detection-plane/pyproject.toml` — pytest configuration with `pythonpath=["."]`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Eventhouse Event Hub connector configured | DETECT-001, DETECT-002 | Fabric Eventhouse connector may require manual portal setup if `azapi` can't configure it fully | Navigate to Fabric workspace → Eventhouse → Add data connection → Event Hub; verify `RawAlerts` table receives messages |
| Activator trigger rule configured on `DetectionResults` | DETECT-003 | Fabric Activator rule creation may not be fully automatable via Terraform | Navigate to Fabric Activator → New trigger → Table: `DetectionResults` → Condition: `domain != null` → Action: call UDF |
| 30-second alert latency SLA | ROADMAP SC-1 | Requires live Azure Monitor alert firing + real Event Hub ingestion | Inject synthetic alert via `az monitor metrics alert create`; query Eventhouse table after 30s |
| 60-second round-trip SLA | ROADMAP SC-2 | Requires live Fabric pipeline + running API gateway | Use OpenTelemetry traces to measure end-to-end latency |
| Suppression rule respect | DETECT-007 | Requires Azure Monitor processing rule creation against real Alert | Create suppression rule, fire matching alert, assert no Cosmos DB incident record after 60s |
| Activity Log OneLake mirror latency | AUDIT-003 | Requires subscription-level diagnostic settings + OneLake mirror | Generate activity log event; query OneLake `ActivityLog` table; verify within 5 minutes |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
