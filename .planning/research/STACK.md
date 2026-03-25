# Stack Research — Azure AIOps Agentic Platform

> Research date: 2026-03-25
> All versions verified against live PyPI, npm, GitHub releases, and Microsoft Learn documentation.

---

## Core Agent Framework

### Microsoft Agent Framework (Python)

| Attribute | Value |
|---|---|
| **Package** | `agent-framework` |
| **Install** | `pip install agent-framework --pre` |
| **Latest version** | `1.0.0rc5` (released 2026-03-20) |
| **Status** | ⚠️ **Pre-release (RC)** — high-velocity, breaking changes likely before GA |
| **Python requirement** | ≥ 3.10 |
| **License** | MIT |

#### Key APIs

```python
from agent_framework import Agent, ChatAgent, ai_function
from agent_framework.azure import AzureAIAgentClient

# Tool declaration
@ai_function
def describe_vm(resource_id: str) -> str:
    """Fetch VM details from ARM."""
    ...

# Agent instantiation
compute_agent = ChatAgent(
    chat_client=AzureAIAgentClient(
        project_endpoint=os.getenv("PROJECT_ENDPOINT"),
        model_deployment_name="gpt-4.1",
        credential=DefaultAzureCredential(),
    ),
    instructions="You are the Compute domain specialist...",
    tools=[describe_vm],
)
```

**Key classes:**
- `ChatAgent` — the primary agent class for conversational agents; wraps `AzureAIAgentClient`
- `Agent` — lower-level base class; use `ChatAgent` for this platform
- `@ai_function` — decorator that exposes a Python function as an LLM-callable tool; replaces manual JSON schema definition
- `AzureAIAgentClient` — Azure AI Foundry backend client; uses `project_endpoint` + `DefaultAzureCredential`
- `OpenAIChatClient` / `AzureOpenAIChatClient` — non-Foundry backends; **not recommended here**

#### Supported Orchestration Patterns

The framework explicitly supports:

| Pattern | Use in this Platform |
|---|---|
| **Sequential** | Orchestrator → Domain Agent → result chain |
| **Handoff** | Orchestrator delegates to Compute/Network/Storage/Security/Arc/SRE agents |
| **Group Chat** | Multi-specialist collaboration on complex incidents |
| **Concurrent** | Parallel agent fan-out for multi-domain investigations |
| **Magentic** | Agentic planning with self-directed subtask decomposition |

For the domain-specialist graph, use **Handoff** as the primary pattern: the Orchestrator agent routes to the appropriate domain specialist and hands control back with a structured result.

#### Deployment as Foundry Hosted Agents

Wrap each agent with the **Hosting Adapter**:

```python
# Packages required per agent container
pip install agent-framework --pre
pip install azure-ai-agentserver-core
pip install azure-ai-agentserver-agentframework

# Entry point
from azure.ai.agentserver.agentframework import from_agent_framework
if __name__ == "__main__":
    from_agent_framework(agent).run()  # starts on localhost:8088
```

The hosting adapter provides:
- Protocol translation between Foundry Responses API and agent framework native format
- Auto-instrumentation (OpenTelemetry traces, metrics, logs)
- Conversation state management
- Local testability before containerization (test via `POST localhost:8088/responses`)

**Container requirements:**
- Build with `--platform linux/amd64` (Hosted Agents run on Linux AMD64 only)
- Push to Azure Container Registry (ACR)
- Grant project managed identity `Container Registry Repository Reader` role on ACR

**Registration via SDK (requires `azure-ai-projects >= 2.0.0`):**

```python
agent = client.agents.create_version(
    agent_name="compute-agent",
    definition=HostedAgentDefinition(
        container_protocol_versions=[ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="v1")],
        cpu="1", memory="2Gi",
        image="your-acr.azurecr.io/compute-agent:v1",
        tools=[{"type": "mcp", "project_connection_id": "azure-mcp-connection-id"}],
        environment_variables={"PROJECT_ENDPOINT": "...", "MODEL_NAME": "gpt-4.1"},
    )
)
```

**Capacity host prerequisite** (one-time per Foundry account):
```bash
az rest --method put \
  --url ".../capabilityHosts/accountcaphost?api-version=2025-10-01-preview" \
  --body '{"properties": {"capabilityHostKind": "Agents", "enablePublicHostingEnvironment": true}}'
```

**Hosting adapter packages:**
- `azure-ai-agentserver-core` — core adapter (all agents)
- `azure-ai-agentserver-agentframework` — Microsoft Agent Framework adapter
- `azure-ai-agentserver-langgraph` — LangGraph adapter (not needed here)

#### Rationale

Microsoft Agent Framework is the stated successor to AutoGen, purpose-built for Foundry Hosted Agents deployment. It is the only framework with first-party hosting adapter support (`azure-ai-agentserver-agentframework`). The domain-specialist graph maps cleanly to the Handoff pattern. The `@ai_function` decorator eliminates manual tool schema boilerplate.

#### Confidence: **MEDIUM** — RC quality, high-velocity; pin versions tightly

---

## Azure Integration Layer

### Foundry Agent Service SDK — `azure-ai-projects`

| Attribute | Value |
|---|---|
| **Package** | `azure-ai-projects` |
| **Install** | `pip install "azure-ai-projects>=2.0.1"` |
| **Latest stable version** | `2.0.1` (released 2026-03-12) |
| **Status** | ✅ **GA (Stable)** — production/stable, v1 Foundry REST APIs |
| **Python requirement** | ≥ 3.9 |

#### Key Classes for this Platform

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    # Hosted agent management
    HostedAgentDefinition,
    ProtocolVersionRecord,
    AgentProtocol,
    # Prompt agent management
    Agent,
    AgentThread,
    ThreadMessage,
    MessageDeltaChunk,
    # Streaming
    AgentStreamEvent,
)
from azure.identity import DefaultAzureCredential

client = AIProjectClient(
    endpoint="https://<resource>.services.ai.azure.com/api/projects/<project>",
    credential=DefaultAzureCredential(),
    allow_preview=True,  # required for hosted agents during Preview
)
```

**Conversation management (Prompt Agents):**
```python
thread = client.agents.create_thread()
client.agents.create_message(thread_id=thread.id, role="user", content="...")

# Streaming
with client.agents.create_stream(thread_id=thread.id, assistant_id=agent.id) as stream:
    for event_type, event_data, _ in stream:
        if isinstance(event_data, MessageDeltaChunk):
            yield event_data.text  # stream to frontend
```

**Hosted agent invocation (Responses API):**
```python
openai_client = client.get_openai_client()
response = openai_client.responses.create(
    input=[{"role": "user", "content": "..."}],
    extra_body={"agent_reference": {"name": "compute-agent", "type": "agent_reference"}}
)
```

**Async client** (for FastAPI / async services):
```python
from azure.ai.projects.aio import AIProjectClient as AsyncAIProjectClient
```

**Optional tracing dependencies:**
```
pip install opentelemetry-sdk azure-core-tracing-opentelemetry azure-monitor-opentelemetry
```

#### Companion package — `azure-ai-agents`

| Attribute | Value |
|---|---|
| **Package** | `azure-ai-agents` |
| **Latest stable** | `1.1.0` (2025-08-05); pre-release `1.2.0b6` |
| **Status** | ⚠️ Stable but superseded by `azure-ai-projects` 2.x for most use cases |

Microsoft recommends pairing `azure-ai-agents` with `azure-ai-projects` for "an enhanced experience." For this platform, **use `azure-ai-projects` as the primary SDK**. `azure-ai-agents` adds built-in tool support (Bing grounding, Azure AI Search, Logic Apps). Import from it when you need those tool definitions:

```python
from azure.ai.agents.models import BingGroundingTool, FileSearchTool
```

#### Rationale

`azure-ai-projects` 2.x is the GA SDK for Foundry Agent Service. It covers the complete lifecycle: create/update hosted agents, manage conversations, invoke via Responses API, and stream events. The 2.0.1 bug fix release is the current stable baseline.

#### Confidence: **HIGH** — GA, production-stable

---

## MCP Tool Surfaces

### Azure MCP Server (GA)

| Attribute | Value |
|---|---|
| **Package** | `@azure/mcp` (npm, run as sidecar) OR invoke via `npx @azure/mcp@latest start` |
| **Distribution** | npm package `@azure/mcp`; also `azmcp` binary |
| **Status** | ✅ **GA** |
| **Authentication** | Entra ID via `DefaultAzureCredential` / managed identity |

#### Covered Services (confirmed in docs, March 2026)

| Domain | Tools Available |
|---|---|
| ARM / Resource management | `group`, `subscription`, `role`, `quota`, `policy`, `advisor`, `resourcehealth` |
| Compute | `compute` (VMs, VMSS, disks), `aks` (list), `appservice`, `functionapp`, `servicefabric` |
| Storage | `storage`, `fileshares`, `storagesync`, `managedlustre` |
| Databases | `cosmos`, `postgres`, `mysql`, `sql`, `redis` |
| Networking | (via `appservice`, `signalr`; no dedicated VNet/NSG tools confirmed) |
| Monitoring | `monitor` (Log Analytics queries + metrics), `applicationinsights`, `applens`, `workbooks` |
| Security | `keyvault`, `role` |
| AI/ML | `foundry`, `search`, `speech` |
| Messaging/Events | `eventhubs`, `servicebus`, `eventgrid` |
| DevOps | `deploy`, `bicepschema`, `grafana`, `loadtesting` |
| Identity | `role` (RBAC assignments) |
| Containers | `acr` (list) |

#### Arc Coverage Gap (CONFIRMED)

The Azure MCP Server tools catalog has **NO Arc-specific namespaces or tools**. The "Hybrid and multicloud" category only lists `postgres` and `sql` (generic, not Arc-specific). **There are no tools for:**

- Arc-enabled servers (`Microsoft.HybridCompute/machines`)
- Arc-enabled Kubernetes (`Microsoft.Kubernetes/connectedClusters`)
- Arc-enabled data services (SQL Managed Instance, PostgreSQL)
- Azure Arc extensions management
- Arc guest configuration / policy compliance

This gap is the architectural justification for the custom Arc MCP Server.

#### Mounting in a Foundry Hosted Agent

Connect via Foundry's `RemoteMCPTool` connection (registered in the Foundry project, then referenced by connection ID):

```python
definition=HostedAgentDefinition(
    tools=[{"type": "mcp", "project_connection_id": "azure-mcp-connection-id"}],
    ...
)
```

For local development / Container Apps deployment, run the MCP server as a sidecar or as a separate Container Apps instance and configure the agent to call it via HTTP (Streamable HTTP transport).

#### Confidence: **HIGH** — GA, tool list verified from docs

---

### Custom Arc MCP Server

| Attribute | Value |
|---|---|
| **Framework** | `mcp` Python package (FastMCP high-level API) |
| **Package** | `mcp[cli]` |
| **Install** | `pip install "mcp[cli]>=1.26.0"` |
| **Latest version** | `1.26.0` (released 2026-01-24) |
| **Python requirement** | ≥ 3.10 |
| **Transport** | Streamable HTTP (recommended for production) |
| **Status** | ✅ **Stable** |

#### Recommended Approach: FastMCP + Azure SDK

Use the `FastMCP` high-level API (built into the `mcp` package — it is **not** a separate package):

```python
from mcp.server.fastmcp import FastMCP
from azure.mgmt.hybridcompute import HybridComputeManagementClient
from azure.mgmt.containerservice import ContainerServiceClient
from azure.identity import DefaultAzureCredential
import os

mcp = FastMCP("arc-mcp-server", stateless_http=True)
credential = DefaultAzureCredential()

@mcp.tool()
def list_arc_servers(subscription_id: str, resource_group: str | None = None) -> list[dict]:
    """List all Arc-enabled servers in a subscription, optionally filtered by resource group."""
    client = HybridComputeManagementClient(credential, subscription_id)
    machines = client.machines.list_by_resource_group(resource_group) if resource_group \
               else client.machines.list_by_subscription()
    return [{"name": m.name, "status": m.status, "os": m.os_name,
             "location": m.location, "id": m.id} for m in machines]

@mcp.tool()
def list_arc_kubernetes_clusters(subscription_id: str) -> list[dict]:
    """List all Arc-enabled Kubernetes clusters."""
    client = ContainerServiceClient(credential, subscription_id)
    # Use connectedClusters API
    ...

@mcp.tool()
def get_arc_server_extensions(subscription_id: str, resource_group: str, machine_name: str) -> list[dict]:
    """Get extensions installed on an Arc-enabled server."""
    ...
```

**Entry point for Container Apps:**
```python
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
```

#### Azure SDK packages for Arc tools

```
pip install azure-mgmt-hybridcompute        # Arc-enabled servers
pip install azure-mgmt-hybridkubernetes     # Arc-enabled Kubernetes
pip install azure-mgmt-azurearcdata         # Arc-enabled data services
pip install azure-mgmt-guestconfiguration   # Arc guest config / policy
pip install azure-mgmt-resource             # ARM resources (general)
pip install azure-identity                  # Managed identity auth
```

#### Why FastMCP (not alternatives)

| Option | Verdict |
|---|---|
| **FastMCP (in `mcp` package)** | ✅ **Use this.** Official Python MCP SDK. Decorator-based, Pydantic validation, production Streamable HTTP transport, actively maintained by Anthropic/MCP community. Ships as `mcp.server.fastmcp`. |
| `mcp-python` (third-party) | ❌ Unofficial fork; do not use |
| `fastmcp` (separate PyPI package) | ⚠️ Was a community project; FastMCP is now absorbed into the official `mcp` package. Use `mcp[cli]` directly. |
| Bare REST API sidecar | ❌ Loses MCP protocol compliance, tool discovery, schema generation |

#### Confidence: **HIGH** — mcp 1.26.0 is stable; FastMCP is the idiomatic Python path

---

## Real-Time Detection Plane (Fabric)

### Fabric Eventhouse + Activator

| Component | Status | Notes |
|---|---|---|
| **Fabric Eventhouse** | ✅ GA | KQL-native time-series store; auto-mirrors to OneLake |
| **Fabric Activator** | ✅ GA | Event detection engine with webhook/pipeline trigger |
| **Fabric Eventstreams** | ✅ GA | No-code ingestion pipeline; Azure Event Hubs connector included |
| **Fabric IQ / Operations Agent** | ⚠️ Preview | Do NOT place on critical path; graceful degradation required |

#### Pipeline: Azure Monitor → Eventhouse → Activator → API

```
Azure Monitor Alert Rules
        │
        ▼ (Diagnostic Settings or Event Hub export)
Azure Event Hub Namespace
        │
        ▼ (Fabric Eventstream – Event Hubs connector, no code)
Fabric Eventstream
        │
        ├──▶ Eventhouse (KQL Database) — store + query
        │
        └──▶ Activator — rule evaluation → HTTP action
```

**Step 1: Connect Azure Monitor to Event Hubs**

Use Azure Monitor Diagnostic Settings to stream activity logs, resource logs, and metrics to an Event Hub:

```bash
az monitor diagnostic-settings create \
  --resource <resource-id> \
  --name "to-eventhub" \
  --event-hub <eventhub-name> \
  --event-hub-rule <auth-rule-id> \
  --logs '[{"category":"Administrative","enabled":true}]' \
  --metrics '[{"category":"AllMetrics","enabled":true}]'
```

For Azure Monitor Alerts specifically, configure **Action Groups** to forward to Event Hubs (via webhook or direct connector).

**Step 2: Fabric Eventstream → Eventhouse**

In Fabric Real-Time Hub, create an Eventstream with:
- Source: Azure Event Hubs (using Event Hub connection string or managed identity)
- Destination: Eventhouse KQL Database table

No code required; schema auto-detected or manually mapped.

**Step 3: KQL Detection Rules in Eventhouse**

```kql
// Example: VM CPU alert detection
MonitorAlerts
| where TimeGenerated > ago(5m)
| where AlertSeverity in ("Sev0", "Sev1", "Sev2")
| where AlertState == "New"
| where ResourceType == "microsoft.compute/virtualmachines"
| summarize AlertCount = count(),
            AffectedResources = make_set(ResourceId),
            MaxSeverity = min(toint(AlertSeverity))  // lower = more severe
  by bin(TimeGenerated, 1m), ResourceGroup, SubscriptionId
| where AlertCount >= 1
```

**Step 4: Activator Trigger → Platform REST API**

Activator supports these action types natively:
- Fabric Pipelines, Notebooks, Spark Jobs, Functions
- Power Automate flows
- Teams notifications
- Email

**For calling the agent platform REST API**, use **Power Automate** as the intermediary (Activator → Power Automate flow → HTTP POST to agent API). This is the supported pattern; Activator does not yet support direct arbitrary HTTP webhook calls without Power Automate.

Alternative: configure Activator to trigger a **Fabric User Data Function** (serverless Python) that calls your agent API directly:

```python
# Fabric User Data Function triggered by Activator
def main(event: dict) -> None:
    import requests, os
    requests.post(
        os.environ["AGENT_API_URL"] + "/incidents",
        json={"alert": event, "source": "fabric-activator"},
        headers={"Authorization": f"Bearer {get_token()}"}
    )
```

#### Terraform provisioning of Fabric

Fabric Eventhouse and Activator are provisioned via **`azapi`** provider (not `azurerm`):
```hcl
resource "azapi_resource" "fabric_eventhouse" {
  type      = "Microsoft.Fabric/workspaces/eventhouses@2023-11-01"
  name      = "aap-eventhouse"
  parent_id = azapi_resource.fabric_workspace.id
  body = jsonencode({ properties = {} })
}
```

#### Confidence: **HIGH** for Eventhouse + Activator (both GA). **LOW** for Fabric IQ/Operations Agent (Preview — exclude from critical path)

---

## Frontend (Next.js + Fluent UI 2)

### Next.js App Router

| Attribute | Value |
|---|---|
| **Package** | `next` |
| **Latest version** | `15.x` (Next.js 15; docs reference 16.2.1 route handler docs in March 2026) |
| **Install** | `npx create-next-app@latest --typescript --app` |
| **Runtime** | Node.js (not Edge Runtime — needed for Azure SDK calls in API routes) |
| **Status** | ✅ GA |

#### Token Streaming: SSE vs WebSocket

**Recommendation: Server-Sent Events (SSE) via App Router Route Handlers**

| Approach | Verdict |
|---|---|
| **SSE (ReadableStream in Route Handler)** | ✅ **Recommended.** Native Web API, no extra infra, works through Azure Container Apps, half-duplex (server → client) which is all that's needed for token streaming. |
| **WebSocket** | ⚠️ More complex; requires separate WebSocket server or Azure Web PubSub; Container Apps support WebSockets but adds operational overhead. Use only if bidirectional push is needed. |
| **Vercel AI SDK (`ai` package)** | ⚠️ Useful abstraction but adds a dependency and may conflict with Foundry's streaming format. Acceptable for prototyping. |

**Dual-stream pattern** for co-equal chat + agent trace events:

```typescript
// app/api/chat/route.ts
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  const { message, conversationId } = await req.json()

  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder()

      // Stream 1: Token stream (SSE event: "token")
      // Stream 2: Agent trace events (SSE event: "trace")
      // Both multiplexed on the same SSE connection using event types

      const foundryStream = await callFoundryAgent(message, conversationId)
      for await (const event of foundryStream) {
        if (event.type === 'token') {
          controller.enqueue(encoder.encode(`event: token\ndata: ${JSON.stringify({text: event.delta})}\n\n`))
        } else if (event.type === 'tool_call') {
          controller.enqueue(encoder.encode(`event: trace\ndata: ${JSON.stringify(event)}\n\n`))
        }
      }
      controller.close()
    }
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    }
  })
}
```

**Client-side consumption:**
```typescript
// hooks/useAgentStream.ts
const eventSource = new EventSource('/api/chat', { /* ... */ })
// For POST-based SSE, use fetch with ReadableStream (not EventSource):
const response = await fetch('/api/chat', { method: 'POST', body: JSON.stringify({...}) })
const reader = response.body!.getReader()
// Parse SSE lines manually or use @microsoft/fetch-event-source
```

**Recommendation:** Use `@microsoft/fetch-event-source` for POST-based SSE:
```
npm install @microsoft/fetch-event-source
```

#### Confidence: **HIGH** — SSE + App Router Route Handlers is the established pattern

---

### Fluent UI 2

| Attribute | Value |
|---|---|
| **Package** | `@fluentui/react-components` |
| **Latest version** | `9.73.4` (released 2026-03-17) |
| **Install** | `npm install @fluentui/react-components` |
| **Styling engine** | Griffel (CSS-in-JS, SSR-compatible) |
| **Status** | ✅ GA (v9 is current stable) |

#### Next.js App Router SSR Considerations

Fluent UI v9 uses **Griffel** for styling, which requires server-side rendering setup to avoid flash of unstyled content (FOUC) and hydration mismatches.

**Critical:** Fluent UI components are **client components** (they use React context, event handlers, and browser APIs). They **cannot** be React Server Components (RSC). You must mark any file that uses Fluent UI with `'use client'`.

**Recommended setup:**

```typescript
// app/providers.tsx — 'use client' boundary
'use client'
import { FluentProvider, webLightTheme, webDarkTheme } from '@fluentui/react-components'
import { createDOMRenderer, SSRProvider, RendererProvider } from '@fluentui/react-components'

// For SSR: use SSRProvider wrapping
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <FluentProvider theme={webLightTheme}>
      {children}
    </FluentProvider>
  )
}

// app/layout.tsx — Server Component
import { Providers } from './providers'

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
```

**Griffel SSR renderer** (for extracting styles server-side — reduces FOUC):
```typescript
// middleware or _document equivalent for style extraction
import { createDOMRenderer, renderToStyleElements } from '@fluentui/react-components'
```

For Next.js App Router, the simplest working approach is `'use client'` on a `Providers` wrapper. Full server-side style extraction with Griffel requires additional configuration in the Next.js build pipeline; defer this optimization to post-MVP.

**Required peer dependencies:**
```
npm install react react-dom  # 18.x or 19.x
```

#### What NOT to use

- `@fluentui/react` v8 — the legacy Fabric/Office UI Fabric package; heavy, Office-branded, not the right baseline for a modern Azure ops UI
- `@fluentui/web-components` — web components variant; does not compose well with React state

#### Confidence: **HIGH** — v9 is current and well-maintained; SSR pattern is settled

---

## Teams Integration

### Teams SDK (New, 2026)

| Attribute | Value |
|---|---|
| **TypeScript package** | `@microsoft/teams.js` + `@microsoft/teams.ai` (new Teams SDK) |
| **Python package** | `microsoft-teams-ai` (`teams-ai` on PyPI, v1.8.1 — **old SDK**) |
| **Python Teams SDK new** | `microsoft.teams` + `microsoft.teams.ai` (new SDK, Python preview) |
| **CLI bootstrap** | `npx @microsoft/teams.cli@latest new typescript my-agent --template echo` |
| **Status** | New Teams SDK: ✅ GA for TypeScript; ⚠️ Preview for Python |

#### Recommendation: TypeScript Teams Bot (New Teams SDK)

For the Teams bot, **use TypeScript** with the new Teams SDK (`@microsoft/teams.js`). The new SDK is purpose-built with significantly better developer experience than the legacy Bot Framework SDK. Python support is present but lags behind.

```typescript
// Bootstrap with CLI
npx @microsoft/teams.cli@latest new typescript aap-bot --template echo

// Key packages
npm install @microsoft/teams.js @microsoft/teams.ai
```

**Architecture:** Deploy the Teams bot as an Azure Container Apps service. The bot receives messages from Teams, forwards them to the Foundry Agent Service, streams responses back to Teams.

#### Adaptive Card Approval Flow

The approval workflow is the critical path for human-in-the-loop remediation:

```typescript
// 1. Agent proposes action → bot sends Adaptive Card to Teams channel
const approvalCard = {
  type: "AdaptiveCard",
  version: "1.5",
  body: [
    { type: "TextBlock", text: "Remediation Approval Required", weight: "Bolder", size: "Large" },
    { type: "FactSet", facts: [
      { title: "Action:", value: action.description },
      { title: "Resource:", value: action.resourceId },
      { title: "Impact:", value: action.estimatedImpact },
      { title: "Agent:", value: action.proposedBy },
    ]},
  ],
  actions: [
    { type: "Action.Submit", title: "Approve", data: { action: "approve", remediationId: action.id, style: "positive" } },
    { type: "Action.Submit", title: "Reject",  data: { action: "reject",  remediationId: action.id, style: "destructive" } },
  ]
}

// 2. Bot handles action submit → calls platform API
app.adaptiveCards.actionExecute('approve', async (context, state) => {
  await platformApi.approveRemediation(context.activity.value.remediationId)
  return { type: "AdaptiveCard", body: [{ type: "TextBlock", text: "✅ Approved" }] }
})
```

**Approval state machine:**
```
Agent proposes → Platform stores pending approval (Cosmos DB)
  → Bot sends Adaptive Card to Teams channel
  → User clicks Approve/Reject → Teams sends invoke activity to bot
  → Bot calls platform API: PATCH /remediations/{id}/decision
  → Platform executes (if approved) or cancels (if rejected)
  → Bot updates card to show final state
```

#### Legacy Bot Framework SDK — avoid for new development

| SDK | Verdict |
|---|---|
| `botbuilder` (Python, npm `botbuilder`) | ❌ **Avoid for new work.** Legacy Bot Framework SDK. Heavy, complex, not designed for AI-native bots. Still works but the new Teams SDK is the Microsoft-recommended path. |
| `teams-ai` (PyPI, v1.8.1) | ⚠️ Transitional — older Teams AI Library built on Bot Framework. Works but will not receive new features from the new SDK path. |
| New Teams SDK (`@microsoft/teams.js`) | ✅ **Use this.** Rebuilt from ground up, clean DX, active development. |

#### Confidence: **HIGH** for new Teams SDK TypeScript; **MEDIUM** for Python (behind TypeScript)

---

## Data Persistence

### Polyglot Persistence Summary

| Store | Package | Version | Use Case | Status |
|---|---|---|---|---|
| **Foundry Agent Service** | `azure-ai-projects` | 2.0.1 | Agent conversation threads + state | ✅ GA (managed) |
| **Azure Cosmos DB** | `azure-cosmos` (Python) | `4.x` | Hot-path alerts, agent session context, pending approvals | ✅ GA |
| **PostgreSQL Flexible Server** | `asyncpg` or `psycopg[binary]` | asyncpg `0.30.x`; psycopg3 `3.2.x` | Runbook library, RBAC config, platform settings | ✅ GA |
| **pgvector** | `pgvector` (Python) | `0.3.x` | Runbook RAG / semantic search | ✅ GA |
| **Fabric OneLake** | `azure-storage-file-datalake` | `12.x` | Audit logs, alert history, resource inventory snapshots | ✅ GA |

#### Cosmos DB Recommendations

```
pip install azure-cosmos>=4.9.0
```

Use the **NoSQL API** (not Mongo or Cassandra). Enable **serverless** tier for dev, switch to provisioned throughput (with autoscale) for prod. Use a **composite partition key** on `(tenantId, sessionId)` for conversation context to avoid hot partitions.

#### PostgreSQL + pgvector for Runbook RAG

```
pip install "psycopg[binary]>=3.2" pgvector>=0.3
```

Enable the pgvector extension on PostgreSQL Flexible Server:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE runbooks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    content text NOT NULL,
    domain text NOT NULL,  -- 'compute', 'network', 'storage', etc.
    embedding vector(1536),  -- text-embedding-3-small dimensions
    created_at timestamptz DEFAULT now()
);
CREATE INDEX ON runbooks USING ivfflat (embedding vector_cosine_ops);
```

#### Confidence: **HIGH** across all persistence layers

---

## Infrastructure as Code (Terraform)

### Provider Strategy

| Provider | Version | When to Use |
|---|---|---|
| `azurerm` (HashiCorp) | `~> 4.65.0` (latest: 4.65.0, 2026-03-19) | Standard Azure resources: Container Apps, Cosmos DB, PostgreSQL, VNet, Storage, Key Vault, Event Hubs, ACR, App Insights |
| `azapi` (Azure) | `~> 2.9.0` (latest: 2.9.0, 2026-03-23) | Foundry resources, Fabric, Entra Agent ID, capability hosts, preview API features |
| `azuread` (HashiCorp) | `~> 3.x` | Entra ID service principals, app registrations, group membership |

#### Provider Configuration

```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.65.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.9.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
  }
  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "tfstateaap"
    container_name       = "tfstate"
    key                  = "prod.terraform.tfstate"
    use_azuread_auth     = true  # Use Entra ID, not storage key
  }
}
```

#### Resource Mapping: azurerm vs azapi

| Resource | Provider | Terraform Resource |
|---|---|---|
| Resource Groups | `azurerm` | `azurerm_resource_group` |
| VNet + Subnets | `azurerm` | `azurerm_virtual_network`, `azurerm_subnet` |
| Container Apps Environment | `azurerm` | `azurerm_container_app_environment` |
| Container Apps | `azurerm` | `azurerm_container_app` |
| Cosmos DB Account | `azurerm` | `azurerm_cosmosdb_account` |
| PostgreSQL Flexible Server | `azurerm` | `azurerm_postgresql_flexible_server` |
| Azure Event Hubs | `azurerm` | `azurerm_eventhub_namespace`, `azurerm_eventhub` |
| Azure Container Registry | `azurerm` | `azurerm_container_registry` |
| Key Vault | `azurerm` | `azurerm_key_vault` |
| Application Insights | `azurerm` | `azurerm_application_insights` |
| Storage Account (Terraform state) | `azurerm` | `azurerm_storage_account` |
| **Foundry Account** | **`azurerm`** | **`azurerm_cognitive_account` (kind = "AIServices")** |
| **Foundry Project** | **`azurerm`** | **`azurerm_cognitive_account_project`** |
| **Foundry Model Deployment** | **`azurerm`** | **`azurerm_cognitive_deployment`** |
| **Foundry Capability Host** | **`azapi`** | `azapi_resource` (type: `Microsoft.CognitiveServices/accounts/capabilityHosts`) |
| **Foundry MCP Connection** | **`azapi`** | `azapi_resource` (type: `Microsoft.CognitiveServices/accounts/projects/connections`) |
| **Fabric Workspace** | **`azapi`** | `azapi_resource` (type: `Microsoft.Fabric/workspaces`) |
| **Fabric Eventhouse** | **`azapi`** | `azapi_resource` (type: `Microsoft.Fabric/workspaces/eventhouses`) |
| **Fabric Activator** | **`azapi`** | `azapi_resource` (type: `Microsoft.Fabric/workspaces/activators`) |
| **Entra Agent ID** | **`azapi`** | `azapi_data_plane_resource` (type: `Microsoft.Foundry/agents`) |
| Private Endpoints | `azurerm` | `azurerm_private_endpoint` |
| RBAC Assignments | `azurerm` | `azurerm_role_assignment` |

#### Key Foundry Terraform Pattern

```hcl
# Foundry account (azurerm is sufficient for core provisioning)
resource "azurerm_cognitive_account" "foundry" {
  name                  = "aap-foundry"
  location              = var.location
  resource_group_name   = azurerm_resource_group.main.name
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = "aap-foundry"
  project_management_enabled = true
  identity { type = "SystemAssigned" }
}

# Foundry project
resource "azurerm_cognitive_account_project" "aap" {
  name                 = "aap-project"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = azurerm_resource_group.main.location
  identity { type = "SystemAssigned" }
}

# Capability host (azapi required — not in azurerm)
resource "azapi_resource" "capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/capabilityHosts@2025-10-01-preview"
  name      = "accountcaphost"
  parent_id = azurerm_cognitive_account.foundry.id
  body = {
    properties = {
      capabilityHostKind         = "Agents"
      enablePublicHostingEnvironment = true
    }
  }
}
```

#### State Management

```hcl
# Backend: Azure Storage with Entra auth (no shared access keys)
backend "azurerm" {
  use_azuread_auth = true
  # Enable state locking via Azure Blob lease (built-in)
}
```

CI/CD pattern:
- **PR**: `terraform plan` (output as PR comment via GitHub Actions)
- **Merge to main**: `terraform apply -auto-approve` (gated by required reviewers)
- Use separate state files per environment: `dev.tfstate`, `staging.tfstate`, `prod.tfstate`

#### Confidence: **HIGH** for azurerm 4.65.0; **HIGH** for azapi 2.9.0; azapi required for Foundry capability hosts, Fabric, and Entra Agent ID

---

## E2E Testing

### Playwright

| Attribute | Value |
|---|---|
| **Package** | `@playwright/test` |
| **Latest version** | `1.58.2` (released 2026-02-06) |
| **Install** | `npm install -D @playwright/test@1.58.2` |
| **Status** | ✅ GA, stable |

#### E2E Pattern for Entra-Protected Azure Container Apps

**Challenge:** Container Apps with Entra EasyAuth require browser-based OAuth flow. CI environments cannot complete interactive MFA.

**Solution:** Service principal + client credentials flow with token injection, bypassing the browser OAuth flow:

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  projects: [
    // Auth setup runs first, saves state
    { name: 'auth-setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['auth-setup'],
    }
  ]
})
```

```typescript
// tests/auth.setup.ts
import { test as setup } from '@playwright/test'
import path from 'path'

const authFile = path.join(__dirname, '../playwright/.auth/user.json')

setup('authenticate', async ({ page }) => {
  // Navigate to the Container App (triggers Entra redirect)
  await page.goto(process.env.APP_URL!)

  // Fill Entra login form
  await page.fill('input[type="email"]', process.env.TEST_USER_EMAIL!)
  await page.click('input[type="submit"]')
  await page.fill('input[type="password"]', process.env.TEST_USER_PASSWORD!)
  await page.click('input[type="submit"]')

  // Handle "Stay signed in?" prompt
  await page.click('input[type="submit"]')

  // Wait for app to fully load
  await page.waitForURL(process.env.APP_URL!)

  // Persist auth state
  await page.context().storageState({ path: authFile })
})
```

```typescript
// tests/chat.spec.ts
import { test, expect } from '@playwright/test'

test('agent responds to compute query', async ({ page }) => {
  await page.goto('/chat')
  await page.fill('[data-testid="chat-input"]', 'List all VMs in the prod subscription')
  await page.click('[data-testid="chat-send"]')

  // Wait for streaming to complete
  await expect(page.locator('[data-testid="agent-response"]')).toContainText('Virtual Machine', { timeout: 30000 })

  // Verify agent trace events appeared
  await expect(page.locator('[data-testid="trace-panel"]')).toBeVisible()
})
```

**For CI/CD against deployed Container Apps:**

```yaml
# .github/workflows/e2e.yml
- name: Run Playwright Tests
  env:
    APP_URL: https://aap-frontend.azurecontainerapps.io
    TEST_USER_EMAIL: ${{ secrets.E2E_USER_EMAIL }}
    TEST_USER_PASSWORD: ${{ secrets.E2E_USER_PASSWORD }}
  run: npx playwright test
```

**Token expiry handling:** Entra tokens expire. For CI, either:
1. Provision a **dedicated test service principal** with password auth (no MFA) scoped only to the test environment
2. Use `storageState` expiry detection: if 401, re-run `auth.setup.ts` before the test suite

**Alternative — bypass EasyAuth for API-level tests:**
```typescript
// For API-level E2E tests (not UI), use client credentials directly:
const token = await getServicePrincipalToken({
  tenantId: process.env.AZURE_TENANT_ID!,
  clientId: process.env.E2E_CLIENT_ID!,
  clientSecret: process.env.E2E_CLIENT_SECRET!,
})
const response = await request.post('/api/chat', {
  headers: { Authorization: `Bearer ${token}` },
  data: { message: '...' }
})
```

#### Confidence: **HIGH** — Playwright 1.58.2 is current stable; auth pattern is well-established

---

## What NOT to Use (and Why)

| Technology | Verdict | Reason |
|---|---|---|
| **AutoGen / AG2 (`pyautogen`)** | ❌ Do not use | AutoGen is in maintenance mode per Microsoft's own positioning; AG2 (community fork) has no enterprise support. Microsoft Agent Framework is the stated successor. |
| **Semantic Kernel `AzureAIAgent` wrapper** | ❌ Do not use | Explicitly marked **Experimental** in the Semantic Kernel SDK. Not a stable API; Microsoft's own docs flag this. Use `azure-ai-projects` directly. |
| **Semantic Kernel (core orchestration)** | ⚠️ Avoid for agent orchestration | SK is GA for plugins/planners but its agent orchestration primitives trail Microsoft Agent Framework. Would introduce framework fragmentation. SK remains useful for embedding/memory patterns. |
| **Copilot Studio / Power Platform agents** | ❌ Out of scope | Low-code, not developer-first. Insufficient programmatic control for AIOps. Confirmed out of scope in PROJECT.md. |
| **LangGraph** | ⚠️ Not recommended | LangGraph is supported by Foundry Hosted Agents (has an adapter), but it's a third-party framework with no Microsoft enterprise support. Introduces an external dependency for no benefit when Microsoft Agent Framework provides equivalent orchestration natively. |
| **AKS (Azure Kubernetes Service)** | ⚠️ Deferred | Container Apps is sufficient for this platform. Add AKS only if scale demands it. Confirmed deferred in PROJECT.md. |
| **Azure Container Instances (ACI)** | ❌ Do not use | No scaling, no managed networking, no revision management. Container Apps is strictly superior. |
| **@fluentui/react v8 ("Fabric")** | ❌ Do not use | Legacy Office UI Fabric; not actively developed for new features. v9 (`@fluentui/react-components`) is the correct package. |
| **Bot Framework SDK (`botbuilder`)** | ❌ Avoid for new bots | Legacy SDK. New Teams SDK (`@microsoft/teams.js`) is the Microsoft-recommended replacement with cleaner developer experience. |
| **`teams-ai` v1.8.1 (old Teams AI Library)** | ⚠️ Legacy path | Built on Bot Framework; will not receive new features. Migrate to new Teams SDK for fresh development. |
| **Vercel AI SDK (`ai` package)** | ⚠️ Use sparingly | Useful helper but opinionated about streaming format. May conflict with Foundry's SSE format. Use raw `ReadableStream` for direct Foundry integration; `ai` package only as a thin convenience wrapper if needed. |
| **`fastmcp` (separate PyPI package)** | ❌ Obsolete | FastMCP was a community project. It is now absorbed into the official `mcp` package as `mcp.server.fastmcp`. Use `pip install mcp[cli]`. |
| **Fabric IQ / Operations Agent** | ⚠️ Preview — keep off critical path | Not GA; no developer SDK. Use Eventhouse + Activator (both GA) for the detection plane. Add Fabric IQ semantic layer only as enrichment once GA. |
| **Entra Agent ID** | ⚠️ Preview — provision but plan for changes | Important for agent identity governance but the API may change before GA. Provision with `azapi` and be prepared for breaking changes in `2025-10-01-preview` API version. |
| **Foundry Hosted Agents** | ⚠️ Preview — no private networking | Critical architectural note: Hosted Agents do not support private networking during Preview. Container Apps fill this gap for VNet-isolated services. Do not put Hosted Agents behind a private endpoint until GA. |
| **Azure SignalR Service** | ⚠️ Overkill | Would add cost and complexity for WebSocket management. SSE via Container Apps is sufficient for token streaming and agent trace events. |
| **pgvector on Cosmos DB** | ⚠️ Not recommended | Cosmos DB for NoSQL vector search exists but pgvector on PostgreSQL is more mature for runbook RAG with hybrid keyword+vector search. Keep PostgreSQL as the runbook store. |

---

## Summary: Versions At a Glance

| Component | Package | Version | Status |
|---|---|---|---|
| Agent Framework | `agent-framework` | `1.0.0rc5` | ⚠️ Pre-release RC |
| Hosting Adapter | `azure-ai-agentserver-agentframework` | latest | ⚠️ Preview |
| Foundry SDK | `azure-ai-projects` | `2.0.1` | ✅ GA |
| Azure MCP Server | `@azure/mcp` (npm) | GA | ✅ GA |
| Arc MCP Framework | `mcp[cli]` | `1.26.0` | ✅ Stable |
| Fabric Eventhouse | (Fabric SaaS) | GA | ✅ GA |
| Fabric Activator | (Fabric SaaS) | GA | ✅ GA |
| Next.js | `next` | `15.x` | ✅ GA |
| Fluent UI v9 | `@fluentui/react-components` | `9.73.4` | ✅ GA |
| Teams SDK (TS) | `@microsoft/teams.js` | latest | ✅ GA (TS) |
| Cosmos DB SDK | `azure-cosmos` | `4.x` | ✅ GA |
| pgvector | `pgvector` | `0.3.x` | ✅ GA |
| Terraform azurerm | hashicorp/azurerm | `~> 4.65.0` | ✅ GA |
| Terraform azapi | azure/azapi | `~> 2.9.0` | ✅ GA |
| Playwright | `@playwright/test` | `1.58.2` | ✅ GA |

---

*Last updated: 2026-03-25 — Stack Research for Azure AIOps Agentic Platform*
