# Phase 103: Network Topology Map — UI Design Contract

**Status:** Approved
**Date:** 2026-04-18

---

## 1. Canvas Layout & Visual Hierarchy

### Overall Structure

```
+-----------------------------------------------------------------------+
| Header bar: icon + "Network Topology" + [Refresh] + [Path Checker]    |
+-----------------------------------------------------------------------+
| Summary pills: VNets: N | NSGs: N | Issues: N (red)                  |
+-----------------------------------------------------------------------+
|                                                                       |
|   React Flow canvas (100% width, calc(100vh - 220px) height)         |
|   Background: var(--bg-canvas)                                        |
|                                                                       |
|   +-----------------------+          +-----------------------+        |
|   | VNet (container node) |---peer---| VNet (container node) |        |
|   |  +-------+ +-------+ |          |  +-------+ +-------+  |        |
|   |  |Subnet | |Subnet | |          |  |Subnet | |Subnet |  |        |
|   |  +--+----+ +---+---+ |          |  +---+---+ +-------+  |        |
|   +-----|----------|------+          +------|----------------+        |
|         |          |                        |                         |
|       [NSG]      [LB]                     [PE]                        |
|                                                                       |
+-----------------------------------------------------------------------+
```

- **Auto-layout:** ELK.js `layered` algorithm, `direction: RIGHT`
- **Zoom/pan:** React Flow built-in controls (bottom-left minimap, zoom buttons)
- **Canvas background:** `var(--bg-canvas)` with React Flow dot grid at `color-mix(in srgb, var(--border) 40%, transparent)`

### Z-Order (back to front)

1. Canvas background + grid
2. Edges (connections)
3. VNet container nodes
4. Subnet nodes (inside VNet containers)
5. Leaf nodes (NSG, LB, PE, Gateway)
6. NSG health badges (overlaid on NSG nodes)
7. Issue highlight edges (red dashed, topmost)

---

## 2. Node Designs

All nodes share a base card style:

```css
/* Base node */
background: var(--bg-surface);
border: 1px solid var(--border);
border-radius: 8px;
font-family: var(--font-sans);
color: var(--text-primary);
```

### 2.1 VNet Container Node

| Property | Value |
|----------|-------|
| **Size** | Auto-sized to contain child subnets; min 280x120 |
| **Border** | `2px solid var(--accent-blue)` |
| **Background** | `color-mix(in srgb, var(--accent-blue) 5%, var(--bg-surface))` |
| **Header** | VNet name (14px semibold) + CIDR badge (12px mono, `var(--text-secondary)`) |
| **Icon** | `Network` (lucide) at 16px, `var(--accent-blue)` |
| **Corner label** | Subscription name (10px, `var(--text-muted)`) |
| **Handles** | Left + right (for peering edges) |

### 2.2 Subnet Node

| Property | Value |
|----------|-------|
| **Size** | 180x56 |
| **Border** | `1px solid var(--border)` |
| **Background** | `var(--bg-surface)` |
| **Label** | Subnet name (12px medium) + CIDR (11px mono, `var(--text-secondary)`) |
| **Handles** | Bottom (for NSG/LB/PE/Gateway connections) |
| **Parent** | Nested inside VNet container via React Flow `parentId` |

### 2.3 NSG Node (with health badge)

| Property | Value |
|----------|-------|
| **Size** | 160x52 |
| **Border** | `1px solid var(--border)` |
| **Background** | `var(--bg-surface)` |
| **Icon** | `Shield` (lucide) at 14px, `var(--text-secondary)` |
| **Label** | NSG name (12px medium) + rule count (11px, `var(--text-muted)`) |
| **Badge** | Health pill — see section 4 |
| **Handles** | Top (connects to subnet) |

**Highlighted state (path checker blocking NSG):**

```css
border: 2px solid var(--accent-red);
box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent-red) 20%, transparent);
```

### 2.4 Load Balancer Node

| Property | Value |
|----------|-------|
| **Size** | 180x60 |
| **Border** | `1px solid var(--border)` |
| **Background** | `var(--bg-surface)` |
| **Icon** | `Scale` (lucide) at 14px, `var(--accent-purple)` |
| **Label** | LB name (12px medium) |
| **Sub-label** | SKU badge (11px, same `color-mix` pattern as LBHealthTab) + public IP if present (11px mono) |
| **Handles** | Top (connects to subnet) |

### 2.5 Private Endpoint Node

| Property | Value |
|----------|-------|
| **Size** | 170x52 |
| **Border** | `1px solid var(--border)` |
| **Background** | `var(--bg-surface)` |
| **Icon** | `Lock` (lucide) at 14px, `var(--accent-purple)` |
| **Label** | PE name (12px medium) |
| **Sub-label** | Target service type (11px, `var(--text-muted)`) |
| **Handles** | Top (connects to subnet) |

### 2.6 Gateway Node (ExpressRoute / VPN)

| Property | Value |
|----------|-------|
| **Size** | 180x60 |
| **Border** | `1px solid var(--accent-orange)` |
| **Background** | `color-mix(in srgb, var(--accent-orange) 5%, var(--bg-surface))` |
| **Icon** | `Globe` (lucide, ExpressRoute) or `Waypoints` (lucide, VPN) at 14px, `var(--accent-orange)` |
| **Label** | Gateway name (12px medium) |
| **Sub-label** | Type (ER/VPN) + SKU (11px, `var(--text-secondary)`) |
| **Handles** | Top (connects to GatewaySubnet) |

---

## 3. Edge / Connection Styles

| Edge Type | Stroke Color | Style | Animated | Width |
|-----------|-------------|-------|----------|-------|
| **VNet peering (connected)** | `var(--accent-blue)` | `smoothstep` | Yes (slow) | 2px |
| **VNet peering (disconnected)** | `var(--accent-red)` | `smoothstep`, dashed | No | 2px |
| **Subnet → NSG** | `var(--border)` | `smoothstep`, dashed `[4,4]` | No | 1px |
| **Subnet → LB** | `var(--text-muted)` | `smoothstep`, solid | No | 1.5px |
| **Subnet → PE** | `var(--accent-purple)` | `smoothstep`, dotted `[2,4]` | No | 1px |
| **Subnet → Gateway** | `var(--accent-orange)` | `smoothstep`, solid | No | 1.5px |
| **Asymmetry issue (auto-highlight)** | `var(--accent-red)` | `smoothstep`, dashed `[6,4]` | Yes (fast) | 2.5px |
| **Path check — allowed hop** | `var(--accent-green)` | `smoothstep`, solid | Yes | 2.5px |
| **Path check — blocked hop** | `var(--accent-red)` | `smoothstep`, solid | Yes | 2.5px |

Edge labels: Peering edges show peering name in 10px `var(--text-muted)`. Issue edges show "Asymmetric block" label in 10px `var(--accent-red)`.

---

## 4. NSG Badge States

Badge is a pill overlaid at the **top-right corner** of the NSG node, offset `-4px, -4px`.

```css
/* Base pill */
padding: 1px 6px;
border-radius: 9999px;
font-size: 10px;
font-weight: 600;
text-transform: uppercase;
letter-spacing: 0.02em;
```

| State | Background | Text Color | Border | Label | Trigger |
|-------|-----------|------------|--------|-------|---------|
| **Green** | `color-mix(in srgb, var(--accent-green) 15%, transparent)` | `var(--accent-green)` | `1px solid color-mix(in srgb, var(--accent-green) 30%, transparent)` | "OK" | No issues detected |
| **Yellow** | `color-mix(in srgb, var(--accent-yellow) 15%, transparent)` | `var(--accent-yellow)` | `1px solid color-mix(in srgb, var(--accent-yellow) 30%, transparent)` | "WARN" | Overly permissive rule: priority < 1000 with source `*`, dest port `*`, access `Allow` |
| **Red** | `color-mix(in srgb, var(--accent-red) 15%, transparent)` | `var(--accent-red)` | `1px solid color-mix(in srgb, var(--accent-red) 30%, transparent)` | "BLOCK" | Asymmetric block detected on common ports (22, 80, 443, 3389): one side allows, other denies |

---

## 5. Path Checker Side Panel

Uses shadcn/ui `Sheet` component, opening from the **right** side. Trigger: "Path Checker" button in header bar.

### 5.1 Panel Layout

```
+-------------------------------------+
| Sheet header                        |
| "Path Checker"              [Close] |
+-------------------------------------+
| Source Resource                      |
| [Combobox / searchable select]      |
|                                      |
| Destination Resource                 |
| [Combobox / searchable select]      |
|                                      |
| Port         Protocol                |
| [Input]      [Select: TCP/UDP/ICMP] |
|                                      |
| [  Check Path  ] (primary button)   |
+-------------------------------------+
| Verdict banner                       |
+-------------------------------------+
| Step-by-step results                 |
+-------------------------------------+
```

### 5.2 Form Fields

| Field | Component | Style |
|-------|-----------|-------|
| **Source Resource** | shadcn `Select` with search, populated from topology nodes (VMs, NICs) | `var(--bg-surface)`, `var(--border)` |
| **Destination Resource** | Same as source | Same |
| **Port** | shadcn `Input`, type `number`, placeholder "443" | Same |
| **Protocol** | shadcn `Select`: TCP, UDP, ICMP | Same |
| **Check Path** | shadcn `Button` variant `default` (primary blue) | Full width |

### 5.3 Verdict Display

**Allowed:**

```css
/* Banner */
background: color-mix(in srgb, var(--accent-green) 10%, transparent);
border: 1px solid color-mix(in srgb, var(--accent-green) 30%, transparent);
color: var(--accent-green);
/* Icon: CheckCircle */
/* Text: "Traffic Allowed" */
```

**Blocked:**

```css
/* Banner */
background: color-mix(in srgb, var(--accent-red) 10%, transparent);
border: 1px solid color-mix(in srgb, var(--accent-red) 30%, transparent);
color: var(--accent-red);
/* Icon: XCircle */
/* Text: "Traffic Blocked by {nsg_name}" */
```

### 5.4 Step-by-Step Verdict List

Rendered as a vertical timeline below the verdict banner:

```
  [1] nsg-web (Outbound, Subnet)     ✓ Allow — rule "AllowHTTPS" (pri 200)
  [2] nsg-db  (Inbound, Subnet)      ✗ Deny  — rule "DenyAllInBound" (pri 65500)
```

| Element | Style |
|---------|-------|
| Step number | `var(--text-muted)`, 11px |
| NSG name | `var(--text-primary)`, 12px semibold |
| Direction + level | `var(--text-secondary)`, 11px |
| Allow result | `var(--accent-green)`, 11px, `CheckCircle` icon 12px |
| Deny result | `var(--accent-red)`, 11px, `XCircle` icon 12px |
| Rule name + priority | `var(--text-muted)`, 11px mono |

### 5.5 Canvas Highlight Behavior

When path check returns:
1. All **non-path nodes** dim to 30% opacity
2. **Path edges** are drawn/highlighted per section 3 (green for allowed hops, red for blocked)
3. **Blocking NSG node** gets the highlighted state from section 2.3 (red border + glow)
4. Canvas auto-fits to show the full path (`fitView` with padding)
5. Clicking "Clear" in the panel resets all highlights and restores full opacity

---

## 6. Loading / Error / Empty States

### Loading (initial fetch)

- Canvas area shows centered spinner + "Loading network topology..." in 14px `var(--text-secondary)`
- Use the same pattern as VNetPeeringTab (loading state in center)

### Error

- Inline error banner below header (same style as VNetPeeringTab error):
  ```css
  background: color-mix(in srgb, var(--accent-red) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent-red) 30%, transparent);
  color: var(--accent-red);
  ```
- Icon: `AlertTriangle` 14px
- Text: error message from API

### Empty (no network resources)

- Canvas area shows centered empty state:
  - Icon: `Network` at 40px, `var(--text-muted)`
  - Text: "No network resources found in the current subscriptions." (14px, `var(--text-secondary)`)
  - **No** "Run a scan" messaging

### Path Checker — no result yet

- Below the form, muted placeholder: "Select source, destination, port, and protocol to check connectivity." (12px, `var(--text-muted)`)

### Path Checker — loading

- Button shows spinner, disabled state
- Text below: "Evaluating NSG rules..." (12px, `var(--text-secondary)`)

---

## 7. Color Token Reference

| Token | CSS Variable | Usage |
|-------|-------------|-------|
| Canvas background | `var(--bg-canvas)` | React Flow canvas bg, page bg |
| Surface background | `var(--bg-surface)` | All node card backgrounds |
| Subtle background | `var(--bg-subtle)` | Stat cards, hover states |
| Border | `var(--border)` | Node borders, edge defaults, grid dots |
| Primary text | `var(--text-primary)` | Node labels, header text |
| Secondary text | `var(--text-secondary)` | Sub-labels, metadata |
| Muted text | `var(--text-muted)` | Timestamps, hints, edge labels |
| Blue accent | `var(--accent-blue)` | VNet borders, peering edges, primary buttons |
| Green accent | `var(--accent-green)` | NSG OK badge, allowed path edges |
| Yellow accent | `var(--accent-yellow)` | NSG WARN badge |
| Red accent | `var(--accent-red)` | NSG BLOCK badge, blocked edges, asymmetry highlights, errors |
| Orange accent | `var(--accent-orange)` | Gateway borders, gateway icons |
| Purple accent | `var(--accent-purple)` | LB icons, PE icons, PE edges |

**Badge formula (all badges):**
```css
background: color-mix(in srgb, var(--accent-*) 15%, transparent);
color: var(--accent-*);
border: 1px solid color-mix(in srgb, var(--accent-*) 30%, transparent);
```

**Never use:** hardcoded Tailwind color classes (`bg-green-100`, `text-red-700`, etc.)

---

## 8. Data Loading Contract

| Aspect | Specification |
|--------|--------------|
| **Mount** | `useEffect` calls `fetchTopology()` immediately |
| **Polling** | `setInterval(fetchTopology, 600_000)` (10 min) |
| **Path check** | On-demand `POST`, no caching |
| **No scan button** | Compliant with Dashboard Tab Implementation Rules |
| **Empty state** | "No network resources found" — never "Run a scan" |

---

*End of UI design contract.*
