# Quick Task 260418-plh: Add AI Chat to Network Topology Tab - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Task Boundary

Add an AI chat panel to the Network Topology tab that lets users ask questions about the
topology. The network domain agent answers. When the agent mentions specific resources,
those nodes are highlighted on the topology map visually.

</domain>

<decisions>
## Implementation Decisions

### Chat Placement & Layout
- Right side panel (resizable), slides in alongside the topology map
- Map shrinks to fill remaining width when chat is open; full width when closed
- Toggle button on the topology tab header to show/hide chat

### Chat Scope & Context
- Chat is context-aware: passes the current subscription IDs and any selected node to the agent
- Agent can answer questions about the rendered topology (e.g. "show me all VMs without NSGs")

### Agent Routing
- Direct to network domain agent (`/api/v1/network/chat` or equivalent)
- No orchestrator hop — keeps latency low and network context focused

### Interactive Topology Highlighting
- When the agent reply mentions resource IDs or names, those nodes are highlighted on the map
- Highlight uses a distinct color (e.g. amber/orange) so selected vs highlighted are distinguishable
- Clicking a highlighted node opens its detail panel as normal
- Highlights clear when a new message is sent

### Claude's Discretion
- Chat history persistence (session-only vs Cosmos) — use session-only (no new infrastructure)
- Streaming vs non-streaming agent responses — use SSE streaming for real-time feel
- How to extract resource IDs from agent replies — regex/heuristic over Azure resource ID patterns
  in the response text (no schema change needed on the agent side)

</decisions>

<specifics>
## Specific Ideas

- Network agent needs a new `/chat` endpoint (or reuse existing `/ask` pattern)
- Agent system prompt should include topology context: subscription IDs, resource counts by type
- Resource ID extraction: scan reply text for `/subscriptions/.../providers/...` patterns and
  ARM short-names (e.g. "vnet-prod-001") that match node IDs in the current topology graph
- Highlight state: new React state `highlightedNodeIds: Set<string>` passed to the D3/force graph
- API proxy route: `app/api/proxy/network/chat/route.ts` → `GET /api/v1/network/chat`

</specifics>

<canonical_refs>
## Canonical References

- Existing chat pattern: `services/web-ui/components/ChatPanel.tsx` — reuse SSE streaming logic
- Network agent: `agents/network/agent.py` — add chat tool or endpoint
- API gateway network router: `services/api-gateway/network_endpoints.py` (or similar)
- Proxy pattern: `services/web-ui/app/api/proxy/*/route.ts`

</canonical_refs>
