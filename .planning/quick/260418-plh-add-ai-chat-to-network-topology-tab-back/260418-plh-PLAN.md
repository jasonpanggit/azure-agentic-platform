# Plan: Add AI Chat to Network Topology Tab

**Task ID:** 260418-plh  
**Created:** 2026-04-18  
**Status:** Ready to execute

---

## Overview

Add a resizable right-side chat panel to `NetworkTopologyTab` that routes directly to the network domain agent via a new `POST /api/v1/network/chat` endpoint. The agent receives topology context (subscription IDs, node/edge counts, optional selected node) and streams a response via SSE. When the reply mentions Azure resource IDs or names that match nodes in the current graph, those nodes are highlighted in amber on the map. Highlights clear on the next send.

No new Cosmos containers, no orchestrator hop, no scan buttons — session-only chat state in component `useState`.

---

## Tasks

### Task 1 — Backend: `POST /api/v1/network/chat` endpoint

**Files changed:**
- `services/api-gateway/network_topology_endpoints.py` — add `POST /api/v1/network/chat` route
- `services/api-gateway/main.py` (or router include file) — verify router is already included (no change expected)

**What changes:**

Add a new `NetworkChatRequest` Pydantic model:
```python
class NetworkChatRequest(BaseModel):
    message: str
    subscription_ids: list[str] = []
    thread_id: Optional[str] = None          # session-only; client generates UUID on first send
    topology_context: Optional[dict] = None  # {node_count, edge_count, selected_node_id}
```

Add a streaming `POST /api/v1/network/chat` handler that:
1. Builds a context-enriched system message prepended to the user message (subscription IDs, node/edge counts, selected node if present)
2. Forwards to the network agent via the Foundry Agent Service (`azure-ai-projects` `AIProjectClient`) on the agent's thread
3. Streams the response back as `text/event-stream` SSE — each chunk as `data: {"token": "..."}`, terminated by `data: [DONE]`
4. Follows the tool function pattern: `start_time = time.monotonic()`, never raises — returns `data: {"error": "..."}` on failure

**Acceptance criterion:** `curl -N -X POST .../api/v1/network/chat -d '{"message":"list all VNets","subscription_ids":["sub-1"]}' -H 'Content-Type: application/json'` streams token chunks and ends with `[DONE]`.

**Commit:** `feat: add POST /api/v1/network/chat SSE endpoint to network topology router`

---

### Task 2 — Frontend proxy route

**Files changed:**
- `services/web-ui/app/api/proxy/network/chat/route.ts` — new file

**What changes:**

Create a POST proxy route following the established pattern (`getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout`). Because this is SSE, the route must:
- Pass `Accept: text/event-stream` upstream
- Stream the response body back to the client without buffering (`return new Response(res.body, ...)`)
- Set `Content-Type: text/event-stream` on the outgoing response
- Use `export const runtime = 'nodejs'` and `export const dynamic = 'force-dynamic'`

**Acceptance criterion:** A fetch from the browser to `/api/proxy/network/chat` with a valid body streams SSE chunks through to the client.

**Commit:** `feat: add /api/proxy/network/chat SSE proxy route`

---

### Task 3 — `useNetworkChat` hook

**Files changed:**
- `services/web-ui/lib/use-network-chat.ts` — new file

**What changes:**

A focused custom hook encapsulating all chat state and SSE logic for the topology tab:

```typescript
interface ChatMessage { role: 'user' | 'assistant'; content: string; id: string }

interface UseNetworkChatOptions {
  subscriptionIds: string[]
  topologyContext: { nodeCount: number; edgeCount: number; selectedNodeId?: string }
  onHighlight: (nodeIds: Set<string>) => void   // called after each complete assistant reply
  nodeIndex: Map<string, string>                // resourceId/name → node id, built from topology nodes
}

function useNetworkChat(opts: UseNetworkChatOptions): {
  messages: ChatMessage[]
  input: string
  setInput: (v: string) => void
  isStreaming: boolean
  sendMessage: () => void
}
```

Internally:
- Maintains `messages`, `input`, `threadId` (UUID generated on first send, kept for session), `isStreaming`
- On `sendMessage`: appends user bubble immediately, clears `highlightedNodeIds` (via `onHighlight(new Set())`), calls `POST /api/proxy/network/chat`, reads `ReadableStream`, accumulates tokens into the trailing assistant bubble
- After stream ends: runs `extractResourceRefs(replyText, nodeIndex)` (pure helper — regex scan for ARM resource IDs `/subscriptions/.../` and short names against `nodeIndex` keys) and calls `onHighlight(matchedIds)`

**Acceptance criterion:** Hook compiles with no type errors; unit test covers `extractResourceRefs` returning correct IDs for a sample reply.

**Commit:** `feat: add useNetworkChat hook with SSE streaming and resource ref extraction`

---

### Task 4 — `NetworkTopologyChatPanel` component

**Files changed:**
- `services/web-ui/components/NetworkTopologyChatPanel.tsx` — new file

**What changes:**

A self-contained chat panel component that:
- Accepts `{ onHighlight, nodeIndex, subscriptionIds, topologyContext, onClose }` props
- Uses `useNetworkChat` hook
- Renders: message list (user bubbles right-aligned, assistant bubbles left-aligned using semantic CSS tokens), `ChatInput`-style textarea + send button at bottom, `X` close button in header
- Follows CSS token conventions (`var(--bg-surface)`, `var(--text-primary)`, `var(--accent-blue)`, etc.) — no hardcoded Tailwind colors
- No scan buttons, no loading spinners for data fetch (chat is user-initiated)
- Pre-populated quick-start prompts: `"List all VNets"`, `"Which NSGs have open inbound rules?"`, `"Show subnets without NSGs"`, `"Describe VNet peering topology"`

**Acceptance criterion:** Component renders in isolation (Storybook or direct import test) with empty message list and quick prompts visible.

**Commit:** `feat: add NetworkTopologyChatPanel component`

---

### Task 5 — Wire chat panel into `NetworkTopologyTab` with amber highlighting

**Files changed:**
- `services/web-ui/components/NetworkTopologyTab.tsx` — add chat toggle, layout split, `highlightedNodeIds` state, amber node styling

**What changes:**

1. **New state:**
   ```typescript
   const [chatOpen, setChatOpen] = useState(false)
   const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set())
   ```

2. **`nodeIndex` memo** — built from `topologyData.nodes`, maps both `node.id` (full ARM ID) and `node.label` (short name, lowercased) → `node.id`:
   ```typescript
   const nodeIndex = useMemo(() => {
     const m = new Map<string, string>()
     topologyData?.nodes.forEach(n => { m.set(n.id.toLowerCase(), n.id); m.set(n.label.toLowerCase(), n.id) })
     return m
   }, [topologyData])
   ```

3. **Amber highlight applied in nodes** — in `transformToReactFlowNodes` (or via a `setNodes` mutation after topology load), pass `highlighted: highlightedNodeIds.has(n.id)` into each node's `data`. Add amber ring to all custom node components using the existing `data.highlighted` prop pattern (already used for NSG blocking highlight — extend it to amber for chat):
   - Border: `var(--accent-orange)`
   - Box shadow: `0 0 0 4px color-mix(in srgb, var(--accent-orange) 20%, transparent)`

4. **Layout split** — wrap the ReactFlow canvas and `NetworkTopologyChatPanel` in a flex row. When `chatOpen`:
   - Map: `flex: 1 1 0`, `min-width: 0`
   - Chat panel: `width: 360px`, `flex-shrink: 0`
   - Resize handle (thin drag divider) between them using a simple `onMouseDown` resize pattern (same as `useResizable` already used in `ChatDrawer`)

5. **Header toggle button** — add a `MessageSquare` icon button beside the existing Refresh and Path Checker buttons:
   ```tsx
   <Button variant={chatOpen ? 'default' : 'outline'} size="sm" onClick={() => setChatOpen(v => !v)}>
     <MessageSquare size={14} /> Ask AI
   </Button>
   ```

6. **`topologyContext` prop** built from `topologyData` counts + `selectedNode?.id`

**Acceptance criterion:**
- Clicking "Ask AI" opens the panel; map shrinks, full width restored on close
- Sending "list all VNets" highlights vnet nodes with amber ring on the map
- Clearing highlights (new message) removes amber ring

**Commit:** `feat: wire NetworkTopologyChatPanel into topology tab with amber node highlighting`

---

## File Summary

| File | Action |
|------|--------|
| `services/api-gateway/network_topology_endpoints.py` | Add POST `/api/v1/network/chat` SSE handler |
| `services/web-ui/app/api/proxy/network/chat/route.ts` | New SSE proxy route |
| `services/web-ui/lib/use-network-chat.ts` | New hook |
| `services/web-ui/components/NetworkTopologyChatPanel.tsx` | New component |
| `services/web-ui/components/NetworkTopologyTab.tsx` | Wire panel + highlighting |

## Constraints Checklist

- [x] No orchestrator — direct to network agent via Foundry thread
- [x] Session-only chat history — `threadId` in component state only
- [x] SSE streaming — `ReadableStream` proxy, no buffering
- [x] Resource highlighting — regex extraction + `nodeIndex` map, amber ring
- [x] No scan buttons — no `POST /scan`, no `handleScan`, no "Run a scan" copy
- [x] Proxy pattern — `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout`
- [x] CSS tokens — `var(--accent-orange)` for amber, no hardcoded Tailwind colors
