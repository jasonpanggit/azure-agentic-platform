# Summary: Add AI Chat to Network Topology Tab

**Task ID:** 260418-plh  
**Status:** ✅ Complete  
**Date:** 2026-04-18

---

## What Was Built

A resizable right-side AI chat panel added to the `NetworkTopologyTab` that routes directly to the network domain agent via a new SSE streaming endpoint. When the agent's reply mentions Azure resource names or IDs that match nodes in the current graph, those nodes are highlighted with an amber/orange ring on the map.

### Features delivered

- **Backend SSE endpoint** — `POST /api/v1/network-topology/chat` streams `data: {"token": "..."}` chunks, terminated by `data: [DONE]`. Session-only conversation history (in-memory, no Cosmos writes). Context-enriched system prompt includes subscription IDs, node/edge counts, and selected node.
- **Next.js SSE proxy route** — `POST /api/proxy/network/chat` — pipes the upstream stream verbatim using the standard `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(120s)` pattern.
- **`useNetworkChat` hook** — encapsulates all chat state, SSE stream parsing, thread ID management, and resource-ref extraction. Pure helper `extractResourceRefs()` scans reply text for ARM IDs (`/subscriptions/.../providers/...`) and short names against a `nodeIndex` map.
- **`NetworkTopologyChatPanel` component** — self-contained chat panel with user/assistant bubbles, quick-start prompts, Textarea + Send button, close button. All styling uses semantic CSS tokens (`var(--accent-blue)`, `var(--bg-surface)`, etc.).
- **Topology tab wiring** — "Ask AI" toggle button in header, flex layout splits map and chat panel (map: `flex: 1 1 0`, chat: `width: 360px`). Amber node highlighting applied in-place via `setNodes` (no re-layout). `NsgNode` extended with `chatHighlighted` prop for amber ring (`var(--accent-orange)`).

---

## Files Changed

| File | Action |
|------|--------|
| `services/api-gateway/network_topology_endpoints.py` | Added `NetworkChatRequest` model, `_stream_network_chat()` async generator, `POST /chat` SSE handler |
| `services/web-ui/app/api/proxy/network/chat/route.ts` | New SSE proxy route |
| `services/web-ui/lib/use-network-chat.ts` | New hook with `extractResourceRefs` helper |
| `services/web-ui/components/NetworkTopologyChatPanel.tsx` | New chat panel component |
| `services/web-ui/components/NetworkTopologyTab.tsx` | Added `MessageSquare` import, `NetworkTopologyChatPanel` import, chat state, `nodeIndex` memo, `topologyContext` memo, "Ask AI" button, flex layout, amber highlight wiring |

---

## Deviations from Plan

- **`onHighlight` uses `setNodes` in-place** (not `computeLayout`) — avoids disruptive graph re-layout on every highlight. Amber styling is applied via `node.style` and `node.data.chatHighlighted` simultaneously so both ReactFlow node styles and the `NsgNode` custom renderer get updated.
- **All non-NSG node types** get amber via the `node.style` outline applied by the `setNodes` updater, since only `NsgNode` had the `highlighted` pattern. This is simpler and covers all node types uniformly.
- **`subscriptionIds` passed as `[]`** from the topology tab (the tab doesn't currently expose subscription state to its children) — the backend falls back to "all" when empty, which is correct behaviour.
