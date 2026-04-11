---
plan: 38-1
title: "Security Tools — 5 new @ai_function tools in tools.py + requirements.txt"
status: complete
commits:
  - b6e56f0  feat(compute): add 4 security SDK packages to requirements.txt
  - 17f311a  feat(compute): add lazy imports for 4 security SDK packages
  - f828c8f  feat(compute): add 5 VM security compliance tools to tools.py
---

# Summary — Plan 38-1: Security Tools

## What Was Done

Added 5 new `@ai_function` security compliance tools to `agents/compute/tools.py`
and updated `agents/compute/requirements.txt` with the 4 required SDK packages.

## Changes

### `agents/compute/requirements.txt`
Added 4 new Azure SDK packages:
- `azure-mgmt-security>=7.0.0` — JIT policy queries
- `azure-mgmt-network>=23.0.0` — Effective NSG rules at NIC level
- `azure-mgmt-recoveryservicesbackup>=9.0.0` — Azure Backup RPO queries
- `azure-mgmt-recoveryservicessiterecovery>=1.0.0` — ASR replication health

### `agents/compute/tools.py`
**Lazy imports added** (after `ForecasterClient` block, before `approval_manager`):
- `SecurityCenter` from `azure.mgmt.security`
- `NetworkManagementClient` from `azure.mgmt.network`
- `RecoveryServicesBackupClient` from `azure.mgmt.recoveryservicesbackup`
- `SiteRecoveryManagementClient` from `azure.mgmt.recoveryservicessiterecovery`

All 4 registered in `_log_sdk_availability()` for startup diagnostics.

**5 new tools appended** (after `detect_performance_drift`):

| Tool | SDK | Key Return Fields |
|------|-----|-------------------|
| `query_defender_tvm_cve_count` | azure-mgmt-resourcegraph (ARG SecurityResources) | `vm_risk_score`, `critical`, `high`, `medium`, `low`, `total` |
| `query_jit_access_status` | azure-mgmt-security | `jit_enabled`, `policy_name`, `allowed_ports`, `active_sessions` |
| `query_effective_nsg_rules` | azure-mgmt-compute + azure-mgmt-network | `effective_rules`, `nic_name`, `inbound_deny_count`, `outbound_deny_count`, `high_priority_count` |
| `query_backup_rpo` | azure-mgmt-resourcegraph + azure-mgmt-recoveryservicesbackup | `backup_enabled`, `vault_name`, `last_backup_time`, `rpo_minutes` |
| `query_asr_replication_health` | azure-mgmt-resourcegraph + azure-mgmt-recoveryservicessiterecovery | `asr_enabled`, `replication_health`, `failover_readiness`, `rpo_seconds` |

## Acceptance Criteria — All Passed

```
@ai_function count:           33  (28 existing + 5 new ✅)
query_defender_tvm_cve_count: ✅ exists, vm_risk_score present
query_jit_access_status:      ✅ exists, jit_enabled present
query_effective_nsg_rules:    ✅ exists, effective_rules present
query_backup_rpo:             ✅ exists, backup_enabled present
query_asr_replication_health: ✅ exists, asr_enabled present
azure-mgmt-security:          ✅ in requirements.txt
azure-mgmt-network:           ✅ in requirements.txt
azure-mgmt-recoveryservicesbackup:         ✅ in requirements.txt
azure-mgmt-recoveryservicessiterecovery:   ✅ in requirements.txt
```

## Patterns Applied

- **Lazy imports**: all 4 new SDKs use `try/except ImportError` with `None` fallback
- **Never raise**: all tools catch `Exception`, log warning, return structured error dict
- **Graceful degradation**: backup/ASR/JIT tools return `{*_enabled: false}` when feature is not configured — not an error condition
- **vm_risk_score formula**: `critical×10 + high×5 + medium×2 + low×1`
- **NSG high_priority flag**: `priority < 200` flagged as `high_priority=True`
- **ARG vault discovery**: both `query_backup_rpo` and `query_asr_replication_health` use ARG to enumerate Recovery Services vaults before calling the respective backup/ASR SDK
