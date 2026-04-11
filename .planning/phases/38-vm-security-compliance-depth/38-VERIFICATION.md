---
status: passed
verified_at: 2026-04-11
must_haves_passed: 19/19
test_results: 20/20 passed
---

# Phase 38 Verification — VM Security & Compliance Depth

## Summary

All must-have checks passed. 20/20 tests pass. Phase 38 goal achieved.

---

## Plan 38-1 Must-Haves — Security Tools (14/14)

| # | Check | Result |
|---|-------|--------|
| 1 | `query_defender_tvm_cve_count` exists with `@ai_function` | ✅ `def query_defender_tvm_cve_count(` found |
| 2 | `vm_risk_score` key present in return dict | ✅ `"vm_risk_score": vm_risk_score` present |
| 3 | `query_jit_access_status` exists with `@ai_function` | ✅ `def query_jit_access_status(` found |
| 4 | `jit_enabled` bool key present in return dict | ✅ `"jit_enabled": jit_enabled` present |
| 5 | `query_effective_nsg_rules` exists with `@ai_function` | ✅ `def query_effective_nsg_rules(` found |
| 6 | `effective_rules` list key present in return dict | ✅ `"effective_rules": effective_rules` present |
| 7 | `query_backup_rpo` exists with `@ai_function` | ✅ `def query_backup_rpo(` found |
| 8 | `backup_enabled` bool key present in return dict | ✅ `"backup_enabled": True/False` present |
| 9 | `query_asr_replication_health` exists with `@ai_function` | ✅ `def query_asr_replication_health(` found |
| 10 | `asr_enabled` bool key present in return dict | ✅ `"asr_enabled": True/False` present |
| 11 | `@ai_function` count >= 33 (28 existing + 5 new) | ✅ Count = **33** |
| 12 | `requirements.txt` contains `azure-mgmt-security>=7.0.0` | ✅ Present |
| 13 | `requirements.txt` contains `azure-mgmt-network>=23.0.0` | ✅ Present |
| 14 | `requirements.txt` contains `azure-mgmt-recoveryservicesbackup>=9.0.0` | ✅ Present |
| 15 | `requirements.txt` contains `azure-mgmt-recoveryservicessiterecovery>=1.0.0` | ✅ Present |

---

## Plan 38-2 Must-Haves — Agent Registration (5/5)

> **Note on grep counts:** Each tool appears **5 times** in `agent.py` (not 4 as the plan stated). The
> extra occurrence is the `## VM Security & Compliance Tools` body section added to `COMPUTE_AGENT_SYSTEM_PROMPT`.
> This is by design — the plan acceptance criteria was written before the body section was added.
> All 4 functional registration locations (import block, allowed-tools list, `ChatAgent(tools=[])`,
> `PromptAgentDefinition(tools=[])`) are correctly populated. Plan 38-2 summary documents this explicitly.

| # | Check | Result |
|---|-------|--------|
| 16 | `query_defender_tvm_cve_count` in `agent.py` at ≥4 locations | ✅ Count = 5 (4 functional + 1 body) |
| 17 | `query_jit_access_status` in `agent.py` at ≥4 locations | ✅ Count = 5 |
| 18 | `query_effective_nsg_rules` in `agent.py` at ≥4 locations | ✅ Count = 5 |
| 19 | `query_backup_rpo` in `agent.py` at ≥4 locations | ✅ Count = 5 |
| 20 | `query_asr_replication_health` in `agent.py` at ≥4 locations | ✅ Count = 5 |

---

## Plan 38-3 Must-Haves — Unit Tests (satisfied by test run)

| # | Check | Result |
|---|-------|--------|
| 21 | Test file exists: `agents/tests/compute/test_compute_security.py` | ✅ Present |
| 22 | 5 test classes (`^class Test`) | ✅ Count = **5** |
| 23 | 20 test methods (`def test_`) | ✅ Count = **20** |
| 24 | `TestQueryDefenderTvmCveCount` with 4 tests | ✅ Present |
| 25 | `TestQueryJitAccessStatus` with 4 tests | ✅ Present |
| 26 | `TestQueryEffectiveNsgRules` with 4 tests | ✅ Present |
| 27 | `TestQueryBackupRpo` with 4 tests | ✅ Present |
| 28 | `TestQueryAsrReplicationHealth` with 4 tests | ✅ Present |

---

## Test Run

```
cd agents && python3 -m pytest tests/compute/test_compute_security.py -q

======================== 20 passed, 1 warning in 0.36s =========================
```

- **Passed:** 20/20
- **Failed:** 0
- **Errors:** 0
- **Warning:** urllib3 LibreSSL notice (macOS dev machine, unrelated to tests)

---

## Phase Goal Assessment

**Goal:** Per-VM security posture as a first-class diagnostic signal in the compute agent.
Five new `@ai_function` tools + agent registration + unit tests.

| Deliverable | Status |
|-------------|--------|
| `query_defender_tvm_cve_count` — Defender TVM CVE counts + `vm_risk_score` | ✅ |
| `query_jit_access_status` — JIT policy + active sessions | ✅ |
| `query_effective_nsg_rules` — Effective NSG rules at NIC level | ✅ |
| `query_backup_rpo` — Azure Backup last backup time + RPO | ✅ |
| `query_asr_replication_health` — ASR replication health + failover readiness | ✅ |
| Agent registration in `agent.py` (4 functional locations each) | ✅ |
| 20 unit tests, all passing | ✅ |

**Phase 38 status: PASSED — all goals achieved.**
