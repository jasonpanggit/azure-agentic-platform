# Azure AIOps Agentic Platform — Architecture

> Version: 1.0 | Stack: Microsoft Agent Framework 1.0.0rc5 · Azure AI Foundry · FastMCP 1.26.0 · Next.js App Router · Terraform azurerm ~>4.65 + azapi ~>2.9

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          DETECTION PLANE                                        │
│                                                                                 │
│  Azure Monitor Alerts ──► Event Hub ──► Fabric Eventhouse (KQL rules)          │
│                                                 │                               │
│                                         Fabric Activator                        │
│                                         (Power Automate / User Data Fn)         │
│                                                 │                               │
│                               REST POST /api/v1/incidents                       │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────────────┐
│                          AGENT PLATFORM                                         │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │              Azure AI Foundry (Hosted Agents — Responses API)           │   │
│  │                                                                         │   │
│  │   ┌──────────────────────────────────────────────────────────────────┐  │   │
│  │   │                    Orchestrator Agent                             │  │   │
│  │   │          (Microsoft Agent Framework — HandoffOrchestrator)       │  │   │
│  │   └────┬──────┬──────┬──────┬──────┬──────┬───────────────────────┘  │   │
│  │        │      │      │      │      │      │                            │   │
│  │   ┌────▼─┐ ┌──▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼───┐ ┌▼────┐                  │   │
│  │   │Compu-│ │Net- │ │Stor-│ │Secu-│ │Arc │ │SRE  │                  │   │
│  │   │ te   │ │work │ │age  │ │rity │ │    │ │     │   domain agents   │   │
│  │   └──┬───┘ └──┬──┘ └──┬──┘ └──┬──┘ └─┬──┘ └──┬──┘                  │   │
│  │      │        │        │        │       │       │                      │   │
│  └──────┼────────┼────────┼────────┼───────┼───────┼──────────────────────┘   │
│         │        │        │        │       │       │                            │
│  ┌──────▼────────▼────────▼────────▼───────▼───────▼──────────────────────┐   │
│  │                        MCP Tool Layer                                   │   │
│  │   ┌─────────────────────┐      ┌───────────────────────────────────┐   │   │
│  │   │  Azure MCP Server   │      │    Custom Arc MCP Server          │   │   │
│  │   │  (msmcp-azure GA)   │      │    (FastMCP / Container App)      │   │   │
│  │   └─────────────────────┘      └───────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────────────┐
│                             UI LAYER                                            │
│                                                                                 │
│  ┌───────────────────────────────────┐   ┌──────────────────────────────────┐  │
│  │   Next.js App Router (Container   │   │   Teams Bot                      │  │
│  │   App) + Tailwind CSS + shadcn/ui │   │   (@microsoft/teams.js)          │  │
│  │                                   │   │   Adaptive Card approvals        │  │
│  │   Dual SSE: token + trace events  │   │   Shared Foundry thread ID       │  │
│  └───────────────────────────────────┘   └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────────────┐
│                             DATA LAYER                                          │
│                                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ Foundry      │  │ Cosmos DB    │  │ PostgreSQL +     │  │ Fabric         │  │
│  │ Threads      │  │ (hot-path    │  │ pgvector         │  │ OneLake        │  │
│  │ (agent       │  │  incident    │  │ (operational /   │  │ (analytics /   │  │
│  │  memory)     │  │  state)      │  │  RAG embeddings) │  │  audit)        │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────────────┐
│                          AZURE RESOURCES (multi-subscription)                   │
│                                                                                 │
│  Sub: platform     Sub: compute    Sub: network    Sub: security   Sub: arc     │
│  ┌─────────────┐  ┌─────────────┐ ┌─────────────┐ ┌────────────┐ ┌──────────┐  │
│  │ AI Foundry  │  │ VMs, VMSS,  │ │ VNets,      │ │ Defender,  │ │ Arc svrs │  │
│  │ Container   │  │ AKS, Batch  │ │ AppGW, FW   │ │ Sentinel   │ │ Arc K8s  │  │
│  │ Apps, ACR   │  │             │ │             │ │ Key Vault  │ │ Arc Data │  │
│  └─────────────┘  └─────────────┘ └─────────────┘ └────────────┘ └──────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent Graph Architecture

### 2.1 Orchestrator Routing Pattern

The Orchestrator uses the Microsoft Agent Framework `HandoffOrchestrator` pattern. Domain agents register themselves as `AgentTarget` instances. The Orchestrator classifies incoming incidents and hands off to the correct domain agent, which can further hand back for cross-domain issues.

```
                         ┌─────────────────────────────┐
    Incident payload ───►│       Orchestrator Agent      │
                         │  HandoffOrchestrator          │
                         │  - classify_incident()        │
                         │  - route_to_domain()          │
                         │  - collect_human_approval()   │
                         └──────────────┬────────────────┘
                                        │
               ┌────────────────────────┼────────────────────────┐
               │      route by          │    incident.domain      │
               ▼                        ▼                         ▼
   ┌─────────────────┐    ┌─────────────────────┐   ┌─────────────────────┐
   │  ComputeAgent   │    │   NetworkAgent       │   │   SecurityAgent     │
   │  AgentTarget    │    │   AgentTarget        │   │   AgentTarget       │
   │                 │    │                      │   │                     │
   │  - diagnose()   │    │  - diagnose()        │   │  - diagnose()       │
   │  - remediate()  │    │  - remediate()       │   │  - remediate()      │
   └────────┬────────┘    └──────────┬───────────┘   └──────────┬──────────┘
            │                        │                           │
            └────────────────────────▼───────────────────────────┘
                              HandoffResult
                         {needs_cross_domain: true}
                                    │
                                    ▼
                         Orchestrator re-routes
                         to secondary domain agent
```

**Python registration pattern:**

```python
# agent_graph.py
from agent_framework import HandoffOrchestrator, AgentTarget, HandoffMessage

orchestrator = HandoffOrchestrator(
    name="aiops-orchestrator",
    client=azure_ai_client,          # AzureAIAgentClient
    instructions=ORCHESTRATOR_PROMPT,
)

for domain, agent_id in DOMAIN_AGENT_IDS.items():
    orchestrator.add_target(AgentTarget(
        name=f"{domain}-agent",
        agent_id=agent_id,           # Foundry Hosted Agent ID
        description=AGENT_DESCRIPTIONS[domain],
    ))
```

### 2.2 Message Contract

All messages between agents use a typed JSON envelope. Agents MUST NOT pass raw strings.

```json
{
  "$schema": "https://aiops.internal/schemas/agent-message/v1",
  "message_id": "msg_01HXYZ...",
  "correlation_id": "inc_01HXYZ...",
  "thread_id": "thread_abc123",
  "timestamp_utc": "2026-03-25T14:30:00Z",
  "source_agent": "orchestrator",
  "target_agent": "compute",
  "message_type": "handoff_request | handoff_response | approval_request | approval_response | tool_result",
  "payload": {
    "incident": {
      "id": "inc_01HXYZ...",
      "severity": "Sev1 | Sev2 | Sev3 | Sev4",
      "domain": "compute | network | storage | security | arc | sre",
      "title": "string",
      "description": "string",
      "affected_resources": [
        {
          "resource_id": "/subscriptions/{sub}/resourceGroups/{rg}/providers/...",
          "subscription_id": "string",
          "resource_type": "string"
        }
      ],
      "kql_detection_rule": "string",
      "raw_alert": {}
    },
    "diagnosis": {
      "summary": "string",
      "root_cause_hypothesis": "string",
      "confidence": 0.0,
      "evidence": ["string"],
      "recommended_actions": [
        {
          "action_id": "act_01...",
          "description": "string",
          "tool": "string",
          "tool_args": {},
          "risk_level": "low | medium | high | critical",
          "requires_approval": true
        }
      ]
    },
    "approval_context": {
      "requested_by_agent": "string",
      "approval_card_id": "string",
      "teams_conversation_id": "string",
      "deadline_utc": "string",
      "approved": null
    }
  }
}
```

### 2.3 Entra Agent ID Scoping

Each domain agent has a dedicated Entra Agent ID (system-assigned managed identity surfaced as a service principal). RBAC is granted only to the subscriptions and resource types the agent needs — principle of least privilege enforced at the identity layer.

```
Entra Tenant
│
├── aiops-orchestrator-agent-id      → Reader on platform subscription
│                                    → No direct resource access
│
├── aiops-compute-agent-id           → VM Contributor on compute subscription
│                                    → Monitoring Reader (platform + compute)
│
├── aiops-network-agent-id           → Network Contributor on network subscription
│                                    → Reader on compute subscription
│
├── aiops-storage-agent-id           → Storage Account Contributor on all subs
│
├── aiops-security-agent-id          → Security Reader + Security Admin
│                                    → Key Vault Secrets User (read-only)
│
├── aiops-arc-agent-id               → Azure Connected Machine Contributor
│                                    → Kubernetes Extension Contributor
│                                    → Arc Data Services Contributor
│
└── aiops-sre-agent-id               → Reader on all subscriptions
                                     → Log Analytics Reader
                                     → Action Group Contributor
```

**Container Apps managed identity binding:**

```hcl
# terraform/modules/agent-identities/main.tf  (azapi)
resource "azapi_resource" "agent_identity" {
  for_each  = var.domain_agents
  type      = "Microsoft.App/containerApps@2024-03-01"
  # identity block sets system-assigned identity
  # Foundry Hosted Agents reference identity via agent_definition.identity_resource_id
}
```

### 2.4 Human-in-the-Loop Integration

Remediation actions with `risk_level: high | critical` ALWAYS require human approval before execution. The approval gate is embedded in the agent graph as a blocking `wait_for_approval()` step.

```
Domain Agent
    │
    ├─ diagnose() ──► builds remediation plan
    │
    ├─ for each action where requires_approval == true:
    │     │
    │     ├─► ApprovalManager.request_approval(action)
    │     │        │
    │     │        ├─► POST Adaptive Card to Teams channel
    │     │        ├─► Write approval record to Cosmos DB
    │     │        └─► Suspend agent (Foundry thread park)
    │     │
    │     │   ... Teams user clicks Approve / Reject ...
    │     │
    │     ├─◄ Webhook callback: POST /api/v1/approvals/{approval_id}
    │     │        │
    │     │        ├─► Update Cosmos DB record
    │     │        └─► Resume Foundry thread (inject approval result)
    │     │
    │     └─ if approved: execute_tool(action)
    │        else: log_rejection(), skip action
    │
    └─ HandoffResult back to Orchestrator
```

---

## 3. Dual SSE Streaming Architecture

### 3.1 Single SSE Connection — Two Event Types

One HTTP/2 persistent connection carries two multiplexed logical streams distinguished by SSE `event:` field:

```
GET /api/stream?thread_id=thread_abc123
Accept: text/event-stream

──────── SSE wire format ────────────────────────────────────────────────────
event: token
data: {"delta": "Analysing VM cpu", "agent": "orchestrator", "seq": 1}

event: token
data: {"delta": " utilisation...", "agent": "orchestrator", "seq": 2}

event: trace
data: {"type": "tool_call", "agent": "compute", "tool": "azure-mcp/list-vms",
       "args": {"subscription": "sub-compute"}, "seq": 3, "ts": "..."}

event: token
data: {"delta": "Found 3 VMs above 95%", "agent": "compute", "seq": 4}

event: trace
data: {"type": "handoff", "from": "compute", "to": "orchestrator",
       "reason": "diagnosis_complete", "seq": 5, "ts": "..."}

event: trace
data: {"type": "approval_gate", "action_id": "act_01...", "seq": 6, "ts": "..."}

event: done
data: {"thread_id": "thread_abc123", "final_status": "awaiting_approval"}
──────────────────────────────────────────────────────────────────────────────
```

### 3.2 Next.js App Router Route Handler

```
app/
└── api/
    └── stream/
        └── route.ts          ← SSE Route Handler
```

```typescript
// app/api/stream/route.ts
import { NextRequest } from 'next/server';
import { AzureAIAgentClient } from '@azure/ai-agent';
import { streamFoundryThread } from '@/lib/foundry/stream';

export const runtime = 'nodejs';   // required for SSE — not edge
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const threadId = req.nextUrl.searchParams.get('thread_id');

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const enqueue = (event: string, data: unknown) => {
        controller.enqueue(
          encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
        );
      };

      for await (const chunk of streamFoundryThread(threadId)) {
        if (chunk.type === 'text_delta') {
          enqueue('token', { delta: chunk.delta, agent: chunk.agent, seq: chunk.seq });
        } else if (chunk.type === 'tool_call' || chunk.type === 'handoff') {
          enqueue('trace', { ...chunk });
        } else if (chunk.type === 'done') {
          enqueue('done', { thread_id: threadId, final_status: chunk.status });
          controller.close();
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',     // disable Nginx buffering
    },
  });
}
```

### 3.3 Tailwind CSS + shadcn/ui Rendering

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Incident Dashboard  (Next.js page)                                      │
│                                                                          │
│  ┌───────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │  Chat Bubble Panel            │  │  Agent Trace Panel              │  │
│  │  (token stream renderer)      │  │  (trace stream renderer)        │  │
│  │                               │  │                                 │  │
│  │  ┌──────────────────────────┐ │  │  ┌─────────────────────────┐   │  │
│  │  │ [orchestrator]           │ │  │  │ ▶ tool_call             │   │  │
│  │  │ Analysing VM cpu         │ │  │  │   azure-mcp/list-vms    │   │  │
│  │  │ utilisation...           │ │  │  │   { "subscription":     │   │  │
│  │  └──────────────────────────┘ │  │  │     "sub-compute" }     │   │  │
│  │  ┌──────────────────────────┐ │  │  └─────────────────────────┘   │  │
│  │  │ [compute]                │ │  │  ┌─────────────────────────┐   │  │
│  │  │ Found 3 VMs above 95%... │ │  │  │ ▶ handoff               │   │  │
│  │  │ ▌ (streaming cursor)     │ │  │  │   compute → orchestrator│   │  │
│  │  └──────────────────────────┘ │  │  └─────────────────────────┘   │  │
│  │                               │  │  ┌─────────────────────────┐   │  │
│  │  [Approve] [Reject] (HITL)    │  │  │ ⏸ approval_gate         │   │  │
│  │                               │  │  │   act_01: restart VM    │   │  │
│  └───────────────────────────────┘  │  └─────────────────────────┘   │  │
│                                     └─────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Component architecture:**

```typescript
// components/incident/IncidentStream.tsx
'use client';
import { useState, useEffect, useRef } from 'react';
import { ChatMessage } from '@fluentui/react-components';   // Fluent UI 2
import { AgentTraceTree } from './AgentTraceTree';

export function IncidentStream({ threadId }: { threadId: string }) {
  const [tokens, setTokens] = useState<TokenChunk[]>([]);
  const [traces, setTraces] = useState<TraceEvent[]>([]);

  useEffect(() => {
    const es = new EventSource(`/api/stream?thread_id=${threadId}`);

    es.addEventListener('token', (e) => {
      const chunk: TokenChunk = JSON.parse(e.data);
      setTokens(prev => mergeTokenChunk(prev, chunk));   // append delta to last bubble
    });

    es.addEventListener('trace', (e) => {
      const event: TraceEvent = JSON.parse(e.data);
      setTraces(prev => [...prev, event]);               // append to trace tree
    });

    es.addEventListener('done', () => es.close());
    return () => es.close();
  }, [threadId]);

  return (
    <div className="incident-stream-layout">
      <ChatBubblePanel tokens={tokens} />
      <AgentTraceTree events={traces} />
    </div>
  );
}
```

### 3.4 Handling Agent Handoff Gaps

During agent-to-agent handoff, the Foundry Responses API may produce a gap in the token stream (no `text_delta` events while routing). The frontend handles this with a "thinking" indicator injected as a synthetic trace event:

```typescript
// lib/foundry/stream.ts
async function* streamFoundryThread(threadId: string) {
  let lastTokenSeq = 0;
  let handoffInProgress = false;

  for await (const event of foundryClient.threads.stream(threadId)) {
    if (event.type === 'thread.run.step.created' &&
        event.data.step_details.type === 'tool_calls') {
      // Check for handoff tool call
      const toolName = event.data.step_details.tool_calls[0]?.function?.name;
      if (toolName === 'handoff') {
        handoffInProgress = true;
        yield { type: 'trace', kind: 'handoff_start', ts: new Date().toISOString() };
      }
    }
    if (event.type === 'thread.message.delta') {
      if (handoffInProgress) {
        handoffInProgress = false;
        yield { type: 'trace', kind: 'handoff_end', ts: new Date().toISOString() };
      }
      yield {
        type: 'text_delta',
        delta: event.data.delta.content[0]?.text?.value ?? '',
        agent: extractAgentName(event),
        seq: ++lastTokenSeq,
      };
    }
  }
  yield { type: 'done', status: 'complete' };
}
```

---

## 4. Foundry Hosted Agent Deployment

### 4.1 Container Image Structure

Each domain agent is a self-contained Python container. The Foundry Hosted Agent runtime calls the container's entry point and injects the `AzureAIAgentClient` context.

```
agents/
├── base/
│   ├── Dockerfile.base          # Python 3.12-slim + shared deps
│   └── requirements-base.txt   # agent-framework==1.0.0rc5, azure-ai-projects, etc.
│
├── compute/
│   ├── Dockerfile               # FROM base
│   ├── agent.py                 # ComputeAgent definition
│   ├── tools.py                 # compute-specific tool wrappers
│   ├── prompts/
│   │   └── system.md
│   └── requirements.txt
│
├── network/
│   └── ... (same structure)
├── storage/
├── security/
├── arc/
│   ├── Dockerfile
│   ├── agent.py
│   ├── tools.py                 # wraps Arc MCP Server tools
│   └── prompts/
│       └── system.md
└── sre/
```

**Base Dockerfile:**

```dockerfile
# agents/base/Dockerfile.base
FROM python:3.12-slim

WORKDIR /app

# System deps for azure identity + crypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

COPY requirements-base.txt .
RUN pip install --no-cache-dir -r requirements-base.txt

# Managed identity is resolved via DefaultAzureCredential at runtime
ENV AZURE_CLIENT_ID=""          # set by Container Apps env binding
```

**Domain agent Dockerfile:**

```dockerfile
# agents/compute/Dockerfile
FROM aiops.azurecr.io/agents/base:latest

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "agent"]    # entrypoint called by Foundry runtime
```

### 4.2 AzureAIAgentClient Registration

```python
# agents/compute/agent.py
import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from agent_framework import AgentDefinition, tool

credential = DefaultAzureCredential()   # resolves Container Apps managed identity

project_client = AIProjectClient(
    subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
    resource_group_name=os.environ["AZURE_RESOURCE_GROUP"],
    project_name=os.environ["FOUNDRY_PROJECT_NAME"],
    credential=credential,
)

# Register or retrieve the hosted agent definition
compute_agent = project_client.agents.create_or_update(
    agent_id=os.environ.get("FOUNDRY_AGENT_ID"),   # idempotent
    model=os.environ["FOUNDRY_MODEL_DEPLOYMENT"],   # gpt-4o
    name="aiops-compute-agent",
    instructions=open("prompts/system.md").read(),
    tools=get_compute_tools(),    # MCP tool descriptors + custom tools
    tool_resources=get_mcp_resources(),
    metadata={"domain": "compute", "version": "1.0.0"},
)
```

### 4.3 Inter-Agent A2A Handoff

```python
# agents/compute/agent.py  (continued)
from agent_framework import HandoffAction, AgentTarget

# Define handoff targets this agent can route to
handoff_targets = [
    AgentTarget(
        name="network-agent",
        agent_id=os.environ["NETWORK_AGENT_ID"],
        description="Handle network-related root causes: NIC, NSG, VNet, DNS",
        handoff_condition="root cause involves network configuration",
    ),
    AgentTarget(
        name="orchestrator",
        agent_id=os.environ["ORCHESTRATOR_AGENT_ID"],
        description="Return to orchestrator when diagnosis is complete or needs cross-domain coordination",
        handoff_condition="diagnosis complete OR needs multiple domains",
    ),
]

@tool(name="request_cross_domain_analysis")
def request_cross_domain_analysis(target_domain: str, context: str) -> HandoffAction:
    """Trigger a handoff to another domain agent for cross-domain issues."""
    target = next(t for t in handoff_targets if target_domain in t.name)
    return HandoffAction(target=target, message=context)
```

---

## 5. Real-Time Detection Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DETECTION PIPELINE                                       │
│                                                                             │
│  Azure Resources                                                            │
│       │                                                                     │
│       │  Diagnostic Settings / Azure Monitor                                │
│       ▼                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Azure Monitor                                                       │   │
│  │  - Metric Alerts (CPU, memory, disk, latency thresholds)            │   │
│  │  - Log Alerts (KQL queries over Log Analytics workspace)            │   │
│  │  - Service Health Alerts                                            │   │
│  └────────────────────────┬─────────────────────────────────────────────┘  │
│                            │ Alert fired → Action Group                     │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Azure Event Hub  (Standard tier, 10 partitions)                    │   │
│  │  Namespace: aiops-eventhub-ns                                       │   │
│  │  Hub: raw-alerts                                                    │   │
│  └────────────────────────┬─────────────────────────────────────────────┘  │
│                            │ Fabric Eventhouse connector (streaming ingest)  │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Fabric Eventhouse (KQL — Real-Time Intelligence)                   │   │
│  │                                                                      │   │
│  │  Tables:                                                             │   │
│  │    RawAlerts          ← raw Event Hub ingestion                     │   │
│  │    EnrichedAlerts     ← join with CMDB/resource inventory           │   │
│  │    DetectionResults   ← output of detection rules                   │   │
│  │                                                                      │   │
│  │  Detection Rules (KQL update policies):                             │   │
│  │    .alter table DetectionResults policy update @'[{                 │   │
│  │      "Source": "EnrichedAlerts",                                    │   │
│  │      "Query": "EnrichedAlerts                                       │   │
│  │        | where severity in ('Sev1','Sev2')                          │   │
│  │        | where not(resource_id in (SuppressedResources))            │   │
│  │        | extend domain = classify_domain(resource_type)             │   │
│  │        | project-away raw_payload",                                 │   │
│  │      "IsEnabled": true, "IsTransactional": true                     │   │
│  │    }]'                                                               │   │
│  └────────────────────────┬─────────────────────────────────────────────┘  │
│                            │ Activator trigger on DetectionResults          │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Fabric Activator                                                    │   │
│  │  Trigger: new row in DetectionResults where domain != null           │   │
│  │  Action: call Power Automate flow OR User Data Function              │   │
│  └────────────────────────┬─────────────────────────────────────────────┘  │
│                            │                                                │
│             ┌──────────────┴──────────────────────┐                        │
│             │                                     │                        │
│             ▼  (simple alerts)                    ▼  (complex enrichment)  │
│   Power Automate Flow                   Fabric User Data Function          │
│   (HTTP connector)                      (Python, low-latency path)         │
│             │                                     │                        │
│             └──────────────┬────────────────────--┘                        │
│                            │                                                │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Agent Platform REST API  (Container App: api-gateway)              │   │
│  │  POST /api/v1/incidents                                              │   │
│  │  {                                                                   │   │
│  │    "incident_id": "inc_01...",                                       │   │
│  │    "severity": "Sev1",                                               │   │
│  │    "domain": "compute",                                              │   │
│  │    "affected_resources": [...],                                      │   │
│  │    "detection_rule": "HighCPUVMs",                                   │   │
│  │    "kql_evidence": "..."                                             │   │
│  │  }                                                                   │   │
│  └────────────────────────┬─────────────────────────────────────────────┘  │
│                            │                                                │
│                            ▼                                                │
│             Orchestrator Agent — new Foundry thread created                 │
│             incident dispatched to domain agent graph                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

**KQL domain classifier function:**

```kql
// Fabric Eventhouse: classify_domain() function
.create-or-alter function classify_domain(resource_type: string) {
    case(
        resource_type has_any ("virtualMachines", "virtualMachineScaleSets", "batchAccounts"), "compute",
        resource_type has_any ("virtualNetworks", "networkSecurityGroups", "loadBalancers", "firewalls"), "network",
        resource_type has_any ("storageAccounts", "fileServices", "blobServices"), "storage",
        resource_type has_any ("vaults", "defenderForCloud", "sentinelWorkspaces"), "security",
        resource_type has_any ("connectedMachines", "connectedClusters", "dataControllers"), "arc",
        "sre"
    )
}
```

---

## 6. Teams Bot Architecture

### 6.1 SDK Integration

The bot uses `@microsoft/teams.js` (new Teams AI SDK) and shares the Foundry thread ID with the web UI session to maintain conversation continuity.

```
Teams Channel
    │
    │  User types: "@AIOps show incident inc_01..."
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Teams Bot  (Container App: teams-bot)                          │
│  @microsoft/teams.js                                            │
│                                                                 │
│  app.message('incident', async (ctx, next) => {                 │
│    const incidentId = extractIncidentId(ctx.activity.text);     │
│    const thread = await getOrCreateFoundryThread(incidentId);   │
│    await ctx.sendActivity(buildStatusCard(thread));             │
│    await next();                                                │
│  });                                                            │
└──────────────────────────────┬──────────────────────────────────┘
                               │  shared thread_id
                               ▼
                    Foundry Conversation Thread
                    (same thread_id accessible
                     from web UI session)
```

### 6.2 Adaptive Card Approval Flow

```
Domain Agent
    │
    │  approval_request generated
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ApprovalManager.send_to_teams(action, thread_id)                    │
│                                                                      │
│  1. Build Adaptive Card v1.5 payload:                                │
│     {                                                                │
│       "type": "AdaptiveCard",                                        │
│       "body": [                                                      │
│         {"type": "TextBlock", "text": "Action: restart VM prod-01"}, │
│         {"type": "FactSet", "facts": [                               │
│           {"title": "Risk", "value": "High"},                        │
│           {"title": "Justification", "value": "CPU 98% for 15min"}   │
│         ]}                                                           │
│       ],                                                             │
│       "actions": [                                                   │
│         {"type": "Action.Http", "title": "Approve",                  │
│          "url": "https://api.aiops.internal/approvals/{id}/approve"}, │
│         {"type": "Action.Http", "title": "Reject",                   │
│          "url": "https://api.aiops.internal/approvals/{id}/reject"}  │
│       ]                                                              │
│     }                                                                │
│                                                                      │
│  2. POST card to Teams channel via Bot Framework connector           │
│  3. Write approval record to Cosmos DB:                              │
│     { id, action_id, thread_id, status: "pending", expires_at }     │
│  4. Park Foundry thread (agent suspends — no polling)                │
└──────────────────────────────────────────────────────────────────────┘
                               │
              Teams user clicks [Approve] or [Reject]
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Webhook: POST /api/v1/approvals/{id}/approve                        │
│  (Container App: api-gateway, authenticated via HMAC + Entra)       │
│                                                                      │
│  1. Validate HMAC signature on request                               │
│  2. Update Cosmos DB: { status: "approved", approved_by, ts }        │
│  3. Inject approval result into Foundry thread:                      │
│     project_client.threads.messages.create(                          │
│       thread_id=thread_id,                                           │
│       role="tool",                                                   │
│       content=f"APPROVAL_RESULT: approved by {user_id}"              │
│     )                                                                │
│  4. Resume thread run → agent continues execution                    │
│  5. Update Adaptive Card to show "Approved by {user} at {time}"     │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.3 Context Sync: Teams ↔ Web UI

```
┌──────────────────────┐        ┌──────────────────────┐
│   Teams Conversation │        │   Web UI Session      │
│                      │        │                       │
│  thread_id stored in │◄──────►│  thread_id in URL:    │
│  Teams conversation  │        │  /incidents/inc_01?   │
│  activity.value      │        │  thread=thread_abc123 │
│                      │        │                       │
│  Bot posts:          │        │  SSE stream reads     │
│  "View in AIOps →    │        │  same Foundry thread  │
│   [link with         │        │  — both surfaces show │
│    thread_id]"       │        │  same conversation    │
└──────────────────────┘        └──────────────────────┘
                  Both share: Foundry thread_abc123
                  Single source of truth for conversation state
```

---

## 7. Cross-Subscription Auth Flow

### 7.1 Identity Architecture

```
Entra ID Tenant (single)
│
├── Managed Identities (Entra Agent IDs — system-assigned via Container Apps)
│   ├── aiops-compute-agent     → principal ID: uuid-compute
│   ├── aiops-network-agent     → principal ID: uuid-network
│   ├── aiops-storage-agent     → principal ID: uuid-storage
│   ├── aiops-security-agent    → principal ID: uuid-security
│   ├── aiops-arc-agent         → principal ID: uuid-arc
│   ├── aiops-sre-agent         → principal ID: uuid-sre
│   └── aiops-orchestrator      → principal ID: uuid-orch
│
└── App Registration (web UI)
    └── aiops-web-ui             → OAuth2 PKCE flow for browser users
        ├── Redirect: https://aiops.internal/auth/callback
        └── Scopes: api://aiops-web-ui/incidents.read
                    api://aiops-web-ui/approvals.write
```

### 7.2 Cross-Subscription RBAC Pattern

```
Subscription: platform (AI Foundry, Container Apps)
│
├── Resource Group: rg-aiops-platform
│   └── Container Apps: agents run here
│       └── Each app gets system-assigned managed identity

Subscription: compute
│
├── Role Assignment: VM Contributor
│   ├── Principal: aiops-compute-agent (uuid-compute)
│   └── Scope: /subscriptions/sub-compute
│
├── Role Assignment: Monitoring Reader
│   ├── Principal: aiops-compute-agent
│   └── Scope: /subscriptions/sub-compute

Subscription: network
│
├── Role Assignment: Network Contributor
│   ├── Principal: aiops-network-agent (uuid-network)
│   └── Scope: /subscriptions/sub-network

Subscription: arc
│
├── Role Assignment: Azure Connected Machine Contributor
│   ├── Principal: aiops-arc-agent (uuid-arc)
│   └── Scope: /subscriptions/sub-arc
│
├── Role Assignment: Kubernetes Extension Contributor
│   ├── Principal: aiops-arc-agent
│   └── Scope: /subscriptions/sub-arc
```

**Terraform RBAC module (azurerm):**

```hcl
# terraform/modules/rbac/main.tf
variable "role_assignments" {
  type = list(object({
    principal_id         = string
    role_definition_name = string
    scope                = string
  }))
}

resource "azurerm_role_assignment" "agent_rbac" {
  for_each             = { for ra in var.role_assignments : "${ra.principal_id}-${ra.role_definition_name}-${md5(ra.scope)}" => ra }
  principal_id         = each.value.principal_id
  role_definition_name = each.value.role_definition_name
  scope                = each.value.scope
}
```

### 7.3 MSAL User Auth (Web UI)

```typescript
// lib/auth/msal.ts
import { PublicClientApplication } from '@azure/msal-browser';

export const msalConfig = {
  auth: {
    clientId: process.env.NEXT_PUBLIC_AZURE_CLIENT_ID!,
    authority: `https://login.microsoftonline.com/${process.env.NEXT_PUBLIC_TENANT_ID}`,
    redirectUri: process.env.NEXT_PUBLIC_REDIRECT_URI!,
  },
  cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
};

// Token acquisition for API calls
export async function getApiToken(): Promise<string> {
  const result = await msalInstance.acquireTokenSilent({
    scopes: ['api://aiops-web-ui/incidents.read'],
    account: msalInstance.getAllAccounts()[0],
  });
  return result.accessToken;
}
```

### 7.4 Managed Identity Resolution in Container Apps

```
Container App (compute-agent)
│
├── system-assigned identity enabled in Terraform
│   └── azurerm_container_app.identity.type = "SystemAssigned"
│
├── AZURE_CLIENT_ID env var injected automatically by Container Apps runtime
│
└── DefaultAzureCredential() resolution order:
    1. AZURE_CLIENT_ID env (ManagedIdentityCredential)
       └── calls IMDS: http://169.254.169.254/metadata/identity/oauth2/token
    2. Falls back to WorkloadIdentityCredential (if federated)
    3. (local dev) AzureCliCredential

# Cross-subscription token acquisition — no extra config needed:
# DefaultAzureCredential works across subscriptions as long as
# the managed identity principal has RBAC on the target subscription.
# Resource manager tokens are tenant-scoped, not subscription-scoped.
```

---

## 8. Custom Arc MCP Server Design

### 8.1 FastMCP Server Structure

```
mcp-servers/arc/
├── Dockerfile
├── pyproject.toml               # mcp[cli]==1.26.0
├── server.py                    # FastMCP entry point
├── tools/
│   ├── __init__.py
│   ├── arc_servers.py           # Arc-enabled servers
│   ├── arc_k8s.py               # Arc-enabled Kubernetes
│   └── arc_data.py              # Arc Data Services
├── auth/
│   └── credential.py            # Managed identity passthrough
├── models/
│   └── responses.py             # Pydantic response models
└── requirements.txt
```

### 8.2 FastMCP Server Definition

```python
# mcp-servers/arc/server.py
from mcp.server.fastmcp import FastMCP
from azure.identity import DefaultAzureCredential
from azure.mgmt.hybridcompute import HybridComputeManagementClient
from azure.mgmt.hybridcontainerservice import HybridContainerServiceClient
from tools.arc_servers import register_arc_server_tools
from tools.arc_k8s import register_arc_k8s_tools
from tools.arc_data import register_arc_data_tools

mcp = FastMCP(
    name="arc-mcp-server",
    version="1.0.0",
    description="Azure Arc management tools for AIOps agents",
)

credential = DefaultAzureCredential()

register_arc_server_tools(mcp, credential)
register_arc_k8s_tools(mcp, credential)
register_arc_data_tools(mcp, credential)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")   # Container App HTTP mode
```

### 8.3 Tools Exposed

**Arc Servers (`tools/arc_servers.py`):**

```python
# tools/arc_servers.py
from mcp.server.fastmcp import FastMCP
from azure.mgmt.hybridcompute import HybridComputeManagementClient
from typing import Optional

def register_arc_server_tools(mcp: FastMCP, credential):

    @mcp.tool()
    def arc_servers_list(subscription_id: str, resource_group: Optional[str] = None) -> list[dict]:
        """List all Arc-enabled servers in a subscription or resource group."""
        client = HybridComputeManagementClient(credential, subscription_id)
        if resource_group:
            machines = client.machines.list_by_resource_group(resource_group)
        else:
            machines = client.machines.list_by_subscription()
        return [{"name": m.name, "status": m.status, "os": m.os_name,
                 "location": m.location, "id": m.id} for m in machines]

    @mcp.tool()
    def arc_server_connect(resource_id: str) -> dict:
        """Get detailed connection status and agent version for an Arc server."""
        # Parse subscription from resource_id
        parts = resource_id.split("/")
        sub_id = parts[2]; rg = parts[4]; name = parts[8]
        client = HybridComputeManagementClient(credential, sub_id)
        machine = client.machines.get(rg, name)
        return {
            "status": machine.status,
            "agent_version": machine.agent_version,
            "last_status_change": str(machine.last_status_change),
            "extensions": [e.name for e in client.machine_extensions.list(rg, name)],
        }

    @mcp.tool()
    def arc_server_extensions_list(resource_id: str) -> list[dict]:
        """List installed extensions on an Arc-enabled server."""
        parts = resource_id.split("/")
        sub_id = parts[2]; rg = parts[4]; name = parts[8]
        client = HybridComputeManagementClient(credential, sub_id)
        return [{"name": e.name, "type": e.type_properties_type,
                 "status": e.provisioning_state, "version": e.type_handler_version}
                for e in client.machine_extensions.list(rg, name)]

    @mcp.tool()
    def arc_server_policies_list(resource_id: str) -> list[dict]:
        """List Azure Policy compliance state for an Arc-enabled server."""
        from azure.mgmt.policyinsights import PolicyInsightsClient
        parts = resource_id.split("/")
        sub_id = parts[2]
        policy_client = PolicyInsightsClient(credential, sub_id)
        results = policy_client.policy_states.list_query_results_for_resource(
            "latest", resource_id
        )
        return [{"policy": r.policy_definition_name, "state": r.compliance_state,
                 "timestamp": str(r.timestamp)} for r in results]
```

**Arc Kubernetes (`tools/arc_k8s.py`):**

```python
# tools/arc_k8s.py
from azure.mgmt.hybridkubernetes import ConnectedKubernetesClient
from azure.mgmt.kubernetesconfiguration import SourceControlConfigurationClient

def register_arc_k8s_tools(mcp: FastMCP, credential):

    @mcp.tool()
    def arc_k8s_clusters_list(subscription_id: str) -> list[dict]:
        """List all Arc-enabled Kubernetes clusters."""
        client = ConnectedKubernetesClient(credential, subscription_id)
        return [{"name": c.name, "connectivity": c.connectivity_status,
                 "k8s_version": c.kubernetes_version, "agent_version": c.agent_version,
                 "id": c.id} for c in client.connected_cluster.list_by_subscription()]

    @mcp.tool()
    def arc_k8s_gitops_status(cluster_resource_id: str) -> list[dict]:
        """Get GitOps/Flux configuration status for an Arc K8s cluster."""
        parts = cluster_resource_id.split("/")
        sub_id = parts[2]; rg = parts[4]; name = parts[8]
        client = SourceControlConfigurationClient(credential, sub_id)
        configs = client.flux_configurations.list(rg, "connectedClusters", name, "")
        return [{"name": c.name, "source_url": c.source_kind,
                 "compliance_state": c.compliance_state,
                 "last_applied": str(c.statuses[0].applied_by.at if c.statuses else None)}
                for c in configs]

    @mcp.tool()
    def arc_k8s_extensions_list(cluster_resource_id: str) -> list[dict]:
        """List Helm extensions installed on an Arc K8s cluster."""
        parts = cluster_resource_id.split("/")
        sub_id = parts[2]; rg = parts[4]; name = parts[8]
        client = SourceControlConfigurationClient(credential, sub_id)
        return [{"name": e.name, "type": e.extension_type,
                 "version": e.version, "status": e.provisioning_state}
                for e in client.extensions.list(rg, "connectedClusters", name, "")]
```

**Arc Data (`tools/arc_data.py`):**

```python
# tools/arc_data.py
from azure.mgmt.azurearcdata import AzureArcDataManagementClient

def register_arc_data_tools(mcp: FastMCP, credential):

    @mcp.tool()
    def arc_data_sqlmi_list(subscription_id: str) -> list[dict]:
        """List Arc-enabled SQL Managed Instances."""
        client = AzureArcDataManagementClient(credential, subscription_id)
        return [{"name": i.name, "state": i.properties.provisioning_state,
                 "tier": i.sku.tier, "id": i.id}
                for i in client.sql_managed_instances.list_by_subscription()]

    @mcp.tool()
    def arc_data_postgres_list(subscription_id: str) -> list[dict]:
        """List Arc-enabled PostgreSQL instances."""
        client = AzureArcDataManagementClient(credential, subscription_id)
        return [{"name": p.name, "state": p.properties.provisioning_state,
                 "workers": p.properties.worker_nodes_count, "id": p.id}
                for p in client.postgres_instances.list_by_subscription()]
```

### 8.4 Deployment as Container App

```
Container App: arc-mcp-server
├── Ingress: internal only (no public endpoint)
│   └── Port: 8080 (streamable-http transport)
│   └── Accessible only from agent Container Apps via internal VNet
│
├── Identity: system-assigned managed identity (aiops-arc-agent-id)
│   └── RBAC: Azure Connected Machine Contributor, Kubernetes Extension Contributor
│
├── Scale: min 1, max 3 replicas
│   └── KEDA: HTTP trigger on request queue
│
└── Environment variables:
    └── AZURE_CLIENT_ID (injected by Container Apps runtime)
```

**MCP tool registration in Arc agent:**

```python
# agents/arc/agent.py
from azure.ai.projects.models import McpTool

arc_mcp_tool = McpTool(
    server_label="arc-mcp",
    server_url=os.environ["ARC_MCP_SERVER_URL"],   # internal Container App FQDN
    allowed_tools=[
        "arc_servers_list", "arc_server_connect", "arc_server_extensions_list",
        "arc_server_policies_list", "arc_k8s_clusters_list", "arc_k8s_gitops_status",
        "arc_k8s_extensions_list", "arc_data_sqlmi_list", "arc_data_postgres_list",
    ],
)
```

---

## 9. Data Flow Architecture

### 9.1 Request Flow (User → Response)

```
User (browser)
    │
    │  1. MSAL token acquired (PKCE)
    │  POST /api/v1/chat  { message, incident_id }
    ▼
Next.js API Route Handler (Container App: web-frontend)
    │
    │  2. Validate JWT (Entra)
    │  3. POST to api-gateway
    ▼
API Gateway (Container App: api-gateway)
    │
    │  4. Auth: validate Entra token
    │  5. Rate limit check (Redis / Cosmos)
    │  6. Create or resume Foundry thread
    │  7. Return { thread_id }
    ▼
Azure AI Foundry — Responses API
    │
    │  8. Route to Orchestrator Hosted Agent
    ▼
Orchestrator Agent
    │
    │  9. Classify domain, handoff
    ▼
Domain Agent (e.g., Compute)
    │
    │  10. Call MCP tool
    ▼
Azure MCP Server / Arc MCP Server
    │
    │  11. Managed identity → Azure REST API
    ▼
Azure Resource (e.g., VM API)
    │
    │  12. Response → MCP → Agent → token stream
    ▼
Foundry Thread (SSE output)
    │
    │  13. SSE: event:token + event:trace multiplexed
    ▼
Next.js SSE Route Handler  (/api/stream)
    │
    │  14. Forward SSE to browser
    ▼
Browser — Fluent UI 2 components update in real-time
```

### 9.2 Audit Flow

```
Agent action executed
    │
    │  OpenTelemetry SDK (in agent container)
    │  span: { agent, tool, action_id, resource_id, outcome, duration_ms }
    ▼
┌──────────────────────────────────────────────────┐
│  OpenTelemetry Collector (sidecar / Container App)│
└──────────────┬───────────────────────────────────┘
               │
    ┌──────────┴────────────┐
    ▼                       ▼
App Insights            Fabric OneLake
(real-time traces,      (long-term audit log,
 query via KQL in       compliance, cross-agent
 Log Analytics)         correlation analytics)
```

**OTel span enrichment:**

```python
# lib/telemetry.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

tracer = trace.get_tracer("aiops.agent")

def instrument_tool_call(agent: str, tool: str, args: dict, action_id: str):
    with tracer.start_as_current_span(f"{agent}.{tool}") as span:
        span.set_attribute("aiops.agent", agent)
        span.set_attribute("aiops.tool", tool)
        span.set_attribute("aiops.action_id", action_id)
        span.set_attribute("aiops.resource_ids", str(args.get("resource_ids", [])))
        # execution happens inside this context
        yield span
```

### 9.3 Telemetry Flow

```
Azure Monitor Metrics + Logs
    │
    │  Diagnostic Settings → streaming export
    ▼
Event Hub (aiops-eventhub-ns/raw-telemetry)
    │
    │  Fabric Eventhouse connector (continuous ingest)
    ▼
Fabric Eventhouse
    ├── Table: RawMetrics       (VM CPU, memory, disk IOPS, network bytes)
    ├── Table: RawLogs          (security events, app logs, diagnostic logs)
    ├── Table: RawAlerts        (Azure Monitor alert firings)
    └── Table: DetectionResults (output of KQL detection rules → triggers Activator)
```

---

## 10. Terraform Module Structure

```
terraform/
├── main.tf                      # Root module — compose all child modules
├── variables.tf
├── outputs.tf
├── versions.tf                  # azurerm ~>4.65, azapi ~>2.9, required providers
│
├── modules/
│   │
│   ├── foundry/                 # ★ REQUIRES azapi (no azurerm support)
│   │   ├── main.tf              # azapi_resource: AIFoundry workspace
│   │   │                        # azapi_resource: AIFoundry project
│   │   │                        # azapi_resource: Model deployments (gpt-4o)
│   │   │                        # azapi_resource: Hosted Agent definitions
│   │   ├── variables.tf
│   │   └── outputs.tf           # workspace_id, project_id, agent_ids{}
│   │
│   ├── container-apps/          # azurerm (CA env) + azapi (CA jobs, newer features)
│   │   ├── main.tf              # azurerm_container_app_environment
│   │   │                        # azurerm_container_app (web, api-gateway, teams-bot)
│   │   │                        # azapi_resource: arc-mcp-server (streamable-http)
│   │   ├── variables.tf
│   │   └── outputs.tf           # app FQDNs, identity principal_ids{}
│   │
│   ├── fabric/                  # ★ REQUIRES azapi (Fabric not in azurerm)
│   │   ├── main.tf              # azapi_resource: Fabric capacity
│   │   │                        # azapi_resource: Eventhouse + KQL database
│   │   │                        # azapi_resource: Activator workspace
│   │   │                        # azapi_resource: OneLake lakehouse
│   │   ├── variables.tf
│   │   └── outputs.tf           # eventhouse_uri, kql_database_name
│   │
│   ├── cosmos/                  # azurerm
│   │   ├── main.tf              # azurerm_cosmosdb_account (serverless, multi-region)
│   │   │                        # azurerm_cosmosdb_sql_database
│   │   │                        # azurerm_cosmosdb_sql_container: incidents, approvals
│   │   ├── variables.tf
│   │   └── outputs.tf
│   │
│   ├── postgres/                # azurerm
│   │   ├── main.tf              # azurerm_postgresql_flexible_server
│   │   │                        # azurerm_postgresql_flexible_server_configuration
│   │   │                        # null_resource: psql "CREATE EXTENSION pgvector"
│   │   ├── variables.tf
│   │   └── outputs.tf           # connection_string (Key Vault reference)
│   │
│   ├── networking/              # azurerm
│   │   ├── main.tf              # azurerm_virtual_network
│   │   │                        # azurerm_subnet (per service: aca, cosmos, postgres, etc.)
│   │   │                        # azurerm_private_endpoint (Cosmos, Postgres, ACR, KV)
│   │   │                        # azurerm_private_dns_zone + vnet links
│   │   ├── variables.tf
│   │   └── outputs.tf           # subnet_ids{}, private_endpoint_ips{}
│   │
│   ├── agent-identities/        # ★ REQUIRES azapi (Entra Agent ID = new resource type)
│   │   ├── main.tf              # azapi_resource: Microsoft.App/managedEnvironments
│   │   │                        #   identity block per domain agent
│   │   │                        # Output principal_ids for rbac module
│   │   ├── variables.tf
│   │   └── outputs.tf           # principal_ids{ compute, network, storage, ... }
│   │
│   ├── rbac/                    # azurerm
│   │   ├── main.tf              # azurerm_role_assignment (cross-subscription)
│   │   │                        # Parameterized list of { principal, role, scope }
│   │   │                        # Depends on: agent-identities outputs
│   │   ├── variables.tf         # role_assignments = list(object)
│   │   └── outputs.tf
│   │
│   └── monitoring/              # azurerm
│       ├── main.tf              # azurerm_log_analytics_workspace
│       │                        # azurerm_application_insights
│       │                        # azurerm_monitor_action_group (→ Event Hub)
│       │                        # azurerm_eventhub_namespace + eventhub
│       │                        # azurerm_monitor_diagnostic_setting (per resource)
│       ├── variables.tf
│       └── outputs.tf           # app_insights_connection_string, eventhub_endpoint
│
└── environments/
    ├── dev/
    │   ├── main.tf              # module composition with dev vars
    │   ├── terraform.tfvars
    │   └── backend.tf           # azurerm backend: dev state container
    ├── staging/
    │   ├── main.tf
    │   ├── terraform.tfvars
    │   └── backend.tf
    └── prod/
        ├── main.tf
        ├── terraform.tfvars
        └── backend.tf
```

**Module dependency summary:**

| Module | Provider | Depends On |
|---|---|---|
| `networking` | azurerm | — |
| `monitoring` | azurerm | networking |
| `agent-identities` | **azapi** | container-apps env |
| `foundry` | **azapi** | networking, monitoring |
| `container-apps` | azurerm + azapi | networking, foundry (ACR endpoint) |
| `fabric` | **azapi** | monitoring (Event Hub) |
| `cosmos` | azurerm | networking |
| `postgres` | azurerm | networking |
| `rbac` | azurerm | agent-identities (principal IDs) |

**Why azapi for Foundry, Fabric, agent-identities:**
- `Microsoft.MachineLearningServices/workspaces` Foundry variant uses `kind: Hub/Project` not yet in azurerm
- Fabric resources (`Microsoft.Fabric/*`) have no azurerm provider coverage
- Entra Agent ID resource type (`Microsoft.App/containerApps` identity extensions) uses preview API versions not yet surfaced in azurerm

---

## 11. Build Order (Critical Path)

The Arc MCP Server is the **longest pole** because it requires: Arc API research + SDK wrapping + FastMCP integration + auth passthrough + Container App deployment + agent integration testing. It gates the ArcAgent, which gates full incident routing.

```
Phase 0: Foundation (Week 1) — ALL parallel
┌─────────────────────────────────────────────────────────────────────┐
│  P0-A: Terraform networking + monitoring (azurerm)                  │
│         → VNet, subnets, private endpoints, Event Hub, App Insights  │
│                                                                     │
│  P0-B: Entra App Registration (web UI) + MSAL config               │
│         → Client ID, redirect URIs, API scopes defined              │
│                                                                     │
│  P0-C: Azure Container Registry provisioned                        │
│         → ACR ready for agent image pushes                          │
└─────────────────────────────────────────────────────────────────────┘
         All P0 must complete before P1

Phase 1: Core Infrastructure (Week 1-2) — parallel tracks
┌─────────────────────────────────────┐  ┌─────────────────────────────┐
│  P1-A: Foundry workspace + project  │  │  P1-B: Cosmos DB + Postgres │
│         (azapi)                     │  │         (azurerm)            │
│         → Model deployment (gpt-4o) │  │         → pgvector extension │
│         → Hosted Agent slots        │  │         → schemas applied    │
│         → Thread API enabled        │  │                              │
└─────────────────────────────────────┘  └─────────────────────────────┘

         P1-A must complete before P2 (agents need Foundry)
         P1-B must complete before P2 (agents write to Cosmos)

Phase 2: Agent Identities + RBAC (Week 2) — sequential within
┌─────────────────────────────────────────────────────────────────────┐
│  P2-A: agent-identities module (azapi)                              │
│         → 7 managed identities provisioned, principal IDs captured  │
│                          ↓                                          │
│  P2-B: rbac module (azurerm)                                        │
│         → Cross-subscription role assignments applied               │
│         → Verify with: az role assignment list --assignee {id}      │
└─────────────────────────────────────────────────────────────────────┘
         Must complete before P3 (agents can't call Azure APIs without RBAC)

Phase 3: MCP Servers (Week 2-3) — parallel but Arc is longest pole
┌─────────────────────────────────────┐  ┌─────────────────────────────┐
│  P3-A: Azure MCP Server (msmcp-azure│  │  ★ P3-B: Arc MCP Server     │
│         GA) validation              │  │    (FastMCP — LONGEST POLE) │
│         → Confirm tool coverage     │  │                              │
│         → Test with dev Foundry     │  │  Week 2: Arc SDK research    │
│           agent                     │  │  Week 2: arc_servers tools   │
│         → 2-3 days                  │  │  Week 3: arc_k8s tools       │
│                                     │  │  Week 3: arc_data tools      │
│                                     │  │  Week 3: auth passthrough    │
│                                     │  │  Week 3: Container App deploy│
│                                     │  │  Week 3: integration tests   │
└─────────────────────────────────────┘  └─────────────────────────────┘
         P3-A gates ComputeAgent, NetworkAgent, StorageAgent, SecurityAgent, SREAgent
         P3-B gates ArcAgent exclusively — do not block other agents on Arc MCP

Phase 4: Domain Agents (Week 3-4) — Arc agent last due to P3-B dependency
┌──────────────────────────────────────────────────────────────────────┐
│  P4-A (Week 3): Orchestrator + Compute + Network agents              │
│         → Uses Azure MCP Server (GA, available from P3-A)           │
│         → HandoffOrchestrator wired up                              │
│         → Unit tests + message contract validation                  │
│                                                                      │
│  P4-B (Week 3): Storage + Security + SRE agents                     │
│         → Parallel with P4-A                                        │
│                                                                      │
│  P4-C (Week 4): Arc Agent                                            │
│         → Blocked on P3-B (Arc MCP Server) completion               │
│         → Arc-specific tool wiring + Foundry registration           │
└──────────────────────────────────────────────────────────────────────┘

Phase 5: Detection Pipeline (Week 3-4) — parallel with P4
┌──────────────────────────────────────────────────────────────────────┐
│  P5-A: Fabric Eventhouse + Activator (azapi)                        │
│         → KQL tables, update policies, detection rules              │
│  P5-B: Azure Monitor Action Groups → Event Hub wiring               │
│  P5-C: Power Automate flow / User Data Function                     │
│         → REST POST to api-gateway on trigger                       │
└──────────────────────────────────────────────────────────────────────┘
         Must complete before system E2E testing (Phase 7)

Phase 6: UI Layer (Week 4-5) — parallel with P4 + P5
┌─────────────────────────────────────┐  ┌─────────────────────────────┐
│  P6-A: Next.js App Router           │  │  P6-B: Teams Bot            │
│         → SSE Route Handler         │  │  → @microsoft/teams.js      │
│         → Fluent UI 2 components    │  │  → Adaptive Card builder    │
│         → MSAL integration          │  │  → Approval webhook handler │
│         → Dual SSE rendering        │  │  → Thread ID sync           │
└─────────────────────────────────────┘  └─────────────────────────────┘

Phase 7: Integration + E2E (Week 5-6)
┌──────────────────────────────────────────────────────────────────────┐
│  P7-A: API Gateway Container App + Container Apps environment        │
│  P7-B: End-to-end incident flow test (Playwright)                   │
│         → Inject synthetic alert → Eventhouse → Activator            │
│            → api-gateway → Orchestrator → Domain Agent               │
│            → SSE stream → UI renders correctly                       │
│  P7-C: Teams approval flow E2E test                                  │
│  P7-D: Cross-subscription auth validation per domain agent          │
│  P7-E: HITL approval gate test (approve + reject paths)             │
└──────────────────────────────────────────────────────────────────────┘

Phase 8: Hardening + Prod Deploy (Week 6)
┌──────────────────────────────────────────────────────────────────────┐
│  P8-A: Security review (all managed identities, no secrets in code)  │
│  P8-B: Terraform prod environment apply                              │
│  P8-C: Playwright E2E suite in CI (GitHub Actions)                  │
│  P8-D: Load test SSE streaming under concurrent incidents            │
└──────────────────────────────────────────────────────────────────────┘

Critical Path (gates everything):
  networking → foundry → agent-identities → rbac → [Arc MCP Server]
                                                        → Arc Agent
                                                        → E2E tests
                                                        → prod deploy

Why Arc MCP Server is the longest pole:
  1. No official SDK for arc-data, arc-k8s in one client — must compose 3 SDKs
  2. FastMCP streamable-http transport requires testing in Container Apps
  3. Managed identity passthrough needs validation across 3 Arc resource types
  4. Arc resources span multiple subscriptions — RBAC complexity highest here
  5. GitOps/Flux status requires azure-mgmt-kubernetesconfiguration with preview API
  6. Integration testing requires actual Arc-onboarded resources (can't mock easily)
```

---

## 12. Resource Identity Certainty Protocol

> Source: Adapted from microsoftgbb/agentic-platform-engineering Cluster Doctor "Cluster Identity Certainty" pattern. Generalizes the "Approve-Then-Stale" pitfall (PITFALLS.md Section 10) into a formal, mandatory pre-execution protocol.

### 12.1 Principle

Before any remediation execution, the agent MUST verify that the target resource state matches the triage snapshot using at least two independent signals. This prevents acting on stale approvals where the resource has changed since the operator approved the action.

### 12.2 Verification Signals (minimum 2 required)

1. **Resource ID match** — The ARM resource ID in the remediation action matches the incident record exactly.
2. **Resource state hash** — A hash of critical resource properties (tags, provisioning state, configuration) taken at triage time is compared against a fresh read. Divergence beyond a configurable threshold triggers an abort.
3. **Subscription/resource group stability** — The resource's subscription and resource group haven't been deleted, moved, or renamed since triage.

### 12.3 Pre-Execution Check Flow

```
Agent receives approved remediation action
    │
    ▼
Re-read resource via Azure MCP / Arc MCP
    │
    ▼
Compare resource state hash against triage snapshot
    │
    ├── Hash matches ──────────────► Proceed with execution
    │                                    │
    │                                    ▼
    │                              Execute remediation tool
    │                                    │
    │                                    ▼
    │                              Log outcome + audit trail
    │
    └── Hash diverged ─────────────► Abort execution
                                         │
                                         ▼
                                    Notify operator:
                                    "Resource state changed since approval.
                                     Original state: {snapshot}
                                     Current state: {current}
                                     Please re-triage and re-approve."
                                         │
                                         ▼
                                    Update incident record in Cosmos DB
                                    with STALE_APPROVAL status
```

### 12.4 Implementation Notes

- The state hash should cover: `provisioning_state`, `tags`, `sku`, `location`, and resource-type-specific critical fields (e.g., `power_state` for VMs, `replica_count` for deployments).
- Hash comparison uses a configurable divergence threshold — some fields (like `last_modified_timestamp`) are expected to change and should be excluded.
- The pre-execution check is a read-only operation and does not require additional RBAC beyond what the agent already has for triage.
- Approval TTL (default: 15 minutes for destructive actions) provides a time-based backstop in addition to the state-based check.

---

## 13. Agent Specification Format

> Source: Adapted from microsoftgbb/agentic-platform-engineering Cluster Doctor agent definition pattern (`.github/agents/cluster-doctor.agent.md`). Extended for AAP's multi-agent, multi-domain architecture.

### 13.1 Purpose

Every domain agent MUST have a human-readable specification document written before agent code. These specs serve as:

- **Design artifacts** — Stakeholders review agent behavior before implementation begins.
- **Version-controlled contracts** — Git history shows how agent scope and behavior evolve.
- **Onboarding documentation** — New team members understand agent capabilities from the spec, not the code.
- **RBAC validation source** — The Permission Model section defines the expected RBAC scope, which Terraform modules enforce.

### 13.2 Specification Location

```
docs/agents/{domain}-agent.spec.md
```

One spec per domain agent: `compute-agent.spec.md`, `network-agent.spec.md`, `storage-agent.spec.md`, `security-agent.spec.md`, `arc-agent.spec.md`, `sre-agent.spec.md`, `orchestrator-agent.spec.md`.

### 13.3 Template Sections

Each agent specification document MUST contain the following sections (derived from the GBB Cluster Doctor format, extended for enterprise AIOps):

| Section | Description |
|---|---|
| **Persona & Expertise** | Role definition, domain expertise, communication style (e.g., "Senior Azure Compute Engineer specializing in VM performance and availability") |
| **Goals & Success Criteria** | What the agent is trying to achieve and how success is measured (e.g., "Reduce MTTR for VM-related incidents by 60%") |
| **Workflow Phases** | Ordered phases: Collect → Verify → Diagnose → Triage → Remediate. Each phase defines inputs, outputs, and exit criteria. |
| **Tool Access** | Explicit list of MCP tools and Azure APIs the agent may invoke. No wildcards — every tool is named. |
| **Permission Model** | RBAC scope (subscriptions, resource groups, roles). Read-only vs read-write boundaries. Maps to Terraform `rbac` module. |
| **Safety Constraints** | Resource Identity Certainty protocol adherence, max blast radius, forbidden actions, rate limits. |
| **Example Diagnostic Flows** | 2-3 concrete scenarios with step-by-step agent reasoning and tool calls. |
| **Handoff Conditions** | When and why this agent escalates to the Orchestrator or another domain agent. Includes cross-domain trigger patterns. |

### 13.4 Lifecycle

1. **Draft** — Written during Phase 2 (Agent Core) before any agent code.
2. **Review** — Team reviews via PR; stakeholders validate scope and safety constraints.
3. **Approved** — Spec is merged; agent implementation may begin.
4. **Updated** — Spec evolves with agent capabilities; each change is a PR with rationale.

---

## 14. GitOps Remediation Path for Arc K8s

> Source: Inspired by microsoftgbb/agentic-platform-engineering ArgoCD → GitHub Issue → PR pattern. Adapted for AAP's Flux/GitOps-managed Arc Kubernetes clusters.

### 14.1 Dual Remediation Path

Arc Kubernetes resources managed by Flux/GitOps require a different remediation strategy than direct Azure API calls. The agent must classify the root cause and choose the appropriate remediation path automatically.

| Root Cause Type | Remediation Path | Example |
|---|---|---|
| **Manifest drift** (wrong resource limits, bad config, incorrect image tag) | Create a PR against the GitOps repository | Pod OOMKilled due to memory limit set too low in deployment manifest |
| **Infrastructure issue** (node down, disk full, network unreachable) | Direct remediation via Arc MCP Server tools | Arc K8s node NotReady due to kubelet crash; requires node drain + restart |

### 14.2 Decision Flow

```
Agent diagnosis complete
    │
    ▼
Classify root_cause_type from diagnosis result
    │
    ├── root_cause_type == "manifest_drift"
    │       │
    │       ▼
    │   Identify affected GitOps repo + file path
    │   (from Flux kustomization source reference)
    │       │
    │       ▼
    │   Generate fix (updated YAML manifest)
    │       │
    │       ▼
    │   Create PR against GitOps repo via GitHub API
    │   (branch: aiops/fix-{incident_id}, title: remediation summary)
    │       │
    │       ▼
    │   Post PR link to incident record + notify operator
    │   "PR created: {url}. Flux will reconcile on merge."
    │
    └── root_cause_type == "infra_issue"
            │
            ▼
        Propose direct remediation action
        (standard approval workflow — Section 2.4)
            │
            ▼
        Human approves → execute via Arc MCP Server
```

### 14.3 GitOps PR Template

When the agent creates a PR for manifest remediation:

- **Branch name**: `aiops/fix-{incident_id}-{short_description}`
- **PR title**: `[AAP] {remediation_summary}`
- **PR body**:
  - Incident reference (link to AAP incident view)
  - Root cause analysis summary
  - Change description (what was modified and why)
  - Test plan (how to verify the fix after Flux reconciliation)
  - Rollback instructions (`git revert` the PR commit)

### 14.4 Scope & Constraints

- GitOps remediation is **Phase 2+** — MVP uses direct remediation only.
- The agent requires a GitHub PAT or GitHub App credential (stored in Key Vault) to create PRs. This is a separate credential from Azure managed identity.
- Only Flux-managed clusters are eligible; the agent checks for Flux kustomization presence via `arc_k8s_gitops_status` tool before attempting GitOps remediation.
- The agent NEVER pushes directly to the default branch — always creates a feature branch for human review.

---

## Appendix: Key Package Versions

| Package | Version | Usage |
|---|---|---|
| `agent-framework` | `1.0.0rc5` | Multi-agent orchestration, HandoffOrchestrator |
| `azure-ai-projects` | latest GA | AzureAIAgentClient, Foundry Responses API |
| `mcp[cli]` | `1.26.0` | Arc MCP Server (FastMCP) |
| `msmcp-azure` | GA | Azure MCP Server (managed, no deployment needed) |
| `@microsoft/teams.js` | latest | Teams bot, Adaptive Cards |
| `azurerm` | `~>4.65` | Core Azure Terraform provider |
| `azapi` | `~>2.9` | Foundry, Fabric, Entra Agent ID resources |
| `@azure/msal-browser` | latest | User auth (PKCE) in Next.js |
| `opentelemetry-sdk` | latest | Agent action tracing → App Insights + OneLake |
| `@fluentui/react-components` | v9 (Fluent UI 2) | UI component library |

## Appendix: Environment Variables Per Agent Container

```bash
# All agents
FOUNDRY_PROJECT_NAME=aiops-foundry-project
FOUNDRY_MODEL_DEPLOYMENT=gpt-4o-2024-11-20
AZURE_SUBSCRIPTION_ID=<platform-sub>
AZURE_RESOURCE_GROUP=rg-aiops-platform
ORCHESTRATOR_AGENT_ID=<from Terraform output>
APPLICATIONINSIGHTS_CONNECTION_STRING=<from Key Vault ref>

# Per-domain agents (example: compute)
FOUNDRY_AGENT_ID=<compute-agent-id from Terraform>
NETWORK_AGENT_ID=<for handoff targeting>
AZURE_CLIENT_ID=<injected by Container Apps runtime>

# Arc agent only
ARC_MCP_SERVER_URL=https://arc-mcp-server.internal.azurecontainerapps.io
```
