# Phase 65: Azure MCP Server v2 Upgrade — Research Findings

**Researched:** 2026-04-14
**Status:** Complete — ready for planning
**Method:** npm registry queries, `npx @azure/mcp@2.0.0 tools list`, MCP stdio protocol introspection, codebase analysis

---

## 1. Package Identity & Version Confirmation

### npm Registry Facts (verified 2026-04-14)

| Attribute | Value |
|---|---|
| **Package name** | `@azure/mcp` (unchanged from v1 beta) |
| **Latest version** | `2.0.0` (tagged `latest`) |
| **Repository** | `git+https://github.com/microsoft/mcp.git` |
| **Homepage** | `https://github.com/Microsoft/mcp/blob/main/servers/Azure.Mcp.Server` |
| **Distribution** | Platform-specific native binaries via optional deps (`@azure/mcp-linux-x64`, etc.) |
| **Current Dockerfile ARG** | `AZURE_MCP_VERSION=2.0.0-beta.34` |
| **Target Dockerfile ARG** | `AZURE_MCP_VERSION=2.0.0` |
| **Avoid** | `3.0.0-beta.1` (exists on npm — DO NOT USE) |

**Confirmed:** The npm package name stays `@azure/mcp`. The registry entry was transferred from `Azure/azure-mcp` (archived) to `microsoft/mcp`. No package rename needed.

### Version Lineage

```
...beta.33 → beta.34 (current) → beta.35..40 → 2.0.0 (GA) → 3.0.0-beta.1
```

Our Dockerfile upgrade path: `2.0.0-beta.34` → `2.0.0` (6 beta releases between, all backward-compatible within the 2.x line).

---

## 2. CRITICAL: MCP Tool Name Architecture Change (Breaking)

### v1 Beta (current — `2.0.0-beta.34`)

In v1, tools were exposed as **granular dotted names**:
```
monitor.query_logs
monitor.query_metrics
advisor.list_recommendations
resourcehealth.get_availability_status
storage.list_accounts
compute.list_vms
```

The MCP `tools/list` response exposed ~131 individual tool entries, each with its own name and schema.

### v2 GA (`2.0.0`)

In v2, the architecture changed to **intent-based namespace tools**. Each namespace is a **single MCP tool** that accepts an `intent` parameter and an optional `command` subcommand:

```json
{
  "name": "advisor",
  "inputSchema": {
    "properties": {
      "intent": { "type": "string" },    // required
      "command": { "type": "string" },    // optional
      "parameters": { "type": "object" }, // optional
      "learn": { "type": "boolean" }      // optional
    },
    "required": ["intent"]
  }
}
```

**MCP `tools/list` now returns 61 tools** (not 235+). The 235 number from `npx @azure/mcp tools list` is the CLI subcommand count — the MCP protocol exposes these as 61 namespace-level intent tools.

### What This Means for ALLOWED_MCP_TOOLS

**All existing dotted tool names are INVALID in v2.** The mapping:

| Old v1 Name (dotted) | New v2 MCP Tool Name | How Agent Invokes It |
|---|---|---|
| `monitor.query_logs` | `monitor` | `intent="query logs for resource X"` |
| `monitor.query_metrics` | `monitor` | `intent="query metrics for resource X"` |
| `applicationinsights.query` | `applicationinsights` | `intent="list recommendations"` |
| `advisor.list_recommendations` | `advisor` | `intent="list advisor recommendations"` |
| `resourcehealth.get_availability_status` | `resourcehealth` | `intent="get availability status"` |
| `resourcehealth.list_events` | `resourcehealth` | `intent="list health events"` |
| `storage.list_accounts` | `storage` | `intent="list storage accounts"` |
| `storage.get_account` | `storage` | `intent="get storage account"` |
| `fileshares.list` | `fileshares` | `intent="list file shares"` |
| `compute.list_vms` | `compute` | `intent="list VMs"` |
| `compute.get_vm` | `compute` | `intent="get VM details"` |
| `compute.list_disks` | `compute` | `intent="list disks"` |
| `keyvault.list_vaults` | `keyvault` | `intent="list key vaults"` |
| `keyvault.get_vault` | `keyvault` | `intent="get key vault"` |
| `role.list_assignments` | `role` | `intent="list role assignments"` |
| `appservice.list_apps` | `appservice` | `intent="list web apps"` |
| `appservice.get_app` | `appservice` | `intent="get web app"` |

### Impact Across ALL Agents

**Every agent with ALLOWED_MCP_TOOLS is affected.** Complete inventory:

| Agent | File | Current Dotted Names | v2 Namespace Names |
|---|---|---|---|
| **SRE** | `agents/sre/tools.py:49-56` | `monitor.query_logs`, `monitor.query_metrics`, `applicationinsights.query`, `advisor.list_recommendations`, `resourcehealth.get_availability_status`, `resourcehealth.list_events` | `monitor`, `applicationinsights`, `advisor`, `resourcehealth` |
| **Compute** | `agents/compute/tools.py:142-152` | `compute.list_vms`, `compute.get_vm`, `compute.list_disks`, `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status`, `advisor.list_recommendations`, `appservice.list_apps`, `appservice.get_app` | `compute`, `monitor`, `resourcehealth`, `advisor`, `appservice` |
| **Network** | `agents/network/tools.py:50-56` | `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status`, `advisor.list_recommendations`, `compute.list_vms` | `monitor`, `resourcehealth`, `advisor`, `compute` |
| **Storage** | `agents/storage/tools.py:20-27` | `storage.list_accounts`, `storage.get_account`, `fileshares.list`, `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status` | `storage`, `fileshares`, `monitor`, `resourcehealth` |
| **Security** | `agents/security/tools.py:63-71` | `keyvault.list_vaults`, `keyvault.get_vault`, `role.list_assignments`, `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status`, `advisor.list_recommendations` | `keyvault`, `role`, `monitor`, `resourcehealth`, `advisor` |
| **EOL** | `agents/eol/tools.py:71-75` | `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status` | `monitor`, `resourcehealth` |
| **Patch** | `agents/patch/tools.py:64-68` | `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status` | `monitor`, `resourcehealth` |
| **Arc** | `agents/arc/tools.py:67-82` | `arc_servers_list`, `arc_servers_get`, `arc_extensions_list`, `arc_k8s_list`, `arc_k8s_get`, `arc_k8s_gitops_status`, `arc_data_sql_mi_list`, `arc_data_sql_mi_get`, `arc_data_postgresql_list`, `monitor.query_logs`, `monitor.query_metrics`, `resourcehealth.get_availability_status` | Arc tools unchanged (custom MCP server), Azure tools → `monitor`, `resourcehealth` |

### Decision Required: Scope of ALLOWED_MCP_TOOLS Migration

**Option A (Recommended): Update ALL agents in this phase.**
- The tool name change is mechanical — dotted names → namespace names
- Each allowlist shrinks (fewer unique entries since subcommands collapse)
- If only SRE is updated, a redeployment of the MCP server would break all other agents

**Option B: Update only SRE + defer others.**
- Risk: MCP server is a shared sidecar. All agents that call it through Foundry MCP tool groups will break simultaneously when the server upgrades.
- This option is NOT safe.

**Recommendation: Option A is mandatory.** The MCP server is shared infrastructure — upgrading it to v2 changes the protocol for ALL consumers. All ALLOWED_MCP_TOOLS lists must be updated atomically with the server upgrade.

---

## 3. Advisor Namespace — v2 Tools

### MCP Protocol Tool Name: `advisor`

**Single tool** in v2 MCP protocol. Accepts `intent` string.

### CLI Subcommands (within the `advisor` namespace):

| Command | Description | Read-Only |
|---|---|---|
| `advisor recommendation list` | List Azure advisor recommendations in a subscription | Yes |

**Only 1 subcommand** in v2 — `advisor recommendation list`. This is equivalent to the old `advisor.list_recommendations`.

There is **no `advisor.get_recommendation`** tool in v2. The CONTEXT.md suggestion to "Add `advisor.get_recommendation` to `ALLOWED_MCP_TOOLS` if available in v2" — it is NOT available.

### Impact on SRE Agent

- Current: `advisor.list_recommendations` in ALLOWED_MCP_TOOLS
- New: `advisor` (the namespace itself is the tool)
- `query_advisor_recommendations` Python SDK tool: **no changes needed** — it uses `AdvisorManagementClient` directly, not MCP
- Docstring update for `OperationalExcellence` category: already accepted as a valid filter value

---

## 4. Container Apps Namespace — v2 Tools

### MCP Protocol Tool Name: `containerapps`

**Single tool** in v2 MCP protocol. Accepts `intent` string.

### CLI Subcommands (within the `containerapps` namespace):

| Command | Description | Read-Only | Key Parameters |
|---|---|---|---|
| `containerapps list` | List Azure Container Apps in a subscription. Optionally filter by resource group. Returns: name, location, resourceGroup, managedEnvironmentId, provisioningState. | Yes | `--subscription`, `--resource-group` |

**Only 1 subcommand** — `containerapps list`. There is **no `containerapps get`** in v2. The MCP tool only lists Container Apps — it does NOT return detailed revision/replica/traffic data.

### Impact on Self-Monitoring Design

The `containerapps list` MCP tool returns basic info only:
- name, location, resourceGroup, managedEnvironmentId, provisioningState

**It does NOT return:**
- Revision name, active revision traffic %, replica count
- Running status, scaling events, last modified time

**Conclusion:** The MCP `containerapps` tool is insufficient for the self-monitoring use case described in 65-CONTEXT.md. The `query_container_app_health` Python SDK tool (`azure-mgmt-appcontainers`) is **required** to get revision/replica/traffic detail.

**Recommendation:**
1. Add `containerapps` to SRE's `ALLOWED_MCP_TOOLS` for basic listing capability
2. Build `query_container_app_health` using `azure-mgmt-appcontainers` SDK for deep inspection
3. Both are needed — MCP for discovery, SDK for depth

---

## 5. `azure-mgmt-appcontainers` Package

### PyPI Facts (verified 2026-04-14)

| Attribute | Value |
|---|---|
| **Package** | `azure-mgmt-appcontainers` |
| **Latest stable** | `4.0.0` |
| **All versions** | 1.0.0, 2.0.0, 3.0.0, 3.1.0, 3.2.0, 4.0.0 |
| **Recommended pin** | `azure-mgmt-appcontainers>=4.0.0` |

### Key API for `query_container_app_health`

```python
from azure.mgmt.containerapp import ContainerAppsAPIClient

client = ContainerAppsAPIClient(credential, subscription_id)

# List container apps (with revision details)
app = client.container_apps.get(resource_group, app_name)
# Returns: provisioning_state, latest_revision_name, latest_ready_revision_name,
#          outbound_ip_addresses, managed_environment_id, configuration.ingress

# List revisions
revisions = client.container_apps_revisions.list_revisions(resource_group, app_name)
# Returns per revision: name, active, traffic_weight, replicas, running_state,
#                       provisioning_state, created_time, last_modified_time
```

**Note:** The import path is `azure.mgmt.containerapp` (singular), not `azure.mgmt.containerapps` (plural). The PyPI package name is `azure-mgmt-appcontainers` but the Python module is `azure.mgmt.containerapp`.

---

## 6. Auth / Transport Changes

### No Breaking Auth Changes

v2 continues to use `DefaultAzureCredential` / managed identity. No Dockerfile CMD changes needed for auth.

### Transport

v2 uses the same `--transport http` flag and binds to `localhost:5000`. The proxy.js pattern remains valid.

### Startup Improvement

v2 starts in 1-2s (vs 20s+ in beta). The proxy.js 503-while-warming pattern still works but the warm-up window shrinks dramatically. No code change needed — this is a free improvement.

### Image Size

v2 image is ~60% smaller due to platform-specific native binary distribution (the npm package pulls only the binary for the target platform via optional dependencies like `@azure/mcp-linux-x64`).

---

## 7. Full v2 MCP Namespace List

61 MCP protocol tools (namespace-level):

| Namespace | Description | In v1 Beta? |
|---|---|---|
| acr | Container Registry | Yes |
| advisor | Azure Advisor | Yes |
| aks | Kubernetes Service | Yes |
| appconfig | App Configuration | **New** |
| applens | App Lens diagnostics | Yes |
| applicationinsights | Application Insights | Yes |
| appservice | App Service | Yes |
| azd | Azure Developer CLI | **New** |
| azuremigrate | Azure Migrate | **New** (deferred) |
| azureterraformbestpractices | Terraform best practices | **New** |
| bicepschema | Bicep schema | Yes |
| cloudarchitect | Architecture design | **New** |
| communication | Communication Services | **New** |
| compute | VMs, VMSS, Disks | Yes |
| confidentialledger | Confidential Ledger | **New** |
| containerapps | Container Apps | **New** |
| cosmos | Cosmos DB | Yes |
| datadog | Datadog monitoring | **New** |
| deploy | Deployment operations | Yes |
| deviceregistry | Device Registry | **New** |
| documentation | Microsoft/Azure docs | **New** |
| eventgrid | Event Grid | Yes |
| eventhubs | Event Hubs | Yes |
| extension_azqr | Azure Quick Review | **New** |
| extension_cli_generate | CLI generation | **New** |
| extension_cli_install | CLI install | **New** |
| fileshares | File Shares | Yes |
| foundry | Foundry resources | **New** |
| foundryextensions | Foundry Extensions | **New** |
| functionapp | Function Apps | **New** |
| functions | Azure Functions codegen | **New** |
| get_azure_bestpractices | Best practices | **New** |
| grafana | Managed Grafana | Yes |
| group_list | Resource group list | Yes (was `group`) |
| group_resource_list | Resource list in RG | Yes (was `group`) |
| keyvault | Key Vault | Yes |
| kusto | Data Explorer / KQL | **New** |
| loadtesting | Load Testing | Yes |
| managedlustre | Managed Lustre | **New** |
| marketplace | Marketplace | **New** |
| monitor | Azure Monitor | Yes |
| mysql | MySQL Flexible Server | **New** |
| policy | Azure Policy | **New** |
| postgres | PostgreSQL Flex Server | **New** |
| pricing | Azure Pricing | **New** (deferred) |
| quota | Quota management | Yes |
| redis | Redis Cache | **New** |
| resourcehealth | Resource Health | Yes |
| role | RBAC | Yes |
| search | AI Search | Yes |
| servicebus | Service Bus | Yes |
| servicefabric | Service Fabric | Yes |
| signalr | SignalR | Yes |
| speech | AI Speech | Yes |
| sql | Azure SQL | **New** |
| storage | Storage | Yes |
| storagesync | Storage Sync | **New** |
| subscription_list | Subscription listing | Yes (was `subscription`) |
| virtualdesktop | Virtual Desktop | **New** |
| wellarchitectedframework | WAF guidance | **New** (deferred) |
| workbooks | Azure Workbooks | Yes |

---

## 8. Test Impact Analysis

### Existing SRE Tests (agents/tests/sre/test_sre_tools.py)

Tests that will break and need updating:

| Test | Current Assertion | Required Change |
|---|---|---|
| `test_allowed_mcp_tools_has_exactly_six_entries` | `len(ALLOWED_MCP_TOOLS) == 6` | Update count to match new list size |
| `test_allowed_mcp_tools_contains_expected_entries` | Checks 6 dotted names | Update to v2 namespace names + new entries |

Tests that will NOT break:
- All `query_*` tool tests (they mock Azure SDK, not MCP)
- `TestProposeRemediation` tests
- `TestPercentile` tests
- `TestCorrelateCrossDomain` tests

### New Tests Needed

1. `test_query_container_app_health_success` — success path with mocked `ContainerAppsAPIClient`
2. `test_query_container_app_health_error` — SDK exception path
3. `test_query_container_app_health_sdk_missing` — `ContainerAppsAPIClient = None` path
4. Updated ALLOWED_MCP_TOOLS count and content assertions

---

## 9. Scope Expansion Assessment

### Original CONTEXT.md Scope

The CONTEXT.md scoped this phase to:
1. Bump Dockerfile ARG
2. Wire advisor + containerapps into SRE agent
3. Update CLAUDE.md

### Actual Required Scope (from research)

The MCP tool name architecture change means **all 8 agents with ALLOWED_MCP_TOOLS must be updated**. This is not optional — the MCP server is shared infrastructure.

**Expanded scope:**
1. Bump Dockerfile ARG (same)
2. Update ALLOWED_MCP_TOOLS in **all 8 agents** (SRE, Compute, Network, Storage, Security, EOL, Patch, Arc)
3. Add `containerapps` to SRE ALLOWED_MCP_TOOLS (same)
4. Add `query_container_app_health` Python SDK tool to SRE (same)
5. Add `azure-mgmt-appcontainers>=4.0.0` to SRE requirements.txt (same)
6. Update all existing MCP tool tests across agents (new)
7. Update CLAUDE.md (same)

### Risk Mitigation

The ALLOWED_MCP_TOOLS migration is mechanical:
- Dotted names → namespace names
- Lists shrink (multiple dotted names per namespace collapse to one)
- No logic changes in any agent's Python SDK tools
- System prompts that mention specific MCP tool names need updating

---

## 10. Files to Modify (Complete List)

### Infrastructure
| File | Change |
|---|---|
| `services/azure-mcp-server/Dockerfile` | `ARG AZURE_MCP_VERSION=2.0.0-beta.34` → `2.0.0` |
| `services/azure-mcp-server/proxy.js` | No change needed |
| `.github/workflows/azure-mcp-server-build.yml` | No change needed |

### SRE Agent (primary target)
| File | Change |
|---|---|
| `agents/sre/tools.py` | Update ALLOWED_MCP_TOOLS, add lazy import for `ContainerAppsAPIClient`, add `_log_sdk_availability` entry, add `query_container_app_health` tool function |
| `agents/sre/agent.py` | Import + wire `query_container_app_health`, update system prompt |
| `agents/sre/requirements.txt` | Add `azure-mgmt-appcontainers>=4.0.0` |

### All Other Agents (ALLOWED_MCP_TOOLS migration)
| File | Change |
|---|---|
| `agents/compute/tools.py` | Update ALLOWED_MCP_TOOLS dotted → namespace |
| `agents/network/tools.py` | Update ALLOWED_MCP_TOOLS dotted → namespace |
| `agents/storage/tools.py` | Update ALLOWED_MCP_TOOLS dotted → namespace |
| `agents/security/tools.py` | Update ALLOWED_MCP_TOOLS dotted → namespace |
| `agents/eol/tools.py` | Update ALLOWED_MCP_TOOLS dotted → namespace |
| `agents/patch/tools.py` | Update ALLOWED_MCP_TOOLS dotted → namespace |
| `agents/arc/tools.py` | Update Azure MCP dotted → namespace (Arc MCP names unchanged) |

### Agent System Prompts
| File | Change |
|---|---|
| `agents/sre/agent.py` | System prompt: add containerapps + query_container_app_health |
| `agents/compute/agent.py` | System prompt: update MCP tool name references |
| `agents/network/agent.py` | System prompt: update MCP tool name references |
| `agents/storage/agent.py` | System prompt: update MCP tool name references |
| `agents/security/agent.py` | System prompt: update MCP tool name references |
| `agents/eol/agent.py` | System prompt: update MCP tool name references |
| `agents/patch/agent.py` | System prompt: update MCP tool name references |
| `agents/arc/agent.py` | System prompt: update Azure MCP tool name references |

### Tests
| File | Change |
|---|---|
| `agents/tests/sre/test_sre_tools.py` | Update MCP tool assertions, add `query_container_app_health` tests |
| All other agent test files with MCP tool assertions | Update dotted → namespace |

### Documentation
| File | Change |
|---|---|
| `CLAUDE.md` | Update Azure MCP Server section: repo `microsoft/mcp`, version `2.0.0`, note intent-based tool names, add `containerapps` to covered services |

---

## 11. Validation Architecture

### Automated Checks

```python
# 65-VALIDATION-CHECKS.py (or integrated into test suite)

# Check 1: Dockerfile ARG is correct
def test_dockerfile_mcp_version():
    with open("services/azure-mcp-server/Dockerfile") as f:
        content = f.read()
    assert "ARG AZURE_MCP_VERSION=2.0.0" in content
    assert "beta" not in content.split("AZURE_MCP_VERSION=")[1].split("\n")[0]

# Check 2: SRE tools.py has query_container_app_health function
def test_sre_tools_has_container_app_health():
    from agents.sre.tools import query_container_app_health
    assert callable(query_container_app_health)

# Check 3: ALLOWED_MCP_TOOLS includes containerapps
def test_sre_allowed_mcp_tools_has_containerapps():
    from agents.sre.tools import ALLOWED_MCP_TOOLS
    assert "containerapps" in ALLOWED_MCP_TOOLS

# Check 4: ALLOWED_MCP_TOOLS has NO dotted names (v1 format)
def test_no_dotted_mcp_tool_names():
    """All agents must use v2 namespace names, not v1 dotted names."""
    import importlib
    agents = [
        "agents.sre.tools",
        "agents.compute.tools",
        "agents.network.tools",
        "agents.storage.tools",
        "agents.security.tools",
        "agents.eol.tools",
        "agents.patch.tools",
        "agents.arc.tools",
    ]
    for mod_path in agents:
        mod = importlib.import_module(mod_path)
        tools = getattr(mod, "ALLOWED_MCP_TOOLS")
        for tool in tools:
            assert "." not in tool, (
                f"{mod_path}: dotted tool name '{tool}' found — "
                f"must use v2 namespace name (e.g., 'monitor' not 'monitor.query_logs')"
            )

# Check 5: SRE requirements.txt has azure-mgmt-appcontainers
def test_sre_requirements_has_appcontainers():
    with open("agents/sre/requirements.txt") as f:
        content = f.read()
    assert "azure-mgmt-appcontainers" in content

# Check 6: CLAUDE.md references microsoft/mcp repo
def test_claude_md_references_new_repo():
    with open("CLAUDE.md") as f:
        content = f.read()
    assert "microsoft/mcp" in content
    # Should not reference old archived repo as primary
    # (may still mention it in migration notes, which is fine)

# Check 7: SRE tests pass
# Run: pytest agents/tests/sre/ -v

# Check 8: All agent tests pass
# Run: pytest agents/tests/ -v

# Check 9: query_container_app_health follows tool pattern
def test_container_app_health_follows_tool_pattern():
    """Verify the tool follows project conventions."""
    import inspect
    from agents.sre.tools import query_container_app_health
    source = inspect.getsource(query_container_app_health)
    # Must have start_time pattern
    assert "start_time = time.monotonic()" in source
    # Must have duration_ms in both try and except
    assert source.count("duration_ms") >= 2
    # Must never raise (returns error dict)
    assert "query_status" in source
    # Must have @ai_function decorator
    assert "@ai_function" in source or "ai_function" in str(
        getattr(query_container_app_health, "__wrapped__", None)
    )

# Check 10: No v1 dotted names remain in system prompts
def test_no_dotted_names_in_system_prompts():
    """System prompts must not reference v1 dotted MCP tool names."""
    import importlib
    v1_patterns = [
        "monitor.query_logs", "monitor.query_metrics",
        "advisor.list_recommendations", "resourcehealth.get_availability_status",
        "resourcehealth.list_events", "applicationinsights.query",
        "storage.list_accounts", "storage.get_account",
        "compute.list_vms", "compute.get_vm", "compute.list_disks",
        "keyvault.list_vaults", "keyvault.get_vault",
        "role.list_assignments", "fileshares.list",
        "appservice.list_apps", "appservice.get_app",
    ]
    agents_with_prompts = [
        ("agents.sre.agent", "SRE_AGENT_SYSTEM_PROMPT"),
        # Add other agents as needed
    ]
    for mod_path, prompt_var in agents_with_prompts:
        mod = importlib.import_module(mod_path)
        prompt = getattr(mod, prompt_var)
        for pattern in v1_patterns:
            assert pattern not in prompt, (
                f"{mod_path}: v1 tool name '{pattern}' found in {prompt_var}"
            )
```

### CI Integration

The above checks should be added to the existing `agents/tests/sre/test_sre_tools.py` and a new cross-agent validation test file. Run with:

```bash
# SRE-specific tests
pytest agents/tests/sre/test_sre_tools.py -v

# Cross-agent MCP tool name validation
pytest agents/tests/test_mcp_v2_migration.py -v

# Full agent test suite
pytest agents/tests/ -v
```

---

## 12. Implementation Order (Recommended)

### Plan 65-1: Dockerfile + CLAUDE.md + ALLOWED_MCP_TOOLS Migration (all agents)

1. Update `services/azure-mcp-server/Dockerfile` ARG to `2.0.0`
2. Update ALLOWED_MCP_TOOLS in all 8 agent tools.py files (dotted → namespace)
3. Update system prompt tool references in all 8 agent agent.py files
4. Update existing MCP tool name tests across all agents
5. Add cross-agent validation test (`test_no_dotted_mcp_tool_names`)
6. Update CLAUDE.md Azure MCP Server section

### Plan 65-2: SRE Container Apps Self-Monitoring Tool

1. Add `azure-mgmt-appcontainers>=4.0.0` to `agents/sre/requirements.txt`
2. Add lazy import for `ContainerAppsAPIClient` from `azure.mgmt.containerapp`
3. Add `_log_sdk_availability` entry for `azure-mgmt-appcontainers`
4. Implement `query_container_app_health` `@ai_function` tool
5. Wire into `create_sre_agent()` tools list
6. Update SRE system prompt with self-monitoring instructions
7. Add 3+ unit tests (success, error, SDK-missing)
8. Run full SRE test suite

---

## 13. Key Risks

| Risk | Severity | Mitigation |
|---|---|---|
| MCP tool names changed but allowlist filtering may not exist in v2 intent model | HIGH | Verify that `ALLOWED_MCP_TOOLS` filtering mechanism still works with namespace-level names. If the framework matches tool names against the allowlist, namespace names must match exactly. |
| `containerapps list` MCP tool returns minimal data | LOW | SDK tool provides depth. MCP is for discovery only. |
| `azure.mgmt.containerapp` import path (singular) vs PyPI name (plural `appcontainers`) | MEDIUM | Document explicitly. Use `try/except ImportError` with correct import path. |
| System prompts reference specific MCP subcommands that no longer exist as discrete tools | MEDIUM | Update prompts to reference namespace tools with intent descriptions |
| v2 intent-based invocation may behave differently than v1 discrete tool calls | MEDIUM | Smoke test key workflows after upgrade: monitor log query, resource health check, advisor recommendations |

---

## 14. Answers to Specific Research Questions

### Q1: Exact npm package version string?
**A:** `@azure/mcp@2.0.0` — exists on npm registry, tagged as `latest`. Package name unchanged.

### Q2: Tools in the `advisor` namespace in v2?
**A:** Single tool — `advisor recommendation list` (equivalent to old `advisor.list_recommendations`). No `advisor.get_recommendation`. The MCP protocol exposes this as a single `advisor` tool with `intent` parameter.

### Q3: Tools in the `containerapps` namespace in v2?
**A:** Single tool — `containerapps list`. Returns name, location, resourceGroup, managedEnvironmentId, provisioningState. No `containerapps get`. Insufficient for deep self-monitoring (no revision/replica data).

### Q4: `azure-mgmt-appcontainers` latest version?
**A:** `4.0.0` on PyPI. Import path is `azure.mgmt.containerapp` (singular). Pin: `azure-mgmt-appcontainers>=4.0.0`.

### Q5: Breaking changes in existing tool names/signatures?
**A:** YES — CRITICAL. v2 changed from granular dotted tool names (`monitor.query_logs`) to intent-based namespace tools (`monitor` with `intent` parameter). All ALLOWED_MCP_TOOLS lists across all 8 agents must be updated.

### Q6: Auth/transport changes affecting Dockerfile CMD or proxy.js?
**A:** None. Same `DefaultAzureCredential`, same `--transport http`, same `localhost:5000` binding. Startup is faster (1-2s vs 20s), image is smaller. proxy.js unchanged.
