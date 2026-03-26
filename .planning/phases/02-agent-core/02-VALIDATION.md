---
phase: 2
slug: agent-core
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` — none yet, Wave 0 installs |
| **Quick run command** | `python -m pytest agents/ services/ -x -q --tb=short` |
| **Full suite command** | `python -m pytest agents/ services/ -v --tb=short --cov=agents --cov=services` |
| **Estimated runtime** | ~45 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest agents/ services/ -x -q --tb=short`
- **After every plan wave:** Run `python -m pytest agents/ services/ -v --tb=short --cov=agents --cov=services`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | AGENT-009 | lint | `spec-lint.yml` CI gate — all 7 spec files present | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 1 | INFRA-005 | infra | `terraform plan -target=module.agent-identities` exits 0 | ❌ W0 | ⬜ pending |
| 2-01-03 | 01 | 1 | INFRA-006 | infra | `terraform plan -target=module.agent-rbac` exits 0 | ❌ W0 | ⬜ pending |
| 2-02-01 | 02 | 2 | AGENT-002 | unit | `python -m pytest agents/tests/shared/test_envelope.py` | ❌ W0 | ⬜ pending |
| 2-02-02 | 02 | 2 | AGENT-007 | unit | `python -m pytest agents/tests/shared/test_budget.py` | ❌ W0 | ⬜ pending |
| 2-02-03 | 02 | 2 | AGENT-008 | security | `trivy image` returns 0 secrets in base image | ❌ W0 | ⬜ pending |
| 2-03-01 | 03 | 2 | DETECT-004 | integration | `python -m pytest services/api_gateway/tests/test_incidents.py` | ❌ W0 | ⬜ pending |
| 2-03-02 | 03 | 2 | DETECT-004 | integration | `curl -X POST /health` returns `{"status":"ok"}` | ❌ W0 | ⬜ pending |
| 2-04-01 | 04 | 4 | AGENT-001 | integration | `python -m pytest agents/tests/integration/test_handoff.py` | ❌ W0 | ⬜ pending |
| 2-04-02 | 04 | 4 | AGENT-004 | integration | `python -m pytest agents/tests/integration/test_mcp_tools.py` | ❌ W0 | ⬜ pending |
| 2-04-03 | 04 | 4 | TRIAGE-001 | integration | `python -m pytest agents/tests/integration/test_triage.py` | ❌ W0 | ⬜ pending |
| 2-04-04 | 04 | 4 | TRIAGE-004 | integration | Agent response contains `hypothesis`, `evidence`, `confidence_score` fields | ❌ W0 | ⬜ pending |
| 2-04-05 | 04 | 4 | REMEDI-001 | integration | `python -m pytest agents/tests/integration/test_remediation.py` | ❌ W0 | ⬜ pending |
| 2-05-01 | 05 | 5 | MONITOR-007 | integration | OTel spans present in App Insights with required fields | ❌ W0 | ⬜ pending |
| 2-05-02 | 05 | 5 | AUDIT-001 | integration | Span fields: `agentId`, `toolName`, `toolParameters`, `outcome`, `durationMs` all present | ❌ W0 | ⬜ pending |
| 2-05-03 | 05 | 5 | AUDIT-005 | integration | `agentId` in spans matches Entra Agent ID object ID (not "system") | ❌ W0 | ⬜ pending |
| 2-05-04 | 05 | 5 | AGENT-007 | integration | Cosmos DB record shows `status: aborted` when budget exceeded | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `agents/tests/__init__.py` — package init
- [ ] `agents/tests/shared/__init__.py` — shared tests package
- [ ] `agents/tests/shared/test_envelope.py` — stubs for AGENT-002 envelope validation
- [ ] `agents/tests/shared/test_budget.py` — stubs for AGENT-007 budget enforcement
- [ ] `agents/tests/integration/__init__.py` — integration tests package
- [ ] `agents/tests/integration/test_handoff.py` — stubs for AGENT-001 HandoffOrchestrator routing
- [ ] `agents/tests/integration/test_mcp_tools.py` — stubs for AGENT-004 MCP tool invocation
- [ ] `agents/tests/integration/test_triage.py` — stubs for TRIAGE-001 through TRIAGE-004
- [ ] `agents/tests/integration/test_remediation.py` — stubs for REMEDI-001
- [ ] `services/api_gateway/tests/__init__.py` — API gateway tests package
- [ ] `services/api_gateway/tests/test_incidents.py` — stubs for DETECT-004
- [ ] `pyproject.toml` — pytest config with `testpaths = ["agents", "services"]`
- [ ] `agents/shared/__init__.py` — package init for import resolution

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| No ARM writes without approval in live subscription | REMEDI-001 | Requires live Azure subscription activity log | `az monitor activity-log list --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ)` — assert no write operations from agent managed identity |
| Managed identity resolves via IMDS in deployed container | AGENT-008 | IMDS only available in Azure runtime environment | `az containerapp exec` → `curl -H "Metadata: true" http://169.254.169.254/metadata/identity/oauth2/token` returns token |
| End-to-end OTel trace visible in Application Insights | MONITOR-007 | Requires deployed App Insights with real ingestion | Azure Portal → App Insights → Transaction Search → filter `operation_Name: incidents` — full trace with handoff spans visible |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
