# Phase 11: Patch Domain Agent - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-30
**Phase:** 11-patch-domain-agent
**Areas discussed:** Patch data depth & triage workflow, ARG access pattern & tool strategy, Orchestrator routing keywords, Remediation scope

---

## Patch Data Depth & Triage Workflow

| Option | Description | Selected |
|--------|-------------|----------|
| Assessment status only | PatchAssessmentResources only — current patch status, missing patches, compliance state per machine | |
| Assessment + installation history | PatchAssessmentResources + PatchInstallationResources — adds last-run history, failed installations, reboot-pending state | |
| Full patch picture | Assessment + installation + compliance rollup — adds a cross-subscription % compliant summary | ✓ |

**User's choice:** Full patch picture — assessment + installation history + compliance % rollup

---

| Option | Description | Selected |
|--------|-------------|----------|
| Critical + Security patches | Critical + Security only | |
| All classifications | Critical, Security, UpdateRollup, FeaturePack, ServicePack, Definition, Tools, Updates | ✓ |
| Configurable | Default Critical+Security, operator can override | |

**User's choice:** All classifications

---

| Option | Description | Selected |
|--------|-------------|----------|
| Single subscription | From incident envelope | |
| All accessible subscriptions | All subscriptions the managed identity has Reader access to | ✓ |
| Explicit list from payload | From operator query or incident payload | |

**User's choice:** All accessible subscriptions

---

| Option | Description | Selected |
|--------|-------------|----------|
| 7 days | Standard look-back window | ✓ |
| 30 days | Broader trend view | |
| Configurable | Default 7 days | |

**User's choice:** 7 days installation history

---

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include reboot-pending | Machines that installed but haven't rebooted | ✓ |
| No, skip reboot state | Simpler | |

**User's choice:** Yes — include reboot-pending status per machine

**Notes:** User also requested a KB-to-CVE mapper as an additional feature — given a KB article number, map to the list of CVEs it addresses.

---

## ARG Access Pattern & Tool Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| @ai_function wrappers via azure-mgmt-resourcegraph | Direct SDK, same pattern as compute/arc agents | ✓ |
| Direct REST calls | httpx/requests, more boilerplate | |
| Via Azure MCP Server | Not available for ARG | |

**User's choice:** `@ai_function` wrappers via `azure-mgmt-resourcegraph`

---

| Option | Description | Selected |
|--------|-------------|----------|
| ARG tools + Azure MCP Server monitor signals | ARG @ai_function + monitor.query_logs/metrics from Azure MCP Server | ✓ |
| ARG-only | No Azure Monitor correlation | |
| ARG + custom Log Analytics @ai_function | Skip Azure MCP Server | |

**User's choice:** ARG tools + Azure MCP Server monitor signals

**Notes:** User clarified that `ConfigurationData` table in Log Analytics stores software inventory for Arc-enabled servers (and Azure VMs with AMA agent), capturing installed and pending patches. Together with AUM patch assessment results from ARG, this provides a unified view. User confirmed ConfigurationData covers both Azure VMs and Arc-enabled servers, so the strategy should query both ARG and LAW always.

---

| Option | Description | Selected |
|--------|-------------|----------|
| ARG primary, ConfigurationData as enrichment | Lead with ARG, enrich with ConfigurationData | |
| Always query both | ARG + ConfigurationData in every triage | |
| Conditional on resource type | ARG for Azure VMs, ConfigurationData for Arc | |

**User's choice:** Always query both (user clarified ConfigurationData covers both Azure VMs and Arc)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Merge ARG + ConfigurationData by machine | Complementary data merged by machine name/resource ID | ✓ |
| ARG authoritative, ConfigurationData fills gaps | | |
| Split authority | | |

**User's choice:** Merge by machine

---

| Option | Description | Selected |
|--------|-------------|----------|
| Workspaces tied to affected Arc resources | Scope to relevant workspaces only | ✓ |
| Cross-workspace query (all workspaces) | All workspace IDs upfront | |
| All accessible workspaces | Broadest coverage | |

**User's choice:** Workspaces tied to affected resources

**Notes:** ConfigurationData KQL filter deferred to Claude's discretion — user pointed to https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata for the schema.

---

## Orchestrator Routing Keywords

| Option | Description | Selected |
|--------|-------------|----------|
| Patch-specific terms only | patch, patches, patching, update manager, windows update, security patch, patch compliance, patch status, missing patches, pending patches, kb article, hotfix | ✓ |
| Broader (includes update, CVE, vulnerability) | Adds: update, updates, software update, vulnerability, CVE | |
| Patch-specific + CVE + KB numbers | Patch terms + CVE-XXXX-XXXX pattern + KB\d+ | |

**User's choice:** Patch-specific terms only — avoids false-positive routing for "storage update", "update VM size" etc.

---

| Option | Description | Selected |
|--------|-------------|----------|
| microsoft.maintenance | Update Manager resource type prefix | ✓ |
| No resource type mapping | Keyword routing only | |
| microsoft.maintenance + patchAssessmentResults | Both ARG resource paths | |

**User's choice:** `microsoft.maintenance`

---

## Remediation Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only | Query and report only, no proposals | |
| Propose remediation (human approval required) | Consistent with REMEDI-001 and all other domain agents | ✓ |
| Propose + auto-trigger assessments | Can directly schedule AUM assessments | |

**User's choice:** Propose remediation, human approval required

---

| Option | Description | Selected |
|--------|-------------|----------|
| Schedule AUM patch installation | POST to ARM maintenance configuration endpoint | |
| Trigger assessment run only | Forces fresh scan, no installation | |
| Both — assessment run or full installation | Agent can propose either | ✓ |

**User's choice:** Both — assessment runs (low risk) and patch installations (higher risk)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Patch installation = high risk always | Always high regardless of classification | |
| Risk based on patch classification | Critical/Security=high, others=medium, assessment=low | ✓ |
| You decide per incident | Agent assesses contextually | |

**User's choice:** Risk based on classification

---

| Option | Description | Selected |
|--------|-------------|----------|
| Individual machines from incident | Precise, low blast radius | |
| By subscription + classification filter | Filtered group | |
| Both — agent decides based on incident type | Single-machine vs compliance incident | ✓ |

**User's choice:** Both — agent decides based on incident type

---

## Claude's Discretion

- Exact KQL for ConfigurationData queries (per MS docs schema)
- KB-to-CVE mapper implementation (static lookup vs. MSRC API vs. NVD API)
- Exact ARG KQL for PatchAssessmentResources and PatchInstallationResources
- Agent system prompt text
- Test fixture design for ARG and ConfigurationData mocks
- Terraform RBAC role for patch agent
- PATCH_AGENT_ID env var name

## Deferred Ideas

None.
