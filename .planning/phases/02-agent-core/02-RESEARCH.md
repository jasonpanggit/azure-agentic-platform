# Phase 2: Agent Core - Research

**Date:** 2026-03-26
**Status:** Complete
**Purpose:** Everything needed to plan Phase 2 well

---

## Table of Contents

1. [Phase 2 Scope Summary](#1-phase-2-scope-summary)
2. [Microsoft Agent Framework 1.0.0rc5](#2-microsoft-agent-framework-100rc5)
3. [Foundry Hosted Agent Deployment](#3-foundry-hosted-agent-deployment)
4. [Azure MCP Server Integration](#4-azure-mcp-server-integration)
5. [Agent Identity & RBAC (Terraform)](#5-agent-identity--rbac-terraform)
6. [API Gateway & Incident Endpoint](#6-api-gateway--incident-endpoint)
7. [Session Budget Tracking](#7-session-budget-tracking)
8. [OpenTelemetry Instrumentation](#8-opentelemetry-instrumentation)
9. [Shared Base Docker Image](#9-shared-base-docker-image)
10. [CI/CD Pipeline Extensions](#10-cicd-pipeline-extensions)
11. [Phase 1 Integration Points](#11-phase-1-integration-points)
12. [Ordering Constraints & Dependencies](#12-ordering-constraints--dependencies)
13. [Risk Register](#13-risk-register)
14. [Open Questions for Planning](#14-open-questions-for-planning)

---

## 1. Phase 2 Scope Summary

Phase 2 delivers the **agent runtime layer** — no UI, no Arc-specific capabilities (Phase 3), no runbook RAG (Phase 5). The scope is:

| Deliverable | Requirements |
|---|---|
| **7 agent spec documents** (design-first gate) | AGENT-009 |
| **Orchestrator + 6 domain agents** deployed as Foundry Hosted Agents on Container Apps | AGENT-001, AGENT-002, AGENT-003, AGENT-004, AGENT-008 |
| **API gateway** (`POST /api/v1/incidents`) as a standalone FastAPI Container App | DETECT-004 |
| **Agent identities** (7 system-assigned managed identities) via Terraform | INFRA-005, INFRA-006 |
| **Session budget tracking** in Cosmos DB | AGENT-007 |
| **OpenTelemetry instrumentation** to App Insights + Fabric OneLake | MONITOR-007, AUDIT-001, AUDIT-005 |
| **Monitoring capabilities** (metrics, logs, KQL, resource health) via MCP tools | MONITOR-001, MONITOR-002, MONITOR-003 |
| **Triage workflow** (classify, diagnose, evidence, confidence score) | TRIAGE-001, TRIAGE-002, TRIAGE-003, TRIAGE-004 |
| **Remediation safety** (propose-only, no execution without approval) | REMEDI-001 |

**Total: 21 requirements across 7 categories.**

### Non-Negotiable Ordering Constraint

> **AGENT-009 design-first gate:** All 7 `docs/agents/{name}-agent.spec.md` files must be committed and PR-approved **before any agent `.py` implementation code is written**. CI lint gate enforces this.

---

## 2. Microsoft Agent Framework 1.0.0rc5

### 2.1 Package Details

| Attribute | Value |
|---|---|
| **Package** | `agent-framework` |
| **Install** | `pip install agent-framework --pre` |
| **Version** | `1.0.0rc5` (2026-03-20) |
| **Status** | Pre-release RC -- pin version exactly |
| **Python** | >= 3.10 |

### 2.2 Key APIs for Phase 2

**`HandoffOrchestrator`** -- the central orchestration class that classifies incoming messages and routes to domain `AgentTarget` instances. This is the backbone of AGENT-001.

```python
from agent_framework import HandoffOrchestrator, AgentTarget

orchestrator = HandoffOrchestrator(
    name="aiops-orchestrator",
    client=azure_ai_client,          # AzureAIAgentClient from azure-ai-projects
    instructions=ORCHESTRATOR_PROMPT,
)

# Register each domain agent as a handoff target
orchestrator.add_target(AgentTarget(
    name="compute-agent",
    agent_id=foundry_agent_id,       # Foundry Hosted Agent registration ID
    description="Handle compute incidents: VMs, VMSS, AKS node issues",
))
```

**`ChatAgent`** -- primary agent class for conversational agents. Wraps `AzureAIAgentClient`. Each domain agent is a `ChatAgent`.

**`@ai_function`** -- decorator that exposes a Python function as an LLM-callable tool. Replaces manual JSON schema definition. This is how we wire MCP tool wrappers and custom tools.

```python
from agent_framework import ai_function

@ai_function
def query_log_analytics(workspace_id: str, kql_query: str, timespan: str = "PT2H") -> dict:
    """Query a Log Analytics workspace with KQL."""
    # Implementation uses Azure MCP Server or direct SDK
    ...
```

**`AzureAIAgentClient`** -- Foundry backend client. Uses `project_endpoint` + `DefaultAzureCredential`. Constructed from `azure-ai-projects` SDK.

### 2.3 Orchestration Pattern for AAP

The `HandoffOrchestrator` pattern maps directly to AGENT-001:

1. Incoming incident arrives at Orchestrator via Foundry thread
2. Orchestrator classifies by `domain` field (or LLM classification if domain is ambiguous)
3. Orchestrator hands off to the correct domain `AgentTarget`
4. Domain agent performs triage (TRIAGE-002, TRIAGE-003, TRIAGE-004)
5. Domain agent can return `needs_cross_domain: true` to trigger re-routing
6. Domain agent hands back to Orchestrator with diagnosis

### 2.4 Cross-Domain Re-Routing

When a domain agent discovers the root cause spans multiple domains:

```python
from agent_framework import HandoffAction

# Inside ComputeAgent: discovered network root cause
return HandoffAction(
    target=AgentTarget(name="network-agent", agent_id=NETWORK_AGENT_ID),
    message=json.dumps({
        "message_type": "handoff_request",
        "needs_cross_domain": True,
        "original_domain": "compute",
        "suspected_domain": "network",
        "evidence": "NIC disconnected events in activity log",
    })
)
```

### 2.5 Version Pinning Strategy

Given RC status with breaking changes likely:

```
# requirements-base.txt
agent-framework==1.0.0rc5      # PINNED -- do not upgrade without testing
azure-ai-projects==2.0.1       # GA, stable
azure-ai-agentserver-agentframework  # Required for Foundry Hosted Agent adapter
azure-ai-agentserver-core      # Core adapter (all agents)
```

### 2.6 What to Watch For

- **Breaking changes** between RC versions -- pin exactly, don't use `>=`
- **`HandoffOrchestrator.add_target()` API** may change parameter names
- **`@ai_function` decorator** may have schema generation differences vs `@tool`
- **Thread management** -- verify how `HandoffOrchestrator` manages Foundry threads vs creating new ones per handoff

---

## 3. Foundry Hosted Agent Deployment

### 3.1 Deployment Architecture

Each domain agent is deployed as a **Foundry Hosted Agent** running on Azure Container Apps. The Foundry runtime translates between the Foundry Responses API and the agent framework's native format.

```
Foundry Responses API (external callers)
    |
    v
azure-ai-agentserver-core (protocol translation)
    |
    v
azure-ai-agentserver-agentframework (agent framework adapter)
    |
    v
ChatAgent / HandoffOrchestrator (agent logic)
    |
    v
MCP tools + @ai_function tools
```

### 3.2 Container Entry Point

Each agent container needs a specific entry point that the Foundry runtime calls:

```python
# agents/compute/agent.py (entry point)
import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from agent_framework import ChatAgent

credential = DefaultAzureCredential()

project_client = AIProjectClient(
    subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
    resource_group_name=os.environ["AZURE_RESOURCE_GROUP"],
    project_name=os.environ["FOUNDRY_PROJECT_NAME"],
    credential=credential,
)

# Create or retrieve agent definition in Foundry
compute_agent = project_client.agents.create_or_update(
    agent_id=os.environ.get("FOUNDRY_AGENT_ID"),
    model=os.environ["FOUNDRY_MODEL_DEPLOYMENT"],
    name="aiops-compute-agent",
    instructions=open("prompts/system.md").read(),
    tools=get_compute_tools(),
    tool_resources=get_mcp_resources(),
    metadata={"domain": "compute", "version": "1.0.0"},
)
```

### 3.3 Required Packages per Agent Container

```
azure-ai-agentserver-core           # Core adapter (all agents)
azure-ai-agentserver-agentframework # Microsoft Agent Framework adapter
```

### 3.4 Local Testing Before Containerization

Agents can be tested locally via:

```bash
POST localhost:8088/responses
```

The `agentserver` adapter exposes a local HTTP server that mimics the Foundry Responses API. This enables rapid iteration before pushing to ACR.

### 3.5 Build Requirements

- Build with `--platform linux/amd64` (Hosted Agents run on Linux AMD64 only)
- Push to Azure Container Registry (ACR)
- Grant project managed identity `Container Registry Repository Reader` role on ACR

### 3.6 Key Consideration: Preview Limitations

> **Foundry Hosted Agents are Preview -- no private networking.** Container Apps fill this gap for VNet-isolated services. Do not put Hosted Agents behind a private endpoint until GA.

This means agent containers are accessible within the Container Apps environment but Foundry's managed networking layer doesn't support private endpoints yet. The Container App's internal ingress provides network isolation within the VNet.

---

## 4. Azure MCP Server Integration

### 4.1 Overview

Azure MCP Server (`@azure/mcp`) is GA and provides tool access to Azure resources. It is the **primary tool surface** for all non-Arc domain agents (AGENT-004).

### 4.2 Covered Services (Relevant to Phase 2)

| Domain Agent | Azure MCP Tools |
|---|---|
| **Compute** | `compute` (VMs, VMSS, disks), `aks` (list), `appservice`, `functionapp` |
| **Network** | Via `appservice`, `signalr`; limited direct networking tools |
| **Storage** | `storage`, `fileshares`, `storagesync` |
| **Security** | `keyvault`, `role` (RBAC) |
| **SRE** | `monitor` (Log Analytics queries + metrics), `applicationinsights`, `advisor`, `resourcehealth` |
| **All agents** | `monitor` (cross-cutting for TRIAGE-002, TRIAGE-003) |

### 4.3 Arc Coverage Gap (Confirmed)

The Azure MCP Server does **NOT** cover:
- Arc-enabled servers (`Microsoft.HybridCompute/machines`)
- Arc-enabled Kubernetes (`Microsoft.Kubernetes/connectedClusters`)
- Arc-enabled data services

This is why the Arc Agent in Phase 2 is a **stub only**. Real Arc tools come in Phase 3 via the custom Arc MCP Server.

### 4.4 Mounting in a Foundry Hosted Agent

MCP tools are registered as tool resources when creating/updating the agent definition in Foundry:

```python
from azure.ai.projects.models import McpTool

azure_mcp_tool = McpTool(
    server_label="azure-mcp",
    server_url="npx @azure/mcp@latest",   # or sidecar URL
    allowed_tools=[
        "compute.list_vms",
        "compute.get_vm",
        "monitor.query_logs",
        "monitor.query_metrics",
        "resourcehealth.get_availability_status",
        "advisor.list_recommendations",
    ],
)
```

### 4.5 Tool Invocation Pattern

The agent framework handles MCP tool invocation transparently:

1. Agent LLM decides to call a tool (e.g., `monitor.query_logs`)
2. Framework routes the call to the registered MCP server
3. MCP server authenticates to Azure via managed identity (`DefaultAzureCredential`)
4. Response is returned to the agent as structured data
5. Agent continues reasoning with the tool result

### 4.6 Auth via Managed Identity

Azure MCP Server uses `DefaultAzureCredential` / managed identity for authentication. Since each agent has its own system-assigned managed identity (INFRA-005), the MCP server inherits the agent's RBAC scope. This ensures:

- Compute Agent's MCP calls are scoped to compute subscriptions
- Security Agent's MCP calls are scoped to security-relevant resources
- No cross-domain RBAC leakage

### 4.7 Wildcard Tool Access Prevention

Per the GBB anti-pattern research (SUMMARY.md Section 3): **explicit `allowed_tools` lists are required**. No wildcard access. CI lint rule should flag any agent config that doesn't specify `allowed_tools`.

### 4.8 Network Tool Gap

The Azure MCP Server has limited direct networking tools (no dedicated VNet/NSG tools confirmed). The Network Agent may need to supplement with:

- `@ai_function` wrappers around `azure-mgmt-network` SDK calls
- Direct ARM API calls via the agent's managed identity
- `monitor` tools for network-related metrics and logs

This is a **planning risk** -- the Network Agent may have the most custom tool development.

---

## 5. Agent Identity & RBAC (Terraform)

### 5.1 Identity Architecture (INFRA-005)

7 system-assigned managed identities, one per Container App:

| Agent | Identity Name | Purpose |
|---|---|---|
| Orchestrator | `aiops-orchestrator` | Route incidents, no direct resource access |
| Compute | `aiops-compute-agent` | VM operations on compute subscription |
| Network | `aiops-network-agent` | Network operations on network subscription |
| Storage | `aiops-storage-agent` | Storage operations across subscriptions |
| Security | `aiops-security-agent` | Security read access across subscriptions |
| Arc | `aiops-arc-agent` | Arc resource operations (stub in Phase 2) |
| SRE | `aiops-sre-agent` | Read-only + monitoring across all subscriptions |

### 5.2 Terraform Implementation Pattern

Container Apps with system-assigned managed identity are created using `azurerm_container_app` (or `azapi_resource` for newer features). The identity is enabled in the `identity` block:

```hcl
resource "azurerm_container_app" "compute_agent" {
  name                         = "ca-compute-agent-${var.environment}"
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  template {
    container {
      name   = "compute-agent"
      image  = "${var.acr_login_server}/agents/compute:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "FOUNDRY_PROJECT_NAME"
        value = var.foundry_project_name
      }
      # ... additional env vars
    }
  }
}

output "compute_agent_principal_id" {
  value = azurerm_container_app.compute_agent.identity[0].principal_id
}
```

### 5.3 RBAC Assignments (INFRA-006)

Cross-subscription role assignments via `azurerm_role_assignment`:

```hcl
variable "role_assignments" {
  type = list(object({
    principal_id         = string
    role_definition_name = string
    scope                = string
  }))
}

resource "azurerm_role_assignment" "agent_rbac" {
  for_each             = {
    for ra in var.role_assignments :
    "${ra.principal_id}-${ra.role_definition_name}-${md5(ra.scope)}" => ra
  }
  principal_id         = each.value.principal_id
  role_definition_name = each.value.role_definition_name
  scope                = each.value.scope
}
```

### 5.4 RBAC Mapping (from D-14)

| Agent | Role | Scope |
|---|---|---|
| Orchestrator | `Reader` | Platform subscription |
| Compute | `Virtual Machine Contributor` | Compute subscription |
| Compute | `Monitoring Reader` | Platform + compute subscriptions |
| Network | `Network Contributor` | Network subscription |
| Network | `Reader` | Compute subscription |
| Storage | `Storage Blob Data Reader` | All storage subscriptions |
| Security | `Security Reader` | All subscriptions |
| SRE | `Reader` | All subscriptions |
| SRE | `Monitoring Reader` | All subscriptions |
| Arc | `Azure Arc ScVmm VM Contributor` (or equivalent) | Arc resource groups |

### 5.5 Entra Agent ID Provisioning

Per D-17, Entra Agent IDs are provisioned via `azapi` for the Preview API. The key is to **output the Entra Agent ID object IDs** from Terraform so Phase 7 Agent 365 integration can reference them.

```hcl
# Entra Agent ID objects may be auto-created by Container Apps
# system-assigned identity. The principal_id output IS the Entra object.
# Agent 365 (GA May 1, 2026) auto-discovers these identities.

output "agent_entra_ids" {
  description = "Map of agent name to Entra object ID (principal_id)"
  value = {
    orchestrator = azurerm_container_app.orchestrator.identity[0].principal_id
    compute      = azurerm_container_app.compute_agent.identity[0].principal_id
    network      = azurerm_container_app.network_agent.identity[0].principal_id
    storage      = azurerm_container_app.storage_agent.identity[0].principal_id
    security     = azurerm_container_app.security_agent.identity[0].principal_id
    arc          = azurerm_container_app.arc_agent.identity[0].principal_id
    sre          = azurerm_container_app.sre_agent.identity[0].principal_id
  }
}
```

### 5.6 Module Structure

Two new Terraform modules for Phase 2:

1. **`terraform/modules/agent-apps/`** -- Container App definitions for 7 agents + 1 API gateway (8 Container Apps total). Outputs `principal_id` per agent.
2. **`terraform/modules/rbac/`** -- Cross-subscription role assignments. Consumes `principal_id` outputs from `agent-apps`.

These extend the existing `envs/dev/main.tf` module composition pattern established in Phase 1.

---

## 6. API Gateway & Incident Endpoint

### 6.1 Architecture (DETECT-004, D-09 through D-12)

A standalone FastAPI service at `services/api-gateway/`:

```
services/api-gateway/
  app/
    __init__.py
    main.py              # FastAPI app
    routes/
      __init__.py
      incidents.py       # POST /api/v1/incidents
      health.py          # GET /health
    middleware/
      __init__.py
      auth.py            # Entra Bearer token validation
      correlation.py     # Correlation ID propagation
      logging.py         # Request/response logging
    models/
      __init__.py
      incident.py        # Pydantic incident payload model
    services/
      __init__.py
      foundry.py         # Foundry thread creation + dispatch
  Dockerfile
  requirements.txt
```

### 6.2 Incident Payload Schema (DETECT-004)

```python
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class AffectedResource(BaseModel):
    resource_id: str
    subscription_id: str
    resource_type: str

class IncidentPayload(BaseModel):
    incident_id: str
    severity: str = Field(pattern="^Sev[1-4]$")
    domain: str = Field(pattern="^(compute|network|storage|security|arc|sre)$")
    affected_resources: list[AffectedResource]
    detection_rule: str
    kql_evidence: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
```

### 6.3 Entra ID Token Validation (D-10)

Recommended approach: **`fastapi-azure-auth`** library for production-grade Entra token validation.

```python
from fastapi import FastAPI, Depends
from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

app = FastAPI()

azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
    app_client_id=os.environ["API_CLIENT_ID"],
    tenant_id=os.environ["AZURE_TENANT_ID"],
    scopes={
        f"api://{os.environ['API_CLIENT_ID']}/incidents.write": "Write incidents"
    },
)

@app.post("/api/v1/incidents")
async def create_incident(
    payload: IncidentPayload,
    user=Depends(azure_scheme)
):
    # Create Foundry thread and dispatch to Orchestrator
    ...
```

**Alternative:** Manual JWT validation with `PyJWT` + JWKS fetching for more control (lighter dependency). The manual approach:

1. Fetch JWKS keys from `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys`
2. Decode JWT header to find `kid`
3. Validate signature, audience (`aud`), issuer (`iss`), expiration (`exp`)
4. Cache JWKS keys with TTL

### 6.4 Foundry Thread Creation

The gateway creates a Foundry thread and dispatches to the Orchestrator:

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

async def dispatch_incident(payload: IncidentPayload) -> dict:
    credential = DefaultAzureCredential()
    client = AIProjectClient(
        subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
        resource_group_name=os.environ["AZURE_RESOURCE_GROUP"],
        project_name=os.environ["FOUNDRY_PROJECT_NAME"],
        credential=credential,
    )

    # Create thread
    thread = client.agents.create_thread()

    # Add incident as first message (typed envelope per AGENT-002)
    message = {
        "message_type": "incident_ingestion",
        "correlation_id": payload.incident_id,
        "thread_id": thread.id,
        "source_agent": "api-gateway",
        "target_agent": "orchestrator",
        "payload": payload.model_dump(),
    }
    client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=json.dumps(message),
    )

    # Run the orchestrator agent on this thread
    run = client.agents.create_run(
        thread_id=thread.id,
        agent_id=os.environ["ORCHESTRATOR_AGENT_ID"],
    )

    return {"thread_id": thread.id, "run_id": run.id}
```

### 6.5 Deployment

- Deployed as its own Container App with **public HTTPS ingress** (D-09)
- Fabric Activator (Phase 4) and external callers need to reach it
- Own system-assigned managed identity for Foundry API access
- Container App: `ca-api-gateway-${environment}`

---

## 7. Session Budget Tracking

### 7.1 Requirements (AGENT-007)

- Per-session token budget tracked in Cosmos DB
- Sessions aborted at configurable threshold (default $5)
- `max_iterations` capped at <= 10 per agent session
- Exponential backoff on tool retries

### 7.2 Cosmos DB Schema

The `incidents` container (already provisioned in Phase 1) or a new `sessions` container:

```json
{
  "id": "session_01HXYZ...",
  "incident_id": "inc_01HXYZ...",
  "thread_id": "thread_abc123",
  "agent_id": "compute-agent",
  "status": "active | completed | aborted | budget_exceeded",
  "created_at": "2026-03-26T14:30:00Z",
  "updated_at": "2026-03-26T14:35:00Z",
  "budget": {
    "limit_usd": 5.00,
    "consumed_usd": 0.00,
    "token_counts": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    },
    "ru_consumed": 0.0
  },
  "iterations": {
    "count": 0,
    "max": 10,
    "history": [
      {
        "iteration": 1,
        "tool_name": "monitor.query_logs",
        "tokens_used": 450,
        "cost_usd": 0.0045,
        "timestamp": "2026-03-26T14:30:05Z"
      }
    ]
  },
  "abort_reason": null
}
```

**Partition key:** `incident_id` (co-locate session records with incident records for efficient queries).

### 7.3 Budget Enforcement Pattern

```python
class SessionBudgetTracker:
    def __init__(self, cosmos_container, session_id: str, budget_limit: float = 5.0):
        self.container = cosmos_container
        self.session_id = session_id
        self.budget_limit = budget_limit

    async def track_iteration(self, tool_name: str, token_usage: dict) -> bool:
        """Track token usage and return False if budget exceeded."""
        cost = self._calculate_cost(token_usage)

        # Optimistic concurrency update via ETag
        session = self.container.read_item(self.session_id, partition_key=self.incident_id)
        session["budget"]["consumed_usd"] += cost
        session["budget"]["token_counts"]["total_tokens"] += token_usage["total_tokens"]
        session["iterations"]["count"] += 1

        if session["budget"]["consumed_usd"] >= self.budget_limit:
            session["status"] = "budget_exceeded"
            session["abort_reason"] = f"Budget limit ${self.budget_limit} exceeded"
            self.container.replace_item(session, session, etag=session["_etag"])
            return False  # Signal abort

        if session["iterations"]["count"] >= session["iterations"]["max"]:
            session["status"] = "aborted"
            session["abort_reason"] = f"Max iterations ({session['iterations']['max']}) reached"
            self.container.replace_item(session, session, etag=session["_etag"])
            return False

        self.container.replace_item(session, session, etag=session["_etag"])
        return True

    def _calculate_cost(self, token_usage: dict) -> float:
        # gpt-4o pricing: ~$2.50/1M input, ~$10/1M output
        input_cost = (token_usage.get("prompt_tokens", 0) / 1_000_000) * 2.50
        output_cost = (token_usage.get("completion_tokens", 0) / 1_000_000) * 10.00
        return input_cost + output_cost
```

### 7.4 Aborting a Foundry Thread Mid-Session

When budget is exceeded:

1. Update Cosmos DB session record to `status: budget_exceeded`
2. Cancel the active run on the Foundry thread: `client.agents.cancel_run(thread_id, run_id)`
3. Post a final message to the thread: `"Session aborted: budget limit exceeded"`
4. Emit a `budget_exceeded` event (for future SSE stream in Phase 5)

### 7.5 Exponential Backoff on Tool Retries

```python
import asyncio

async def call_tool_with_backoff(tool_fn, *args, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await tool_fn(*args)
        except (TimeoutError, ConnectionError) as e:
            if attempt == max_retries - 1:
                raise
            delay = min(2 ** attempt, 30)  # 1s, 2s, 4s ... max 30s
            await asyncio.sleep(delay)
```

---

## 8. OpenTelemetry Instrumentation

### 8.1 Requirements (MONITOR-007, AUDIT-001, AUDIT-005)

Every agent tool call must be recorded as an OpenTelemetry span with:

| Field | Source |
|---|---|
| `timestamp` | Span start time |
| `correlationId` | Incident ID (correlation_id from message envelope) |
| `agentId` | Entra Agent ID object ID (AUDIT-005: attributable to specific identity) |
| `agentName` | Domain agent name (e.g., "compute-agent") |
| `toolName` | MCP tool or @ai_function name |
| `toolParameters` | Serialized tool input arguments |
| `outcome` | success / failure / timeout |
| `durationMs` | Span duration |

### 8.2 Package: `azure-monitor-opentelemetry`

The all-in-one Azure Monitor OpenTelemetry Distro:

```bash
pip install azure-monitor-opentelemetry
```

This provides:
- Auto-instrumentation for popular Python packages
- Export to Azure Application Insights via connection string
- Works in Azure Container Apps, AKS, VMs

### 8.3 Configuration in Agent Containers

```python
# agents/shared/telemetry.py
import os
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

def setup_telemetry(agent_name: str):
    """Configure OpenTelemetry for an agent container."""
    configure_azure_monitor(
        connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"],
        # Auto-instrumentation is enabled by default
    )

    # Get tracer for custom spans
    return trace.get_tracer(f"aiops.{agent_name}")
```

### 8.4 Custom Span for Tool Calls

```python
# agents/shared/telemetry.py (continued)
from opentelemetry import trace
from contextlib import contextmanager

@contextmanager
def instrument_tool_call(
    tracer: trace.Tracer,
    agent_name: str,
    agent_id: str,
    tool_name: str,
    tool_params: dict,
    correlation_id: str,
):
    """Create an OpenTelemetry span for a tool call."""
    with tracer.start_as_current_span(f"{agent_name}.{tool_name}") as span:
        span.set_attribute("aiops.agent_name", agent_name)
        span.set_attribute("aiops.agent_id", agent_id)       # Entra object ID
        span.set_attribute("aiops.tool_name", tool_name)
        span.set_attribute("aiops.tool_parameters", str(tool_params))
        span.set_attribute("aiops.correlation_id", correlation_id)
        try:
            yield span
            span.set_attribute("aiops.outcome", "success")
        except Exception as e:
            span.set_attribute("aiops.outcome", "failure")
            span.set_attribute("aiops.error", str(e))
            span.record_exception(e)
            raise
```

### 8.5 Dual Export: App Insights + Fabric OneLake

**App Insights** -- handled by `azure-monitor-opentelemetry` distro (real-time traces).

**Fabric OneLake** -- for long-term audit, we need a second exporter. Options:

1. **OTLP Exporter to a collector sidecar** that forwards to OneLake (recommended)
2. **Direct export** to OneLake via Azure Storage SDK (custom exporter)
3. **Continuous export** from App Insights to OneLake (Azure-native, may have latency)

Recommended approach for Phase 2: Use `azure-monitor-opentelemetry` for App Insights. OneLake export via continuous export or a collector sidecar -- this can be a follow-up in Phase 2 or deferred to Phase 4 when Fabric infrastructure is provisioned.

### 8.6 Agent Framework Auto-Instrumentation

The `azure-ai-agentserver-agentframework` adapter includes auto-instrumentation:
- OpenTelemetry traces for all agent framework operations
- Metrics and logs
- Conversation state management instrumentation

This is bundled -- no additional configuration needed beyond the connection string environment variable.

---

## 9. Shared Base Docker Image

### 9.1 Strategy (D-07)

A shared base image at `agents/Dockerfile.base` installs all common Python dependencies. Each domain agent's Dockerfile starts `FROM base-image` and copies only agent-specific code.

### 9.2 Base Dockerfile

```dockerfile
# agents/Dockerfile.base
FROM python:3.12-slim AS base

WORKDIR /app

# System deps for azure identity + crypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

# Shared Python dependencies
COPY requirements-base.txt .
RUN pip install --no-cache-dir -r requirements-base.txt

# Shared utilities (telemetry, auth, message envelope, cosmos client)
COPY shared/ ./shared/
```

### 9.3 Base Requirements

```
# requirements-base.txt
agent-framework==1.0.0rc5
azure-ai-projects==2.0.1
azure-ai-agentserver-core
azure-ai-agentserver-agentframework
azure-identity>=1.17.0
azure-cosmos>=4.7.0
azure-monitor-opentelemetry>=1.6.0
opentelemetry-sdk>=1.25.0
opentelemetry-exporter-otlp>=1.25.0
pydantic>=2.8.0
```

### 9.4 Domain Agent Dockerfile

```dockerfile
# agents/compute/Dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE:-aap-agents-base:latest}

WORKDIR /app

# Agent-specific dependencies (if any)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Agent code
COPY . ./compute/

# Entry point for Foundry Hosted Agent runtime
CMD ["python", "-m", "compute.agent"]
```

### 9.5 Build Pipeline

1. **Build base image first:** `docker build -f agents/Dockerfile.base -t agents/base:sha .`
2. **Push base to ACR:** `${ACR}/agents/base:sha`
3. **Build each domain agent:** `docker build --build-arg BASE_IMAGE=${ACR}/agents/base:sha -f agents/compute/Dockerfile -t agents/compute:sha .`
4. **Push each agent to ACR:** `${ACR}/agents/compute:sha`

### 9.6 CI Optimization

- Base image rebuild triggered only when `requirements-base.txt` or `agents/shared/` changes
- Domain agent rebuild triggered only when `agents/{name}/` changes
- Uses existing `docker-push.yml` reusable workflow (Phase 1)

---

## 10. CI/CD Pipeline Extensions

### 10.1 New Workflows Needed

| Workflow | Trigger | Purpose |
|---|---|---|
| `agent-spec-lint.yml` | PR with changes to `agents/` | Verify corresponding `docs/agents/{name}-agent.spec.md` exists (AGENT-009) |
| `agent-base-build.yml` | Push to `agents/shared/` or `requirements-base.txt` | Build and push base image |
| `agent-build.yml` | Push to `agents/{name}/` | Build and push per-agent image (calls `docker-push.yml`) |
| `api-gateway-build.yml` | Push to `services/api-gateway/` | Build and push API gateway image |

### 10.2 Agent Spec Lint Gate (AGENT-009, D-03)

```yaml
# .github/workflows/agent-spec-lint.yml
name: Agent Spec Lint
on:
  pull_request:
    paths: ['agents/**/*.py']

jobs:
  check-specs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verify agent specs exist
        run: |
          AGENTS=$(find agents -maxdepth 1 -mindepth 1 -type d \
            -not -name shared -not -name base | sort)
          for agent_dir in $AGENTS; do
            agent_name=$(basename "$agent_dir")
            spec_file="docs/agents/${agent_name}-agent.spec.md"
            if [ ! -f "$spec_file" ]; then
              echo "::error::Missing spec file: $spec_file (required by AGENT-009)"
              exit 1
            fi
          done
          echo "All agent spec files present."
```

### 10.3 Extending the Docker Push Workflow

The existing `docker-push.yml` (Phase 1) is a `workflow_call` reusable workflow. Phase 2 agent builds call it:

```yaml
# .github/workflows/agent-build.yml
name: Build Agent Images
on:
  push:
    branches: [main]
    paths: ['agents/**']

jobs:
  detect-changes:
    # Detect which agents changed
    ...

  build-compute:
    needs: detect-changes
    if: needs.detect-changes.outputs.compute == 'true'
    uses: ./.github/workflows/docker-push.yml
    with:
      image_name: agents/compute
      dockerfile_path: agents/compute/Dockerfile
      build_context: agents/
```

---

## 11. Phase 1 Integration Points

### 11.1 Available Terraform Outputs from Phase 1

These outputs from Phase 1 modules are consumed by Phase 2:

| Phase 1 Module | Output | Consumed By (Phase 2) |
|---|---|---|
| `compute-env` | `container_apps_environment_id` | Agent Container Apps (environment binding) |
| `compute-env` | `container_apps_environment_name` | Agent Container Apps |
| `compute-env` | `acr_login_server` | Agent image references |
| `compute-env` | `acr_name` | CI/CD image push |
| `foundry` | `foundry_account_endpoint` | Agent `AzureAIAgentClient` configuration |
| `foundry` | `foundry_project_id` | Agent Foundry project binding |
| `foundry` | `foundry_model_deployment_name` | Agent model reference (`gpt-4o`) |
| `foundry` | `foundry_principal_id` | RBAC for Foundry identity |
| `databases` | `cosmos_endpoint` | Session budget tracking client |
| `databases` | `cosmos_database_name` | Session budget container reference |
| `monitoring` | `log_analytics_workspace_id` | Container Apps logging |
| `monitoring` | `app_insights_connection_string` | OpenTelemetry export |
| `keyvault` | `keyvault_uri` | Secret references for agents |
| `keyvault` | `keyvault_id` | RBAC for Key Vault access |
| `networking` | `subnet_container_apps_id` | Already consumed by compute-env |

### 11.2 Existing CI Assets

| Asset | Usage in Phase 2 |
|---|---|
| `docker-push.yml` (reusable) | Called by per-agent and API gateway build workflows |
| `terraform-plan.yml` | Runs on PRs with Terraform changes (agent-apps, rbac modules) |
| `terraform-apply.yml` | Applies on merge to main |

### 11.3 Cosmos DB Containers

Phase 1 provisioned:
- `incidents` container (partition key: TBD from Phase 1 config)
- `approvals` container (partition key: TBD)

Phase 2 needs a `sessions` container for budget tracking (AGENT-007), or reuses `incidents` with a different document type. **Decision needed during planning.**

---

## 12. Ordering Constraints & Dependencies

### 12.1 Hard Ordering Within Phase 2

```
Step 1: Agent Spec Documents (AGENT-009)
   |  All 7 docs/agents/{name}-agent.spec.md written and PR-approved
   |  CI lint gate deployed
   |  NO agent .py code allowed before this completes
   |
   v
Step 2: Shared Infrastructure (parallel)
   |  2a: Terraform agent-apps module (7 Container Apps + API gateway)
   |  2b: Terraform rbac module (cross-subscription RBAC)
   |  2c: agents/shared/ (telemetry, auth, message envelope, budget tracker)
   |  2d: agents/Dockerfile.base + CI pipeline
   |
   v
Step 3: API Gateway (depends on 2a)
   |  services/api-gateway/ implementation
   |  Entra auth middleware
   |  Foundry thread creation
   |  Deployed as Container App
   |
   v
Step 4: Agent Implementation (depends on Steps 1, 2, 3)
   |  4a: Orchestrator agent (HandoffOrchestrator)
   |  4b: Compute, Network, Storage, Security, SRE agents (parallel)
   |  4c: Arc agent (stub only)
   |
   v
Step 5: Integration Testing (depends on Step 4)
   |  End-to-end: POST /api/v1/incidents -> Orchestrator -> domain agent
   |  Budget enforcement test
   |  RBAC verification
   |  OpenTelemetry trace verification
```

### 12.2 External Dependencies

| Dependency | Status | Risk |
|---|---|---|
| Phase 1 Terraform (all modules) | Complete | None |
| Foundry workspace + model deployment | Provisioned in Phase 1 | None |
| Cosmos DB + containers | Provisioned in Phase 1 | May need new `sessions` container |
| ACR | Provisioned in Phase 1 | None |
| Container Apps environment | Provisioned in Phase 1 | None |
| Azure MCP Server GA | Available | Need to validate tool coverage |

### 12.3 Parallel Execution Opportunities

- **Spec writing (Step 1)** can overlap with Terraform module development (Step 2a/2b) since specs don't depend on infrastructure
- **Shared utilities (Step 2c)** and **base Docker image (Step 2d)** are independent of Terraform
- **All 5 non-Arc domain agents (Step 4b)** can be developed in parallel
- **API gateway (Step 3)** is independent of agent implementation

---

## 13. Risk Register

### 13.1 Technical Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Agent Framework 1.0.0rc5 has breaking changes in next RC | HIGH | Pin version exactly; wrap all framework calls in thin adapter layer; plan 1-2 days for upgrade testing |
| R2 | `HandoffOrchestrator` API doesn't support the routing pattern we need | HIGH | Verify API in a spike during Step 1 (while writing specs); fallback to manual handoff via `@ai_function` tool calls |
| R3 | Azure MCP Server tool coverage insufficient for Network Agent | MEDIUM | Plan custom `@ai_function` wrappers around `azure-mgmt-network` SDK; document gap in network-agent.spec.md |
| R4 | Foundry Hosted Agent Preview has reliability issues | MEDIUM | Test locally via `localhost:8088/responses` first; have Container Apps direct-run fallback |
| R5 | `azure-ai-agentserver-agentframework` adapter lacks documentation | MEDIUM | Follow Foundry SDK examples closely; test early with minimal agent |
| R6 | Cross-subscription RBAC requires subscription-level scope which needs elevated permissions during Terraform apply | LOW | Ensure CI OIDC identity has `User Access Administrator` on target subscriptions |
| R7 | Session budget calculation inaccurate due to streaming token counting | LOW | Use Foundry usage API for authoritative counts; Cosmos DB tracking is a backstop |

### 13.2 Process Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R8 | Design-first gate (AGENT-009) delays agent implementation | MEDIUM | Start spec writing immediately; specs can be lean (not novels); parallelize with infrastructure work |
| R9 | 21 requirements is a lot for one phase | MEDIUM | Many requirements are naturally fulfilled by the same code (e.g., TRIAGE-002/003/004 are all part of domain agent triage workflow) |

---

## 14. Open Questions for Planning

These should be resolved during plan creation:

| # | Question | Context | Proposed Answer |
|---|---|---|---|
| Q1 | Should session budget tracking use the existing `incidents` container or a new `sessions` container? | Cosmos DB was provisioned with `incidents` and `approvals` in Phase 1 | New `sessions` container -- cleaner separation, different partition key needs |
| Q2 | How do we validate `HandoffOrchestrator` works before writing all 7 agent implementations? | RC API with possible gaps | Plan a spike/prototype in Step 1 alongside spec writing -- minimal Orchestrator + 1 mock domain agent |
| Q3 | Does the Azure MCP Server run as a sidecar or remote service? | CLAUDE.md mentions both `npx` and sidecar patterns | Sidecar in each agent container (simplest); evaluate remote shared service if resource usage is high |
| Q4 | What's the OneLake export strategy for AUDIT-001 spans? | App Insights handles real-time; OneLake needs long-term | Phase 2: App Insights only. Phase 4: Add OneLake export when Fabric is provisioned. Document this as a known gap. |
| Q5 | Do we need a new Cosmos DB container for sessions, or should we add it to Phase 1 Terraform? | Phase 1 databases module handles Cosmos DB | Extend Phase 1 databases module or add to agent-apps module |
| Q6 | What model pricing applies for budget calculation? | gpt-4o pricing changes over time | Use env var for pricing rates; default to current gpt-4o rates; make it configurable |
| Q7 | How is the Arc Agent stub implemented? | Must exist and deploy but has no real tools | Deploy with system prompt saying "Arc capabilities pending Phase 3"; return structured message on any incident |

---

## Research Sources

- [Azure Monitor OpenTelemetry Distro](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-enable) -- auto-instrumentation for Python
- [azure-monitor-opentelemetry on PyPI](https://pypi.org/project/azure-monitor-opentelemetry/) -- all-in-one telemetry package
- [Azure SDK for Python - OpenTelemetry](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/monitor/azure-monitor-opentelemetry/README.md) -- GitHub README
- [OpenTelemetry Configuration for Azure Monitor](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-configuration) -- connection strings, custom instrumentation
- [Azure Container Apps auto-instrumentation](https://learn.microsoft.com/en-us/azure/azure-monitor/app/create-workspace-resource) -- Python support in Container Apps
- [Docker Multi-stage Builds](https://docs.docker.com/build/building/multi-stage/) -- shared base image pattern
- [FastAPI Azure Auth](https://github.com/intility/fastapi-azure-auth) -- `fastapi-azure-auth` library for Entra token validation
- [Azure Cosmos DB Python SDK](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/sdk-python) -- `azure-cosmos` v4.x, request charge tracking
- Project internal: `.planning/research/ARCHITECTURE.md` -- agent graph, message contract, identity architecture
- Project internal: `.planning/research/SUMMARY.md` -- GBB pattern adoption, anti-patterns
- Project internal: `CLAUDE.md` -- technology stack, constraints, version table

---

## Validation Architecture

> Required by Nyquist validation (plan-phase step 5.5). Describes how plans for this phase
> will be verified during execution.

### Test Framework

| Property | Value |
|----------|-------|
| **Language** | Python + TypeScript (CI workflows) |
| **Framework** | pytest 8.x |
| **Quick command** | `python -m pytest agents/ services/ -x -q --tb=short` |
| **Full command** | `python -m pytest agents/ services/ -v --tb=short --cov=agents --cov=services` |
| **Estimated runtime** | ~45 seconds |

### Per-Requirement Verification Map

| Requirement | Test Type | How to Verify |
|-------------|-----------|---------------|
| INFRA-005 | infra | `terraform plan` shows 7 `azapi_resource` blocks for Entra Agent IDs; `az identity show` per agent |
| INFRA-006 | infra | `az role assignment list --scope /subscriptions/{id}` shows expected assignments per agent |
| AGENT-001 | integration | `pytest tests/integration/test_handoff.py` — synthetic incident routes to correct domain agent via HandoffOrchestrator |
| AGENT-002 | unit | `pytest tests/shared/test_envelope.py` — validates all TypedDict fields present and typed correctly |
| AGENT-003 | infra | `az containerapp show` for each of 6 domain agents returns `provisioningState: Succeeded` |
| AGENT-004 | integration | `pytest tests/integration/test_mcp_tools.py` — Compute Agent calls `compute.list_vms`, returns structured response |
| AGENT-007 | unit | `pytest tests/shared/test_budget.py` — forces cost > $5 threshold, asserts `BudgetExceededException` raised, Cosmos record shows `status: aborted` |
| AGENT-008 | security | `trivy image {acr}/{agent}:sha` returns 0 secrets; `az role assignment list` shows only managed identity |
| AGENT-009 | lint | `spec-lint.yml` CI check passes; all 7 `docs/agents/{name}-agent.spec.md` files exist with required sections |
| DETECT-004 | integration | `pytest tests/api_gateway/test_incidents.py` — POST with valid payload returns 202, Foundry thread created |
| MONITOR-001 | integration | `pytest tests/integration/test_monitor.py` — agent session queries metrics across 2 mock subscriptions |
| MONITOR-002 | integration | KQL query via agent chat returns log results; verified in integration test |
| MONITOR-003 | integration | Agent response includes `resource_health` and `service_health` fields alongside metrics |
| MONITOR-007 | integration | `az monitor app-insights events show` — OTel spans with `agentId`, `toolName`, `durationMs` present |
| TRIAGE-001 | integration | `pytest tests/integration/test_triage.py` — Orchestrator classifies by domain, typed handoff message verified |
| TRIAGE-002 | integration | Each domain agent test asserts Log Analytics + Resource Health both queried before diagnosis |
| TRIAGE-003 | integration | Agent test asserts Activity Log change query executed as first step for every incident |
| TRIAGE-004 | integration | Agent response contains `hypothesis`, `evidence`, and `confidence_score` fields |
| REMEDI-001 | integration | `pytest tests/integration/test_remediation.py` — SRE proposal generated, assert no ARM write calls in subscription activity log |
| AUDIT-001 | integration | OTel spans in App Insights contain all 8 required action log fields |
| AUDIT-005 | integration | Each span's `agentId` field matches the specific Entra Agent ID object ID (not "system") |

### Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| No ARM writes without approval in real subscription | REMEDI-001 | Requires live Azure subscription activity log | Check `az monitor activity-log list` after SRE agent proposal; assert no write operations |
| Managed identity auth in deployed container | AGENT-008 | IMDS only available in Azure runtime | SSH into Container App console, `curl -H "Metadata: true" http://169.254.169.254/metadata/identity/oauth2/token` returns token |
| End-to-end OTel trace in Application Insights | MONITOR-007 | Requires deployed App Insights with real data | Azure Portal → App Insights → Transaction Search → filter by `operation_Name: incidents` |

### Wave 0 Requirements

- [ ] `agents/tests/shared/test_envelope.py` — stubs for AGENT-002 envelope validation
- [ ] `agents/tests/shared/test_budget.py` — stubs for AGENT-007 budget enforcement
- [ ] `services/api_gateway/tests/test_incidents.py` — stubs for DETECT-004
- [ ] `pytest.ini` or `pyproject.toml` — test discovery config at repo root
- [ ] `agents/shared/__init__.py` — package init for import resolution in tests

---

*Research completed: 2026-03-26. All cross-references verified against CONTEXT.md, REQUIREMENTS.md, ROADMAP.md, ARCHITECTURE.md, and Phase 1 Terraform outputs.*
