# World-Class AIOps Platform — Phases 29–34 Design Spec

**Date:** 2026-04-11  
**Status:** Draft — Pending User Approval  
**Authors:** Platform Team  
**Phases:** 29 (Foundry Migration) → 30 (SOP Engine) → 31 (SOP Library) → 32 (VM Depth) → 33 (Evaluation) → 34 (AI Search RAG)  
**Foundry Design Principle:** Use Foundry-native capabilities at every layer. SOP files live in a Foundry-managed vector store (Basic setup — no separate storage account). Runbooks migrate to Azure AI Search (Foundry connection). All agents versioned via `create_version`. Evaluation via `azure-ai-evaluation`. Tracing via `AIProjectInstrumentor` + App Insights.

---

## 1. Context and Motivation

The AAP platform has completed 28 phases and is running in production with 9 agents, a Next.js web UI, Teams bot, and full detection plane. However, the platform was built on `azure-ai-projects` 1.x patterns (threads/runs model, `create_agent`, `AgentsClient`) which are superseded by the 2.0.x Foundry SDK. Additionally, several world-class AIOps capabilities are missing:

- Agents are not natively visible or manageable in the new Foundry portal (no versioning, no playground, no built-in knowledge sources)
- No externalized SOP/workflow engine — triage procedures are hardcoded in Python system prompt strings
- VM, Arc VM, VMSS, and AKS domains lack depth (stubs, missing tools, no HITL remediation at agent level)
- No continuous evaluation or quality gates on agent behaviour
- Teams notification limited to approval Adaptive Cards; no general-purpose alert/outcome notifications
- Runbook RAG uses pgvector only; Foundry-native knowledge sources (FileSearch, AI Search) not leveraged

These 6 phases close every identified gap and fully leverage the Foundry Discover → Build → Operate stack.

---

## 2. Success Criteria

| Metric | Target | Phase |
|--------|--------|-------|
| All 9 agents visible in Foundry portal with version history | 100% | 29 |
| OTel trace waterfall visible per agent run in Foundry portal | All agents instrumented | 29 |
| SOP loaded and grounding agent before every incident run | 100% of incident runs | 30 |
| Teams + email notification coverage | All SOP NOTIFY steps | 30 |
| SOP library coverage | ≥30 SOPs across all domains | 31 |
| Patch/EOL triage stubs replaced with real SDK calls | 4 stubs → real | 32 |
| VM/Arc/VMSS/AKS HITL remediation tools | ≥15 new tools | 32 |
| Agentic eval scores tracked per agent | TaskAdherence ≥ 4/5 | 33 |
| Continuous eval pipeline running in CI | ≥ weekly | 33 |
| SOP/runbook knowledge via FileSearch (portal-native) | Vector store attached | 34 |
| Runbook RAG via Azure AI Search | Index migrated | 34 |

---

## 3. Phase 29 — Foundry Platform Migration

### 3.1 Goal

Migrate all 9 agents from `azure-ai-projects` 1.x patterns to 2.0.x. Every agent becomes a versioned `PromptAgentDefinition` registered with Foundry Agent Service. A2A topology replaces ad-hoc connected_agent handoffs. OTel tracing wired to App Insights. All agents visible and inspectable in the Foundry portal.

### 3.2 SDK Migration: Key Breaking Changes

| 1.x Pattern | 2.0.x Pattern |
|-------------|---------------|
| `AgentsClient(endpoint, credential)` | `AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=...)` |
| `client.agents.create_agent(model, tools, instructions)` | `project.agents.create_version(agent_name, definition=PromptAgentDefinition(...))` |
| Threads + Runs (`create_thread`, `create_run`, `create_and_process_run`) | Responses API: `openai.responses.create(input, extra_body={"agent_reference": ...})` |
| Multi-turn: `create_message` on thread | `openai.conversations.create()` + `openai.responses.create(conversation=conv.id, ...)` |
| `FileSearchTool` via `tool_resources` | `FileSearchTool(vector_store_ids=[...])` in `PromptAgentDefinition.tools` |
| Connected agent via `connected_agent` tool type | `A2APreviewTool(project_connection_id=conn.id)` in orchestrator definition |
| `client.agents.upload_file_and_poll()` | `openai.vector_stores.files.upload_and_poll()` |
| No agent versioning | `create_version` / `list_versions` / `delete_version` |

### 3.3 Agent Registration Pattern (per agent)

```python
# agents/compute/agent.py — 2.0.x pattern
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, AzureAISearchTool
from azure.identity import DefaultAzureCredential

def create_compute_agent(project: AIProjectClient) -> AgentVersion:
    return project.agents.create_version(
        agent_name="aap-compute-agent",
        definition=PromptAgentDefinition(
            model=os.environ["AGENT_MODEL_DEPLOYMENT"],   # e.g. "gpt-4.1"
            instructions=COMPUTE_AGENT_SYSTEM_PROMPT,
            tools=[
                # Native Foundry tools (new in 2.0.x)
                FileSearchTool(vector_store_ids=[SOP_VECTOR_STORE_ID]),   # Phase 34
                AzureAISearchTool(azure_ai_search=AzureAISearchToolResource(
                    indexes=[AISearchIndexResource(
                        index_connection_id=RUNBOOK_SEARCH_CONNECTION_ID,
                        index_name="aap-runbooks"
                    )]
                )),                                                         # Phase 34
                # Custom tools injected as function_tool definitions
                # (actual execution happens in hosted agent container)
            ],
        )
    )
```

> **Note on hosted agents vs prompt agents:** Our 9 agents are *hosted agents* (Container Apps running Microsoft Agent Framework). The `create_version` call registers the agent definition with Foundry for portal visibility and versioning. The actual tool execution still runs in the Container App. Both are visible in Foundry: the definition in the portal builder, the runs via tracing.

### 3.4 A2A Topology — Orchestrator → Domain Agents

```python
# agents/orchestrator/agent.py — register A2A connections per domain agent
from azure.ai.projects.models import A2APreviewTool

def create_orchestrator_agent(project: AIProjectClient) -> AgentVersion:
    # Each domain agent is registered as an A2A connection in Foundry
    a2a_connections = {
        domain: project.connections.get(f"aap-{domain}-agent-connection")
        for domain in ["compute", "patch", "network", "security", "arc", "sre", "eol", "storage"]
    }
    
    return project.agents.create_version(
        agent_name="aap-orchestrator",
        definition=PromptAgentDefinition(
            model=os.environ["ORCHESTRATOR_MODEL_DEPLOYMENT"],
            instructions=ORCHESTRATOR_SYSTEM_PROMPT,
            tools=[
                A2APreviewTool(project_connection_id=conn.id)
                for conn in a2a_connections.values()
            ],
        )
    )
```

### 3.5 OTel Tracing Setup

```python
# agents/shared/telemetry.py — new shared module
import os
from azure.ai.projects import AIProjectClient
from azure.ai.projects.telemetry import AIProjectInstrumentor
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

os.environ["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] = "true"
os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"

def setup_foundry_tracing(project: AIProjectClient, agent_name: str) -> None:
    conn_str = project.telemetry.get_application_insights_connection_string()
    configure_azure_monitor(connection_string=conn_str)
    AIProjectInstrumentor().instrument()

def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
```

Custom span attributes for every incident run:
```python
with tracer.start_as_current_span("incident_run") as span:
    span.set_attribute("incident.id", incident_id)
    span.set_attribute("incident.domain", domain)
    span.set_attribute("incident.severity", severity)
    span.set_attribute("sop.title", sop_title)        # Phase 30
    span.set_attribute("sop.version", sop_version)    # Phase 30
    span.set_attribute("sop.is_generic", is_generic)  # Phase 30
```

### 3.6 Foundry Portal Visibility

After Phase 29, operators can:
- **Agents tab** → see all 9 agents with version history, instructions, and tool configurations
- **Tracing tab** → inspect every incident run's waterfall (tool calls, arguments, results, token usage)
- **Monitor tab** → per-agent dashboard: success rate, latency, token consumption over time
- **Playground** → test any agent version directly in the portal (prompt agents; hosted agents are invokable)

### 3.7 Terraform Changes

- New `azapi_resource` for each A2A connection (`Microsoft.CognitiveServices/accounts/projects/connections`, category `"RemoteA2A"`)
- App Insights connected to Foundry project via `azurerm_monitor_workspace` link
- New `SOP_VECTOR_STORE_ID` and `RUNBOOK_SEARCH_CONNECTION_ID` env vars (values populated in Phase 34)

---

## 4. Phase 30 — SOP Engine + Teams Notifications

### 4.1 Goal

Externalize all triage/remediation procedures from hardcoded Python strings into versioned Markdown files stored natively in **Foundry's managed vector store** (Basic setup — no separate storage account required). Agents semantically search and load the most relevant SOP via `FileSearchTool` before executing anything. Every SOP notification step dispatches to Teams and/or email. HITL approval is always required for remediation steps.

### 4.2 SOP Storage — Foundry Vector Store (Basic Setup)

SOPs are stored entirely within Foundry using the `openai.vector_stores` API via `project.get_openai_client()`. No Azure Storage Account is provisioned. Files live in Microsoft-managed storage, fully abstracted. Markdown (`.md`) is natively supported.

```python
# agents/shared/sop_store.py — provision SOP vector store in Foundry
from azure.ai.projects import AIProjectClient

async def provision_sop_vector_store(project: AIProjectClient, sop_files: list[Path]) -> str:
    """Upload all SOP markdown files to a Foundry-managed vector store."""
    openai = project.get_openai_client()

    # Create or reuse named vector store
    vs = openai.vector_stores.create(name="aap-sops-v1")

    for sop_path in sop_files:
        with open(sop_path, "rb") as f:
            openai.vector_stores.files.upload_and_poll(
                vector_store_id=vs.id,
                file=f,
                # filename used as the searchable file identifier
                filename=sop_path.name,   # e.g. "vm-high-cpu.md"
            )

    return vs.id   # stored as SOP_VECTOR_STORE_ID env var across all agents
```

**Foundry portal visibility:** Navigate to **Project → Files** to browse all uploaded SOP files. The vector store and its files are visible in the portal — no external storage to manage.

**SOP update pattern** (when an SOP is revised):
```python
# Delete old file, re-upload revised version — no DB migration needed
openai.vector_stores.files.delete(vector_store_id=vs_id, file_id=old_file_id)
openai.vector_stores.files.upload_and_poll(vector_store_id=vs_id, file=open("vm-high-cpu-v2.md","rb"))
```

**Limits (all well within range for SOP files):**
- Max file size: 512 MB (SOP markdown files are < 50 KB each)
- Max files per vector store: 10,000
- Max vector stores per agent: 1 (one shared `aap-sops-v1` store)
- Supported format: `.md` (text/markdown) ✅

**SOP file structure (logical naming convention in the vector store):**
```
_template.md                 ← authoring template
compute-generic.md
patch-generic.md
network-generic.md
security-generic.md
arc-generic.md
sre-generic.md
eol-generic.md
storage-generic.md
vm-high-cpu.md
vm-memory-pressure.md
vm-disk-exhaustion.md
vm-unavailable.md
vm-boot-failure.md
vm-network-unreachable.md
arc-vm-disconnected.md
arc-vm-extension-failure.md
arc-vm-patch-gap.md
vmss-scale-failure.md
vmss-unhealthy-instances.md
aks-node-not-ready.md
aks-pod-crashloop.md
aks-upgrade-required.md
patch-compliance-violation.md
patch-installation-failure.md
patch-critical-missing.md
eol-os-detected.md
eol-runtime-detected.md
security-defender-alert.md
security-rbac-anomaly.md
```

### 4.3 SOP Markdown Template (`_schema/sop-template.md`)

Every SOP file **must** follow this structure exactly. Agents parse the front matter for metadata and the body for procedure steps:

```markdown
---
title: "Human-readable SOP title"
version: "1.0"
domain: compute          # compute|patch|arc|eol|network|security|sre|storage
scenario_tags:           # used for semantic search matching
  - tag1
  - tag2
severity_threshold: P2   # P1|P2|P3|P4 — only load for incidents at this severity or higher
resource_types:          # ARM resource types this SOP applies to
  - Microsoft.Compute/virtualMachines
author: platform-team
last_updated: 2026-04-11
---

## Description
<!-- One paragraph explaining when this SOP applies and what it covers. -->

## Pre-conditions
<!-- Bullet list of conditions that must be true before this SOP is applicable. -->
- Resource type is X
- Alert rule is Y

## Triage Steps
<!-- Numbered steps the agent MUST attempt in order.
     Step types: [DIAGNOSTIC] | [NOTIFY] | [DECISION] | [ESCALATE]
     Agent may skip a step with justification logged in the trace. -->

1. **[DIAGNOSTIC]** Description of what to check and what tool to use.
   - *Expected signal:* What a healthy result looks like.
   - *Abnormal signal:* What triggers escalation or next step.

2. **[NOTIFY]** If <condition>: send notification via Teams + email with message template:
   > "Incident {incident_id}: {resource_name} — {alert_title}. Current state: {state}."
   - *Channels:* teams, email
   - *Severity:* warning|critical

3. **[DECISION]** Based on triage findings, determine root cause from:
   - Cause A: <description>
   - Cause B: <description>
   - Unknown: escalate

## Remediation Steps
<!-- IMPORTANT: Every REMEDIATION step REQUIRES human approval before execution.
     Risk levels: LOW | MEDIUM | HIGH | CRITICAL
     The agent proposes but NEVER executes without an approved ApprovalRecord. -->

4. **[REMEDIATION:MEDIUM]** If Cause A: description of proposed action.
   - *Reversibility:* reversible|irreversible
   - *Estimated impact:* description
   - *Approval message:* "Approve restarting {resource_name} to resolve {issue}?"

5. **[REMEDIATION:HIGH]** If Cause B: description of proposed action.
   - *Reversibility:* reversible
   - *Estimated impact:* description
   - *Approval message:* "Approve resizing {resource_name} from {current_sku} to {target_sku}?"

## Escalation
<!-- What happens when triage is inconclusive or remediation is rejected/fails. -->
- If triage inconclusive after all diagnostic steps: escalate to SRE agent
- If remediation rejected: create priority incident and notify on-call via Teams
- If remediation fails verification: trigger auto-rollback (WAL mechanism)

## Rollback
<!-- Auto-rollback conditions — these are handled by the existing WAL + RemediationExecutor. -->
- On DEGRADED verification: auto-rollback via existing WAL mechanism
- Manual rollback procedure: description

## References
- Runbook: "Runbook title in pgvector library"
- KB: https://learn.microsoft.com/...
- Related SOPs: sop-title-1.md, sop-title-2.md
```

### 4.4 SOP Index — PostgreSQL Metadata Table

The SOP *content* lives entirely in the Foundry vector store. PostgreSQL holds lightweight metadata only — for fast domain-scoped selection before the agent does a FileSearch:

```sql
CREATE TABLE sops (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              TEXT NOT NULL,
    domain             TEXT NOT NULL,
    scenario_tags      TEXT[],
    foundry_filename   TEXT NOT NULL UNIQUE,  -- e.g. "vm-high-cpu.md" (name in vector store)
    foundry_file_id    TEXT,                  -- openai file object ID; populated on upload
    content_hash       TEXT,                  -- SHA-256 of file content; used for idempotent upload
    version            TEXT NOT NULL DEFAULT '1.0',
    description        TEXT,
    severity_threshold TEXT DEFAULT 'P2',
    resource_types     TEXT[],
    is_generic         BOOLEAN DEFAULT FALSE,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON sops (domain, is_generic);
CREATE INDEX ON sops (foundry_filename);
```

No `embedding` column — the Foundry vector store handles chunking, embedding, and semantic search natively via `FileSearchTool`. No pgvector needed for SOPs.

### 4.5 SOP Loader — `agents/shared/sop_loader.py`

Selection uses the PostgreSQL metadata table to choose the right SOP filename, then the agent's `FileSearchTool` retrieves the content from the Foundry vector store:

```python
@dataclass
class SopLoadResult:
    title: str
    version: str
    foundry_filename: str   # e.g. "vm-high-cpu.md"
    is_generic: bool
    grounding_instruction: str  # injected into agent instructions

async def select_sop_for_incident(
    incident: IncidentMessage,
    domain: str,
    pg_conn: asyncpg.Connection,
) -> SopLoadResult:
    """
    Select the best SOP filename from the metadata table.
    The agent will retrieve full content via FileSearchTool at runtime.
    """
    # 1. Try to find scenario-specific SOP by domain + resource_type + tag overlap
    # Extract keywords from incident for tag matching
    incident_tags = _extract_incident_tags(incident)  # alert_title words + resource_type fragments
    row = await pg_conn.fetchrow(
        """SELECT foundry_filename, title, version, is_generic,
                  array_length(
                    ARRAY(SELECT unnest(scenario_tags) INTERSECT SELECT unnest($3::text[])),
                    1
                  ) AS tag_overlap
           FROM sops
           WHERE domain = $1
             AND is_generic = FALSE
             AND ($2 = ANY(resource_types) OR resource_types IS NULL)
           ORDER BY tag_overlap DESC NULLS LAST,
                    array_length(scenario_tags, 1) DESC NULLS LAST
           LIMIT 1""",
        domain, incident.get("resource_type", ""), incident_tags
    )

    if row is None:
        # Fall back to generic SOP for this domain
        row = await pg_conn.fetchrow(
            "SELECT foundry_filename, title, version, is_generic "
            "FROM sops WHERE domain = $1 AND is_generic = TRUE LIMIT 1",
            domain
        )

    filename = row["foundry_filename"]
    is_generic = row["is_generic"]
    title = row["title"]
    version = row["version"]

    # 2. Build grounding instruction — agent uses FileSearchTool to retrieve content
    grounding = f"""
## Active SOP: {title} (v{version})
{"[GENERIC FALLBACK — no scenario-specific SOP matched for this incident]" if is_generic else ""}

Use the `file_search` tool to retrieve the full SOP content for file: **{filename}**
Follow every step in that SOP as your primary guide for this incident.
Every [REMEDIATION] step REQUIRES human approval — never execute without an ApprovalRecord.
Every [NOTIFY] step REQUIRES calling the `sop_notify` tool.
Log any step you skip with explicit justification in your response.
"""

    return SopLoadResult(
        title=title,
        version=version,
        foundry_filename=filename,
        is_generic=is_generic,
        grounding_instruction=grounding,
    )
```

**How it works end-to-end:**
1. `select_sop_for_incident()` runs at request start — fast DB lookup, no blob fetch
2. `grounding_instruction` is injected into the Responses API call instructions
3. The agent's first action: call `file_search` for `{filename}` → Foundry returns the SOP content from the vector store
4. Agent follows the SOP steps, calling domain tools + `sop_notify` + `propose_*` as instructed
5. The `file_search` call appears as a named span in the Foundry portal trace waterfall — fully observable

### 4.6 Agent Grounding — Runtime Injection

Each agent's request handler selects the right SOP and injects a grounding instruction **before** invoking the Foundry run. The agent then uses its `FileSearchTool` to retrieve the full SOP content from the Foundry vector store:

```python
# agents/compute/main.py — grounding pattern
async def handle_incident(incident: IncidentMessage) -> AgentResponse:
    # 1. Select SOP from metadata table (fast DB lookup, no blob fetch)
    sop = await select_sop_for_incident(incident, domain="compute", pg_conn=pg_conn)

    # 2. Inject grounding instruction — agent fetches SOP content via FileSearchTool
    # ⚠️ P0 VALIDATION: test `additional_instructions` in dev before Phase 30 executes.
    # If the field is rejected for hosted agent references, fall back to:
    #   instructions_override = base_system_prompt + "\n\n" + sop.grounding_instruction
    # set at agent startup via SOP_GROUNDING_INSTRUCTIONS env var refreshed per-request.
    response = openai.responses.create(
        input=build_incident_message(incident),
        extra_body={
            "agent_reference": {"name": "aap-compute-agent", "type": "agent_reference"},
            "additional_instructions": sop.grounding_instruction,  # injected at run time
        }
    )
    # The agent's FIRST tool call will be file_search("{sop.foundry_filename}")
    # That span is fully visible in the Foundry portal trace waterfall
```

### 4.7 `sop_notify` Tool

New `@ai_function` added to **all agents**. Agents call this whenever a SOP step is marked `[NOTIFY]`:

```python
@ai_function
async def sop_notify(
    message: str,
    severity: Literal["info", "warning", "critical"],
    channels: list[Literal["teams", "email"]],   # pass ["teams","email"] for both; no "both" shorthand
    incident_id: str,
    resource_name: str,
    sop_step: str,       # e.g. "Step 2: Notify operator of CPU threshold breach"
) -> dict:
    """
    Send a notification as required by the active SOP.
    Call this whenever the SOP specifies a [NOTIFY] step.
    Always use this tool — never skip notification steps.
    Pass channels=["teams","email"] to notify on both channels simultaneously.
    """
    results = {}
    if "teams" in channels:
        results["teams"] = await _send_teams_notification(...)
    if "email" in channels:
        results["email"] = await _send_email_notification(...)
    return {"status": "sent", "channels": results, "sop_step": sop_step}
```

### 4.8 Teams Notification Expansion

The existing Teams bot supports only `alert`, `approval`, `outcome`, `reminder` card types. Phase 30 adds:

| New card type | Purpose |
|---------------|---------|
| `sop_notification` | General-purpose SOP NOTIFY step → operator awareness card (no action buttons) |
| `sop_escalation` | SOP ESCALATE step → escalation card with context + acknowledge button |
| `sop_summary` | Post-incident SOP execution summary → what steps ran, what was skipped, outcome |

New `NotifyRequest` card types in `services/teams-bot/src/types.ts`:
```typescript
type CardType = "alert" | "approval" | "outcome" | "reminder" 
              | "sop_notification" | "sop_escalation" | "sop_summary";  // new
```

Email notifications via **Azure Communication Services** (ACS Email):
- New env var: `ACS_CONNECTION_STRING`, `NOTIFICATION_EMAIL_FROM`, `NOTIFICATION_EMAIL_TO`
- New shared module: `services/api-gateway/email_notifier.py`
- Simple text+HTML template, no attachment

---

## 5. Phase 31 — SOP Library (Research + Content)

### 5.1 Goal

Generate ≥30 production-quality SOP markdown files covering all domains. Each SOP is:
- Researched against real Azure documentation and operational best practices
- Templated per the `_schema/sop-template.md` schema from Phase 30
- Validated for schema compliance (front matter parsing, step type labels, HITL markers)
- Indexed into the `sops` PostgreSQL table via a migration script

### 5.2 SOP Coverage Plan

| Domain | Count | Key SOPs |
|--------|-------|---------|
| **VM (Azure)** | 7 | high-cpu, memory-pressure, disk-exhaustion, vm-unavailable, boot-failure, network-unreachable, generic |
| **Arc VM** | 4 | disconnected, extension-failure, patch-gap, generic |
| **VMSS** | 3 | scale-failure, unhealthy-instances, generic |
| **AKS** | 4 | node-not-ready, pod-crashloop, upgrade-required, generic |
| **Patch** | 4 | compliance-violation, install-failure, critical-missing, generic |
| **EOL** | 3 | os-detected, runtime-detected, generic |
| **Network** | 3 | nsg-blocking, connectivity-failure, generic |
| **Security** | 3 | defender-alert, rbac-anomaly, generic |
| **SRE** | 3 | slo-breach, availability-degraded, generic |
| **Total** | **34** | |

### 5.3 SOP Upload + Registration

New script: `scripts/upload_sops.py` — runs once after Phase 31 content is authored, and again whenever SOPs are updated:

```python
# scripts/upload_sops.py — idempotent SOP upload
# Idempotency mechanism: SHA-256 content hash stored in PostgreSQL sops.content_hash
# Skip upload if file hash matches stored hash; replace if hash differs.
#
# 1. For each .md file in sops/:
#    a. Compute SHA-256 hash of file content
#    b. Look up existing row in PostgreSQL sops table by foundry_filename
#    c. If row exists AND content_hash matches → skip (no change)
#    d. If row exists AND hash differs → delete old foundry file, re-upload, update row
#    e. If no row → upload to Foundry vector store (aap-sops-v1), insert row
# 2. openai.vector_stores.files.upload_and_poll(vector_store_id, file)
# 3. Parse YAML front matter → upsert PostgreSQL sops row
#    (foundry_filename, foundry_file_id, content_hash, title, domain, scenario_tags, ...)
```

No pgvector embeddings needed — the Foundry vector store handles all semantic indexing. The PostgreSQL `sops` table is a lightweight metadata registry only (domain, tags, filename → Foundry file ID + content hash for idempotency).

---

## 6. Phase 32 — VM Domain Depth

### 6.1 Goal

Bring the VM domain (Azure VM, Arc VM, VMSS, AKS) and the Patch/EOL agents to world-class depth. Fix all triage chain stubs. Add HITL remediation tools for every resource type.

### 6.2 Stub Fixes (Patch + EOL agents)

| Agent | Stub | Fix |
|-------|------|-----|
| Patch | `query_activity_log` | Real SDK: `MonitorManagementClient.activity_logs.list()` — mirrors Compute agent implementation |
| Patch | `query_resource_health` | Real SDK: `MicrosoftResourceHealth.availability_statuses.get_by_resource()` — mirrors Compute |
| EOL | `query_activity_log` | Same fix as Patch |
| EOL | `query_resource_health` | Same fix as Patch |
| EOL | `query_software_inventory` | Activate the KQL already written in comments — `ConfigurationData` table query for Python/Node/.NET/DB runtimes |

### 6.3 New Compute Agent Tools

**Azure VM tools:**

| Tool | Description | SDK |
|------|-------------|-----|
| `query_vm_extensions` | List extensions on a VM, health state, provisioning status | `ComputeManagementClient.virtual_machine_extensions.list()` |
| `query_boot_diagnostics` | Retrieve boot diagnostics screenshot URI and serial log | `ComputeManagementClient.virtual_machines.retrieve_boot_diagnostics_data()` |
| `query_vm_sku_options` | List available VM SKUs in the same region/family for rightsizing | `ComputeManagementClient.resource_skus.list()` — diagnostic read only |
| `propose_vm_restart` | Create HITL ApprovalRecord for VM restart | `approval_manager.create_approval_record()` — no ARM call |
| `propose_vm_resize` | Create HITL ApprovalRecord for VM resize; accepts `target_sku` resolved by agent after calling `query_vm_sku_options` | `approval_manager.create_approval_record()` — no ARM call |
| `propose_vm_redeploy` | Create HITL ApprovalRecord for VM redeploy (host-level issue) | `approval_manager.create_approval_record()` — no ARM call |
| `query_disk_health` | Disk IOPS/throughput metrics, disk state, encryption status | `ComputeManagementClient.disks.get()` + Monitor metrics |

> **HITL rule:** All `propose_*` tools call only `approval_manager.create_approval_record()`. No ARM mutations. SKU lookup for resize is a separate diagnostic tool (`query_vm_sku_options`) called before `propose_vm_resize`.

**VMSS tools:**

| Tool | Description | SDK |
|------|-------------|-----|
| `query_vmss_instances` | List instances with health state, power state, provisioning | `ComputeManagementClient.virtual_machine_scale_set_vms.list()` |
| `query_vmss_autoscale` | Current autoscale settings, recent scale events | `MonitorManagementClient.autoscale_settings.list_by_resource_group()` |
| `query_vmss_rolling_upgrade` | Upgrade policy, in-progress/failed instance upgrades | `ComputeManagementClient.virtual_machine_scale_set_rolling_upgrades.get_latest()` |
| `propose_vmss_scale` | HITL ApprovalRecord for manual scale-out/in | `approval_manager.create_approval_record()` |

**AKS tools:**

| Tool | Description | SDK |
|------|-------------|-----|
| `query_aks_cluster_health` | API server status, provisioning state, Kubernetes version | `ContainerServiceClient.managed_clusters.get()` |
| `query_aks_node_pools` | Node pool health, count, VM size, resource pressure | `ContainerServiceClient.agent_pools.list()` |
| `query_aks_diagnostics` | AKS control plane logs from Log Analytics (kube-apiserver, kube-scheduler errors) | `LogsQueryClient.query_workspace()` with AKS KQL |
| `query_aks_upgrade_profile` | Available Kubernetes upgrades, deprecated APIs | `ContainerServiceClient.managed_clusters.get_upgrade_profile()` |
| `propose_aks_node_pool_scale` | HITL ApprovalRecord for node pool scale | `approval_manager.create_approval_record()` |

### 6.4 Arc Agent Enhancements

| Tool | Description | SDK |
|------|-------------|-----|
| `query_arc_extension_health` | List Arc extensions, provisioning state, error details | `azure-mgmt-hybridcompute` → `HybridComputeManagementClient.machine_extensions.list()` |
| `query_arc_guest_config` | Guest configuration assignments and compliance state | `azure-mgmt-guestconfiguration` → `GuestConfigurationClient.guest_configuration_assignment_reports.list()` |
| `query_arc_connectivity` | Agent connectivity status, last heartbeat, disconnect reason | `HybridComputeManagementClient.machines.get()` → `properties.agentConfiguration` |
| `propose_arc_assessment` | HITL ApprovalRecord for triggering a new patch assessment on Arc VM | `approval_manager.create_approval_record()` |

### 6.5 HITL Remediation Architecture (all new tools)

All `propose_*` tools follow the **write-then-return** pattern established in `approval_manager.py`:
1. Build `RemediationProposal` with `requires_approval=True`, `risk_level`, `reversibility`
2. Call `create_approval_record(cosmos_container, proposal, thread_id, incident_id)`
3. Cosmos record created with `status="pending"`, `expires_at=+30min`
4. Teams approval card sent via `teams_notifier.post_approval_card()`
5. Agent returns immediately — thread goes idle, waits for approval webhook
6. On approval: existing `approvals.py` `_resume_foundry_thread()` re-activates run
7. `RemediationExecutor` performs pre-flight checks + WAL write + ARM call

No new `SAFE_ARM_ACTIONS` are executed without going through this full chain.

---

## 7. Phase 33 — Foundry Evaluation + Quality Gates

### 7.1 Goal

Instrument every agent with `azure-ai-evaluation` agentic evaluators. Run continuous evaluation in CI. Set alert thresholds on agent quality metrics visible in the Foundry portal.

### 7.2 Agentic Evaluators

```python
# services/api-gateway/evaluation/agent_evaluators.py
from azure.ai.evaluation import (
    TaskAdherenceEvaluator,      # Did agent complete the assigned task?
    ToolCallAccuracyEvaluator,   # Were tool calls correct and well-formed?
    IntentResolutionEvaluator,   # Did agent correctly resolve the user/incident intent?
    GroundednessEvaluator,       # Are diagnoses grounded in evidence from tools?
    ContentSafetyEvaluator,      # No harmful content in agent responses
    IndirectAttackEvaluator,     # XPIA — prompt injection via tool results
)
```

**AIOps-specific custom evaluators:**

| Evaluator | What it measures |
|-----------|-----------------|
| `SopAdherenceEvaluator` | Did the agent follow the loaded SOP steps in order? Checks span sequence against SOP step list. |
| `DiagnosisGroundingEvaluator` | Is the agent's root-cause diagnosis supported by at least 2 evidence signals from tool calls? |
| `RemediationSafetyEvaluator` | Did the agent correctly gate every REMEDIATION step behind an ApprovalRecord? No direct ARM calls. |
| `TriageCompletenessEvaluator` | Were TRIAGE-002 (resource health) and TRIAGE-003 (activity log) both called before diagnosis? |

### 7.3 Continuous Evaluation Pipeline

```python
# .github/workflows/agent-eval.yml trigger: weekly + on PR to main
from azure.ai.evaluation import evaluate

result = evaluate(
    data="tests/eval/agent_traces_sample.jsonl",   # sampled from App Insights
    evaluators={
        "task_adherence": TaskAdherenceEvaluator(model_config),
        "tool_accuracy": ToolCallAccuracyEvaluator(model_config),
        "sop_adherence": SopAdherenceEvaluator(model_config),
        "triage_completeness": TriageCompletenessEvaluator(model_config),
        "content_safety": ContentSafetyEvaluator(credential=cred, azure_ai_project=proj),
        "indirect_attack": IndirectAttackEvaluator(credential=cred, azure_ai_project=proj),
    },
    azure_ai_project=azure_ai_project,   # results logged to Foundry portal
    output_path="./eval-results.json"
)

# CI gate: fail if any metric drops below threshold
# Note: azure-ai-evaluation SDK returns metrics with evaluator-name prefix,
# e.g. "task_adherence.task_adherence" or "task_adherence.score" depending on version.
# Use .get() with explicit error to catch key mismatches on first run.
ta_score = result.get("metrics", {}).get("task_adherence.task_adherence") \
           or result.get("metrics", {}).get("task_adherence.score") \
           or result["metrics"]["task_adherence"]  # fallback for flat key
tc_score = result.get("metrics", {}).get("triage_completeness.triage_completeness") \
           or result["metrics"]["triage_completeness"]
assert ta_score >= 4.0, f"TaskAdherence {ta_score} below threshold 4.0"
assert tc_score >= 0.95, f"TriageCompleteness {tc_score} below threshold 0.95"
```

### 7.4 Foundry Portal — Continuous Evaluation Rules

In the Foundry portal (Evaluate → Continuous evaluation):
- Sample rate: 10% of production runs
- Evaluators: `TaskAdherence`, `ToolCallAccuracy`, `ContentSafety`
- Alert threshold: `TaskAdherence < 3.5` → alert via App Insights metric alert → Teams notification

---

## 8. Phase 34 — FileSearch Knowledge + Azure AI Search RAG

### 8.1 Goal

Replace the current pgvector-only runbook RAG with Azure AI Search (portal-native). Attach SOP files as a `FileSearchTool` vector store on every agent definition. Operators can manage knowledge sources directly in the Foundry portal.

### 8.2 FileSearch Vector Store — SOPs (Phase 30 provisioned, Phase 34 attaches)

The Foundry vector store `aap-sops-v1` is **provisioned in Phase 30** via `agents/shared/sop_store.py` and `scripts/upload_sops.py`. Phase 34 attaches it to every agent definition via `FileSearchTool`:

```python
# agents/compute/agent.py — attach SOP vector store (Phase 34 addition)
from azure.ai.projects.models import FileSearchTool

def create_compute_agent(project: AIProjectClient) -> AgentVersion:
    return project.agents.create_version(
        agent_name="aap-compute-agent",
        definition=PromptAgentDefinition(
            model=os.environ["AGENT_MODEL_DEPLOYMENT"],
            instructions=COMPUTE_AGENT_SYSTEM_PROMPT,
            tools=[
                FileSearchTool(vector_store_ids=[os.environ["SOP_VECTOR_STORE_ID"]]),
                AzureAISearchTool(...),   # runbook RAG — Phase 34
            ],
        )
    )
```

`SOP_VECTOR_STORE_ID` is the `vs.id` written to the environment by `scripts/upload_sops.py` and set on all Container Apps. No blob storage, no re-upload in Phase 34 — the vector store already exists. Agents can now use `file_search` to retrieve any SOP by filename, visible as named spans in the Foundry portal trace waterfall.

### 8.3 Azure AI Search — Runbook RAG Migration

```python
# Migration: index existing pgvector runbooks into Azure AI Search
# scripts/migrate_runbooks_to_ai_search.py

from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchableField,
    VectorSearch, HnswAlgorithmConfiguration, VectorSearchProfile,
    SearchField, SearchFieldDataType
)

index_schema = SearchIndex(
    name="aap-runbooks",
    fields=[
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="domain", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="version", type=SearchFieldDataType.String),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            vector_search_dimensions=1536,
            vector_search_profile_name="hnsw-profile"
        ),
    ],
    vector_search=VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")]
    )
)
```

Portal visibility: the `AzureAISearchTool` on each agent definition shows the runbook index as a named knowledge source in the Foundry portal.

---

## 9. Infrastructure Changes Summary (All Phases)

| Resource | Phase | Terraform provider / mechanism |
|----------|-------|-------------------------------|
| Foundry vector store `aap-sops-v1` (SOP files) | 30 | Created via `scripts/upload_sops.py` (SDK: `openai.vector_stores.create`) — **no Terraform, Foundry-managed** |
| `SOP_VECTOR_STORE_ID` env var on all Container Apps | 30 | `azurerm_container_app` env var update |
| ACS Email Communication Services | 30 | `azurerm_email_communication_service` |
| App Insights connected to Foundry project | 29 | `azurerm_application_insights` + `azapi` link to Foundry project |
| A2A connections (8 domain agents) | 29 | `azapi_resource` (category `RemoteA2A`) |
| `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` env var on all agents | 29 | `azurerm_container_app` env var update |
| Azure AI Search service (`aap-search-prod`) | 34 | `azurerm_search_service` |
| AI Search connection in Foundry project | 34 | `azapi_resource` (AzureAISearch) |
| Runbook index (`aap-runbooks`) | 34 | Created via `scripts/migrate_runbooks_to_ai_search.py` |

> **No new storage account is required for SOPs.** The Foundry vector store (Basic setup) uses Microsoft-managed storage — fully abstracted, visible in the Foundry portal under Project → Files.

---

## 10. Testing Strategy

Each phase follows the existing TDD workflow. Key test additions:

| Phase | New tests |
|-------|-----------|
| 29 | Agent registration smoke tests (create_version roundtrip), OTel span attribute assertions, A2A connection verification |
| 30 | SOP selector unit tests (domain match, generic fallback, no-match fallback), `sop_notify` tool unit tests (Teams + email mock), SOP template schema validation (front matter parse) |
| 31 | SOP file lint (front matter YAML parse, required sections present, step type labels valid), upload script idempotency test (upload same file twice → no duplicate) |
| 32 | Real SDK tool tests (3-path: success/error/SDK-missing) for all 15+ new tools, HITL proposal chain integration test |
| 33 | Evaluator smoke tests (single-row pass), CI gate threshold assertions, custom evaluator unit tests |
| 34 | FileSearch roundtrip (upload → query → retrieve), AI Search index tests, agent definition tool attachment assertions |

---

## 11. Phase Dependencies

```
Phase 29 (Foundry Migration)
    ↓
Phase 30 (SOP Engine)      ← requires 29 (Foundry agent patterns, OTel spans, vector store provisioned)
    ↓
Phase 31 (SOP Library)     ← requires 30 (template schema, vector store exists, PostgreSQL sops table)
    ↓
Phase 32 (VM Depth)        ← requires 30 (sop_notify + propose_* tools), can overlap with 31
    ↓
Phase 33 (Evaluation)      ← requires 29 (OTel traces as eval input), 30 (SopAdherenceEvaluator needs SOP data)
    ↓
Phase 34 (AI Search RAG)   ← requires 29 (agent definitions for tool attachment)
```

---

## 12. Open Questions / Decisions Deferred

1. **`additional_instructions` in Responses API for hosted agents** — needs validation in dev environment. If `extra_body.additional_instructions` is not supported for hosted agent references, fallback is to set `SOP_GROUNDING_INSTRUCTIONS` as an env var that each agent appends to its base system prompt at startup, refreshed per-request via a lightweight middleware pattern.
2. **A2A vs in-process `connected_agent`** — A2A is the portal-visible pattern but adds a network hop through Foundry service. Decision: use A2A for orchestrator→domain agent calls (enables portal topology visibility), keep in-process `connected_agent` handoffs for sub-agent calls within a single domain Container App.
3. **Vector store refresh on SOP update** — the `scripts/upload_sops.py` script is the update mechanism. For automated refresh when an operator edits a SOP file (e.g. via git commit), wire a GitHub Actions workflow trigger: `on: push` to `sops/**/*.md` → run `upload_sops.py`. No blob triggers or Azure Functions needed.
4. **Email provider** — Azure Communication Services Email vs. SendGrid. ACS is fully Azure-native with managed identity auth; SendGrid requires API key management. Recommendation: ACS (`azurerm_email_communication_service`).
5. **VMSS/AKS agents** — remain as tools on the Compute agent for now. Extract to dedicated agents (Phase 35+) only if the Compute agent's tool count exceeds 12 or routing accuracy degrades.
