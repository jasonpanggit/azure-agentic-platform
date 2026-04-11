---
phase: 38
title: VM Security & Compliance Depth — Code Review
status: issues
reviewer: claude-code
date: 2026-04-11
---

# Phase 38 Code Review

**Files reviewed:**
- `agents/compute/tools.py` — 5 new tools (821 lines added)
- `agents/compute/agent.py` — registration at 4 locations
- `agents/tests/compute/test_compute_security.py` — 20 unit tests (892 lines)
- `agents/compute/requirements.txt` — 4 new SDK packages

---

## Summary

The implementation is structurally solid: all 5 tools follow project patterns (lazy imports, `instrument_tool_call`, `start_time = time.monotonic()`, never-raise). Two issues require fixes before merge: a **HIGH** NIC resource-group mismatch bug that will cause 404s whenever a NIC lives in a different resource group from its VM, and a **HIGH** silent-swallow in per-vault loops that drops errors without any logging, making multi-vault failures invisible. Two MEDIUM issues round out the list.

---

## CRITICAL

_None._

---

## HIGH

### H1 — `query_effective_nsg_rules`: NIC resource group passed incorrectly to network API

**File:** `tools.py` lines 3078–3079

```python
poller = network_client.network_interfaces.begin_list_effective_network_security_groups(
    resource_group, nic_name   # ← resource_group is the VM's RG, not the NIC's RG
)
```

The Azure `begin_list_effective_network_security_groups` API takes `resource_group_name` as the **NIC's** resource group, not the VM's. These are often the same, but they differ in two common real-world cases:

1. VMs deployed into a shared networking RG (NIC in `rg-network`, VM in `rg-compute`)
2. VMSS-managed VMs where NICs land in an auto-generated RG

The NIC's resource group is already embedded in `nic_id`:
```
/subscriptions/{sub}/resourceGroups/{NIC_RG}/providers/Microsoft.Network/networkInterfaces/{name}
```

The fix is to parse `nic_rg` from `nic_id.split("/")[4]` and pass it instead of `resource_group`.

**Impact:** Returns a 404 `ResourceGroupNotFound` error for any VM whose NIC is in a different RG — this is a hard failure, not a graceful degradation. The outer `except Exception` catches it and returns `query_status: error`, so it won't crash the agent, but the tool will be non-functional for a meaningful subset of real environments.

---

### H2 — `query_backup_rpo` and `query_asr_replication_health`: per-vault errors swallowed silently

**File:** `tools.py` lines 3312–3314 and 3505–3507

```python
except Exception:
    # Swallow per-vault errors and continue to next vault
    continue
```

Both vault-loop exception handlers have no logging. If every vault returns a 403, a throttle error, or a permissions error, the tool silently returns `backup_enabled: False` / `asr_enabled: False` — indistinguishable from "VM genuinely not protected." This violates the project convention that errors are always logged (project CLAUDE.md: "Never silently swallow errors").

The fix is a single `logger.warning(...)` call in each block:
```python
except Exception as vault_exc:
    logger.warning("query_backup_rpo: vault %s error (skipping): %s", vault_name, vault_exc)
    continue
```

**Impact:** Operational blindspot — an RBAC misconfiguration (e.g., backup client lacks Reader on a vault) will look identical to "VM has no backup," causing the LLM to incorrectly report a VM as unprotected.

---

## MEDIUM

### M1 — `query_jit_access_status`: `asc_location="eastus"` is a dead kwarg

**File:** `tools.py` line 2908

```python
client = SecurityCenter(credential, subscription_id, asc_location="eastus")
```

In `azure-mgmt-security >= 7.0.0` (the version pinned in `requirements.txt`), `SecurityCenter.__init__` signature is `(credential, subscription_id, **kwargs)`. The `asc_location` parameter existed in the old v2.x SDK where `SecurityCenter` was a flat client, not a multi-API client. In v7.0.0 it flows into `**kwargs` → `_configure(**kwargs)` and is silently ignored.

The call works at runtime (no error), but:
- It's misleading — the caller appears to be configuring a location that has no effect
- It creates a maintenance liability: if a future SDK version starts rejecting unknown kwargs via strict validation, this breaks silently

The fix is to remove `asc_location="eastus"` from the constructor call.

**Impact:** No runtime crash today, but dead code with misleading intent and a forward-compatibility risk.

---

### M2 — `query_asr_replication_health`: fuzzy VM name match can produce false positives

**File:** `tools.py` line 3468

```python
if fabric_obj_id == vm_resource_id_lower or vm_name.lower() in fabric_obj_id:
```

The fallback `vm_name.lower() in fabric_obj_id` substring match will return a false positive if another VM or VMSS has a name that contains `vm_name`. For example, VM `web-vm` will match a protected item for `web-vmss-001` because `"web-vm"` is a substring of `"web-vmss-001"`.

The substring fallback was presumably added to handle cases where `fabric_object_id` is a friendly name rather than a full resource ID. The exact match `fabric_obj_id == vm_resource_id_lower` is always correct; the fallback is the risk.

Consider either removing the fallback (rely on exact resource ID match, which is what the ARM API guarantees) or tightening it to a whole-word match:
```python
# Tighter: require /vm_name at end of ID segment
or fabric_obj_id.endswith(f"/virtualmachines/{vm_name.lower()}")
```

**Impact:** Could cause the LLM to believe ASR is configured for a VM when it is actually configured for a similarly-named resource. Incorrect DR status reporting.

---

## LOW

### L1 — Error return shapes are incomplete relative to success shapes

**File:** `tools.py` — error `except` blocks for `query_effective_nsg_rules`, `query_defender_tvm_cve_count`

On the error path, these tools return a minimal dict (`error`, `vm_name`, `query_status`, `duration_ms`). The success path returns 8–11 keys. This is consistent with some existing tools in the file but inconsistent with others (e.g., `query_jit_access_status` error path includes `jit_enabled: False`, and `query_backup_rpo` error path includes `backup_enabled: False`).

The JIT/backup/ASR pattern is better: always return the primary boolean status field so the LLM can reason about state even on error without key-presence checks. `query_effective_nsg_rules` and `query_defender_tvm_cve_count` error paths are missing `nic_name`/`effective_rules`/`critical`/`high`/etc.

**Impact:** LLM may throw a KeyError-equivalent reasoning error when accessing `result["backup_enabled"]` after an error. Low severity because the LLM should check `query_status` first, but inconsistency is a code quality concern.

---

### L2 — `query_effective_nsg_rules` missing test for the "no NIC" code path

**File:** `test_compute_security.py`

The early-return when no NIC is found (lines 3062–3076 of `tools.py`) is untested. The `test_nsg_empty_rules` test covers the NIC-found-but-no-rules path. There is no test for `network_profile = None` or `network_interfaces = []`.

**Impact:** Low — the code path is simple, but 20 tests with a gap in a documented code branch is a minor coverage miss. A test for this path would complete the 4-scenario matrix (success, not-configured, sdk=None, exception) for this tool.

---

## Pattern Consistency — PASS

The following project conventions are correctly followed across all 5 tools:

| Convention | Status |
|---|---|
| Module-level lazy import with `try/except ImportError` + `= None` | ✅ All 4 new SDKs |
| `_log_sdk_availability()` updated with new packages | ✅ |
| `start_time = time.monotonic()` at function entry | ✅ All 5 tools |
| `duration_ms` recorded in both try and except blocks | ✅ All 5 tools |
| `instrument_tool_call` context manager | ✅ All 5 tools |
| Tool functions never raise | ✅ All 5 tools |
| Structured error dict returned on exception | ✅ All 5 tools |
| `logger.info` on success path | ✅ All 5 tools |
| `logger.warning` on exception path | ✅ All 5 tools |
| SDK=None check before use | ✅ All 5 tools |
| ARG KQL uses f-string (consistent with existing tools) | ✅ |

---

## Security — PASS

- No hardcoded credentials
- `DefaultAzureCredential` via `get_credential()` throughout
- `tool_parameters` logged to telemetry contains only `resource_group` and `vm_name` — no secrets, no subscription IDs in the span attributes
- Error messages use `str(exc)` which may include Azure resource IDs, consistent with existing tools
- KQL f-string injection: `vm_resource_id` is constructed from validated SDK parameters (subscription_id, resource_group, vm_name) — same pattern used in existing tools; acceptable risk given these are internal tool invocations from Foundry agents with managed identity, not user-supplied strings to a public endpoint

---

## Agent Registration — PASS

All 4 registration locations in `agent.py` updated correctly:
1. Import block
2. System prompt section (`## VM Security & Compliance Tools`)
3. `COMPUTE_TOOL_NAMES` frozenset
4. `ChatAgent` tools list in `create_compute_agent()`
5. Tools list in `create_compute_agent_version()`

System prompt documentation is clear and actionable. The guidance distinguishing "not configured" from "error" states is particularly useful for LLM reasoning.

---

## Test Quality — PASS (with gap noted in L2)

| Tool | success | not-configured | sdk=None | exception | coverage |
|---|---|---|---|---|---|
| `query_defender_tvm_cve_count` | ✅ (×2) | — | ✅ | ✅ | Good |
| `query_jit_access_status` | ✅ | ✅ | ✅ | ✅ | Full |
| `query_effective_nsg_rules` | ✅ (×2) | ❌ missing | ✅ | ✅ | Gap (L2) |
| `query_backup_rpo` | ✅ | ✅ | ✅ | ✅ | Full |
| `query_asr_replication_health` | ✅ | ✅ | ✅ | ✅ | Full |

The `_instrument_mock()` helper is well-designed. Mock construction for the JIT and ASR tests correctly mirrors the SDK object graph. The RPO arithmetic check (`rpo_minutes > 0`) is appropriately loose rather than brittle.

---

## Action Items Before Merge

| Priority | Item |
|---|---|
| **HIGH** | Fix `query_effective_nsg_rules`: extract NIC resource group from `nic_id` and pass it to `begin_list_effective_network_security_groups` |
| **HIGH** | Add `logger.warning(...)` to the per-vault `except Exception: continue` blocks in `query_backup_rpo` and `query_asr_replication_health` |
| MEDIUM | Remove `asc_location="eastus"` from `SecurityCenter(...)` constructor call |
| MEDIUM | Tighten the ASR VM match fallback to avoid substring false positives |
| LOW | Add test for `query_effective_nsg_rules` with no-NIC path |
| LOW | Add `backup_enabled`/status sentinel keys to `query_defender_tvm_cve_count` and `query_effective_nsg_rules` error returns (for LLM key-access consistency) |
