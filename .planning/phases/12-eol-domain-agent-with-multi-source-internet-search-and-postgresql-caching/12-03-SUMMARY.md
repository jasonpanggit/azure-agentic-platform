# PLAN-12-03 Summary

## Status: COMPLETE

**Commit:** `04f95d3`

---

## What Was Modified / Created

### Modified Files

| File | Change |
|------|--------|
| `agents/shared/routing.py` | Added `"eol"` domain entry with 12 keywords (end of life, eol, end-of-life, outdated software, software lifecycle, unsupported version, lifecycle status, deprecated version, software expiry, version support, eol status, lifecycle check). `QUERY_DOMAIN_KEYWORDS` now has 7 entries. |
| `agents/orchestrator/agent.py` | Added `"eol": "eol_agent"` to `DOMAIN_AGENT_MAP` (8 entries total). Added `"microsoft.lifecycle": "eol"` to `RESOURCE_TYPE_TO_DOMAIN` (13 entries). Added eol routing to system prompt (Domain → agent tool mapping section + natural-language routing section). |
| `terraform/modules/agent-apps/main.tf` | Added `eol` to `local.agents`; added `EOL_AGENT_ID` dynamic env block (orchestrator); added `POSTGRES_DSN` dynamic env block (eol agent). |
| `terraform/modules/agent-apps/variables.tf` | Added `eol_agent_id` and `postgres_dsn` variables. |
| `terraform/envs/staging/main.tf` | Wired `eol_agent_id = var.eol_agent_id` in `module "agent_apps"` block. |
| `terraform/envs/staging/variables.tf` | Added `eol_agent_id` variable. |
| `terraform/envs/prod/main.tf` | Wired `eol_agent_id = var.eol_agent_id` in `module "agent_apps"` block. |
| `terraform/envs/prod/variables.tf` | Added `eol_agent_id` variable. |
| `.github/workflows/deploy-all-images.yml` | Added `build-eol` job (after `build-patch`), added to `summary` job `needs` list, added summary table row. |

### Created Files

| File | Contents |
|------|----------|
| `agents/tests/eol/__init__.py` | Empty module init with docstring |
| `agents/tests/eol/test_eol_tools.py` | 56 unit tests across 14 test classes covering: ALLOWED_MCP_TOOLS, PRODUCT_SLUG_MAP, normalize_product_slug, _parse_eol_field, classify_eol_status, query_endoflife_date, query_ms_lifecycle, query_activity_log, query_os_inventory, query_k8s_versions, scan_estate_eol, search_runbooks, cache helpers (get/set_cached_eol), _fetch_with_retry |
| `agents/tests/eol/test_eol_agent.py` | 15 unit tests across 2 classes: TestEolAgentSystemPrompt (10 tests verifying prompt content and requirement traceability), TestCreateEolAgent (5 tests verifying factory function) |
| `agents/tests/integration/test_eol_routing.py` | 12 integration tests across 3 classes: TestEolDomainAgentMap, TestEolResourceTypeToDomain, TestEolQueryKeywords |

---

## Test Results

```
86 passed in 5.05s (using .venv/bin/python3 — project venv with agent_framework installed)
```

| Test File | Tests | Result |
|-----------|-------|--------|
| `agents/tests/eol/test_eol_agent.py` | 15 | ✅ All pass |
| `agents/tests/eol/test_eol_tools.py` | 56 | ✅ All pass |
| `agents/tests/integration/test_eol_routing.py` | 12 | ✅ All pass |
| **Total** | **86** | **✅ 86/86** |

Existing test suite (non-integration): **177 passed, 0 failures**

---

## Deviations from Plan

### Agent name format: underscore vs hyphen

The plan specified `"eol": "eol-agent"` (hyphen) in `DOMAIN_AGENT_MAP`. However, a parallel subagent refactored the orchestrator during this plan execution to use underscore-format tool names (`compute_agent`, `patch_agent`, etc.) consistent with the Foundry connected-agent name pattern (`^[a-zA-Z_]+$`). The eol entry was added as `"eol": "eol_agent"` to maintain consistency with this established convention.

Integration tests were updated to assert `DOMAIN_AGENT_MAP["eol"] == "eol_agent"` accordingly.

### Test runner: venv Python required

Tests must run with `.venv/bin/python3` (Python 3.14 with project dependencies including `agent_framework`) rather than system `python3` (Python 3.9). The `MCPStreamableHTTPTool` import in `agents/eol/agent.py` requires the venv version of `agent_framework`.

The `test_eol_agent.py` tests use a module-level mock approach (`_import_eol_agent()` with `sys.modules` patching) that works correctly under the venv Python.

### Terraform fmt: no changes needed

All Terraform files passed `terraform fmt -check` without requiring format corrections.

---

## Verification Commands Passed

```bash
# routing.py — 7 keyword domains ✅
python3 -c "from agents.shared.routing import QUERY_DOMAIN_KEYWORDS; assert len(QUERY_DOMAIN_KEYWORDS) == 7"

# orchestrator — 8 DOMAIN_AGENT_MAP entries, 13 RESOURCE_TYPE_TO_DOMAIN entries ✅
grep DOMAIN_AGENT_MAP agents/orchestrator/agent.py  # 8 entries including eol
grep RESOURCE_TYPE_TO_DOMAIN agents/orchestrator/agent.py  # 13 entries including microsoft.lifecycle

# Terraform fmt ✅
terraform fmt -check terraform/modules/agent-apps/
terraform fmt -check terraform/envs/staging/
terraform fmt -check terraform/envs/prod/

# CI/CD ✅
grep -q "build-eol" .github/workflows/deploy-all-images.yml

# All tests ✅
.venv/bin/python3 -m pytest agents/tests/eol/ agents/tests/integration/test_eol_routing.py -v
# → 86 passed in 5.05s
```
