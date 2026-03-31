# Web UI SaaS Redesign — Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Scope:** `services/web-ui`

---

## 1. Objective

Transform the current "default shadcn prototype" aesthetic into a polished, production-grade SaaS UI in the Datadog/Grafana style. The redesign covers:

- A new design system (color tokens, typography, depth model) with full light/dark mode consistency
- A new layout: always-dark top nav + full-width dashboard + collapsible AI chat drawer
- Upgraded component styling throughout (tabs, alerts, cards, input, bubbles)

The redesign is **purely cosmetic + layout** — no changes to data fetching, API routes, auth, or business logic.

---

## 2. Design System

### 2.1 Color Tokens

All tokens defined as CSS custom properties in `globals.css` under `:root` (light) and `.dark` (dark). The top nav bar uses `--bg-nav` which is **always dark** regardless of mode.

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| `--bg-canvas` | `#F4F5F7` | `#0D1117` | Page background |
| `--bg-surface` | `#FFFFFF` | `#161B22` | Cards, panels, drawer |
| `--bg-surface-raised` | `#FFFFFF` | `#1C2333` | Dropdowns, drawer header/footer |
| `--bg-subtle` | `#F0F2F5` | `#21262D` | Agent bubbles, row hovers, badges |
| `--bg-nav` | `#0D1117` | `#0D1117` | Top nav (always dark) |
| `--border` | `#DDE1E7` | `#30363D` | Card/panel borders |
| `--border-subtle` | `#EBEDF0` | `#21262D` | Dividers, subtle separators |
| `--text-primary` | `#0D1117` | `#E6EDF3` | Main body text |
| `--text-secondary` | `#57606A` | `#8B949E` | Labels, secondary info |
| `--text-muted` | `#8C959F` | `#6E7681` | Timestamps, placeholders |
| `--accent-blue` | `#0969DA` | `#388BFD` | Primary action, active tab, FAB, user bubble |
| `--accent-green` | `#1A7F37` | `#3FB950` | Healthy/success states |
| `--accent-yellow` | `#9A6700` | `#D29922` | Warning / Sev2 |
| `--accent-red` | `#CF222E` | `#F85149` | Critical / Sev0 / destructive |
| `--accent-orange` | `#BC4C00` | `#DB6D28` | Sev1 / proposal cards |
| `--accent-purple` | `#8250DF` | `#A371F7` | Informational / Sev3 |

### 2.2 Severity → Color Mapping

Consistent across all tabs and the chat drawer:

| Severity | Color Token | Left Border | Dot Badge |
|----------|-------------|-------------|-----------|
| Sev0 (Critical) | `--accent-red` | ✓ | ✓ |
| Sev1 (High) | `--accent-orange` | ✓ | ✓ |
| Sev2 (Medium) | `--accent-yellow` | ✓ | ✓ |
| Sev3 (Low) | `--accent-purple` | ✓ | ✓ |
| Healthy | `--accent-green` | ✓ | ✓ |

### 2.3 Typography

| Use | Font | Size | Weight |
|-----|------|------|--------|
| UI body | Inter | 14px | 400 |
| Dense data (tables, lists) | Inter | 13px | 400 |
| Labels, chips | Inter | 12px | 500 |
| Headings (card titles) | Inter | 14px | 600 |
| Metric values | JetBrains Mono | 20–24px | 600 |
| IDs, resource names, code | JetBrains Mono | 12–13px | 400 |

### 2.4 Depth Model

Three elevation levels, expressed through **background + border** (no box shadows except drawer):

| Level | Token | Border | Usage |
|-------|-------|--------|-------|
| Canvas | `--bg-canvas` | none | Page background |
| Surface | `--bg-surface` | `1px --border` | Cards, tab content, drawer body |
| Raised | `--bg-surface-raised` | `1px --border` | Drawer header/footer, dropdowns, tooltips |

The chat drawer gets a single `box-shadow: -4px 0 24px rgba(0,0,0,0.25)` to lift it above the backdrop.

### 2.5 Border Radius

| Element | Radius |
|---------|--------|
| Cards, panels | `8px` |
| Buttons, chips, badges | `6px` |
| Chat bubbles | `16px` (outer corners) / `4px` (sender-side bottom) |
| FAB | `50%` (circle) |
| Input | `8px` |
| Avatar | `50%` |

---

## 3. Top Navigation Bar

### 3.1 Structure

Always-dark (`--bg-nav`) `48px` full-width bar. Never participates in the theme toggle.

```
[Logo + Wordmark] [separator] [Breadcrumb]     [SubscriptionSelector]     [Refresh] [Theme] [Bell 3] [Avatar]
← left                                          ← center                            ← right →
```

### 3.2 Elements

**Logo + Wordmark**
- Small Azure-style hex/cloud icon mark (SVG inline, white)
- "Azure AIOps" in Inter 14px 600 white
- Separator: `1px` vertical line `bg-gray-700` `20px` tall

**Breadcrumb**
- Shows active tab name, `--text-muted` in nav context (light gray)
- Updates on tab change

**Subscription Selector**
- Compact pill: cloud icon + "N subscription(s)" + chevron
- `bg-gray-800` background, `border border-gray-700`, white text
- Hover: `bg-gray-700`
- Opens existing `SubscriptionSelector` dropdown logic

**Right controls (left → right)**
- **Refresh indicator:** `16px` lucide `RefreshCw` icon, spins while any fetch is in-flight. Muted when idle.
- **Theme toggle:** Sun icon (light mode) / Moon icon (dark mode). `32px` icon button. Persists to `localStorage` key `aap-theme`. Defaults to system preference via `prefers-color-scheme`.
- **Notifications bell:** `Bell` icon + red count badge (positioned top-right of icon). Badge hidden when 0. Wired to alert feed count from `DashboardPanel`.
- **User avatar:** `32px` circle, initials derived from MSAL `account.name`. `bg-accent-blue`. Clicking opens a small dropdown: name (bold), tenant (muted), divider, "Sign out" (destructive text).

---

## 4. Main Layout

### 4.1 Shell Structure

```
┌────────────────────────────────────────────────────────┐
│  TopNav (48px, always dark, position: sticky, z-50)    │
├────────────────────────────────────────────────────────┤
│                                                        │
│  DashboardPanel (full width, height: calc(100vh-48px)) │
│  bg-canvas, overflow-y: auto                           │
│                                                        │
└────────────────────────────────────────────────────────┘
                                       [FAB: Ask AI]  ← fixed bottom-right
[ChatDrawer] ← slides in from right, fixed, overlays dashboard
```

- Remove `react-resizable-panels` entirely — no more split pane
- `AppLayout` becomes a simple flex-col: TopNav + DashboardPanel
- Chat state (messages, threadId, streaming) moves into a `ChatDrawerProvider` context so FAB and drawer share state without prop drilling

### 4.2 Dashboard Tab Bar

Sits at the top of `DashboardPanel`, full width, `bg-surface` with `border-b border`.

```
[padding-left: 16px]
[Bell Alerts]  [Clipboard Audit]  [Network Topology]  [Server Resources]  [Activity Observability]
```

- Each tab: icon (16px) + label, `13px 500`, `px-4 py-3`
- Inactive: `--text-secondary`, transparent bg, hover `--bg-subtle`
- Active: `--text-primary`, `2px` bottom border `--accent-blue`, `font-600`
- No shadcn `Tabs` wrapper — use a simple flex bar with `button` elements and active state managed in `DashboardPanel`

### 4.3 Tab Content Area

- `padding: 24px`
- Each tab renders its content inside `bg-surface` cards with `1px border --border`, `border-radius: 8px`
- Scrolls independently (dashboard is the scroll container)

---

## 5. Dashboard Tab Upgrades

### 5.1 Alerts Tab

**Header row** (flex, space-between):
- Left: 3 filter pills (Severity / Domain / Status) — compact `Select` with icon prefix, `height: 32px`, `bg-subtle` background
- Right: "N alerts" count in `--text-secondary` + Export button (outline, small)

**Alert rows** (inside a card, no outer table borders):
- `4px` left border stripe in severity color
- Row: `severity dot` + `resource name (bold, font-mono 13px)` + `domain chip` + `description (muted, truncated)` + `time (relative, muted)` + `status chip`
- `hover:bg-subtle` on row
- `cursor-pointer` — future click-to-investigate hook
- Skeleton rows (4) on loading state

### 5.2 Audit Tab

- Same card + header pattern
- Agent filter + action search inline in header
- Table rows: `timestamp (mono)` + `agent chip` + `tool name` + `outcome badge` + `duration (mono)`
- Outcome: green "success" / red "error" / yellow "warning" badges

### 5.3 Topology Tab

- Search bar in header card
- Tree items: larger hit targets (`py-2`), hover bg, type icons colored by category
- Subscription node: `--accent-blue` icon
- Resource group: `--text-secondary` folder icon
- Resources: category color (compute=blue, network=purple, storage=yellow, db=green)

### 5.4 Resources Tab

- Search + type filter in header
- Table: `name (mono, bold)` + `type badge` + `location chip` + `subscription (muted)`
- Type badges use category colors (not all `secondary`)

### 5.5 Observability Tab

- Time range selector in header (right-aligned)
- 2×2 metric card grid — cards get the surface treatment
- Metric values: `font-mono 24px 600`, label `12px muted`
- Trend indicators: small `↑` / `↓` colored arrows next to values

---

## 6. Chat Drawer

### 6.1 Trigger: FAB

- Fixed position: `bottom: 24px`, `right: 24px`, `z-index: 50`
- `56px` circle, `bg-accent-blue`, white `MessageSquare` icon (24px)
- Subtle `box-shadow: 0 0 0 4px rgba(9,105,218,0.2)` pulse animation when streaming
- When drawer open: morphs to `✕` (X icon), same size/position

### 6.2 Drawer Layout

- `width: 420px`, `height: calc(100vh - 48px)` (sits below nav)
- `position: fixed`, `top: 48px`, `right: 0`
- `bg-surface`, `border-l border`, `box-shadow: -4px 0 24px rgba(0,0,0,0.25)`
- Slides in/out: `transform: translateX(100%)` → `translateX(0)`, `transition: 300ms ease-out`
- Backdrop: `fixed inset-0 bg-black/40 z-40`, `top: 48px` (doesn't cover nav), fade in/out

**Internal flex layout (column):**
```
┌─────────────────────────────────┐  ← bg-surface-raised, border-b, 48px
│  [AI dot] Azure AI   [GPT-4o]   │
├─────────────────────────────────┤  ← flex-grow, overflow-y-auto
│  Message history                │
├─────────────────────────────────┤  ← border-t, 40px, horizontal scroll
│  Quick chips                    │
├─────────────────────────────────┤  ← bg-surface-raised, border-t, min 60px
│  [textarea]          [→ Send]   │
└─────────────────────────────────┘
```

### 6.3 Drawer Header

- `bg-surface-raised`, `border-b border`, `48px`, `px-4`
- Left: `8px` green dot (online indicator) + "Azure AI" `14px 600`
- Center: `GPT-4o` chip — `bg-subtle border`, `font-mono 11px`, `border-radius: 4px`, `px-2`
- Right: `✕` icon button, `--text-muted`, hover `--text-primary`

### 6.4 Message Bubbles

**User bubble:**
- Right-aligned, max-width `85%`
- `bg-accent-blue`, white text, `border-radius: 16px 16px 4px 16px`
- `14px`, padding `10px 14px`
- No avatar

**Agent bubble:**
- Left-aligned, max-width `90%`
- `bg-subtle`, `border border`, `border-radius: 16px 16px 16px 4px`
- `14px`, padding `10px 14px`
- Small `24px` avatar circle left of bubble: "AI" initials, `bg-accent-blue/20`, `--accent-blue` text
- Markdown rendered with tight `.chat-prose` styles (existing, tweak spacing)
- Streaming: blinking cursor `▋` at end of partial text

**Timestamps:** `11px --text-muted`, shown on hover only, positioned below bubble

**ThinkingIndicator:** 3 dots, `--accent-blue` color, staggered pulse

### 6.5 Quick Chips Bar

- `height: 40px`, horizontal scroll, `gap: 8px`, `px-4`
- Each chip: `bg-subtle border`, `12px 500`, `px-3 py-1`, `border-radius: 6px`
- Hover: `bg-accent-blue/10 border-accent-blue/40`
- Hidden when `messages.length === 0` (empty state handles this differently — see below)

### 6.6 Empty State (inside drawer)

When no messages yet, replace message history area with centered content:
- `MessageSquare` icon `48px --text-muted`
- "Ask anything about your Azure infrastructure" — `14px --text-secondary`
- Chips rendered in a 2-column wrap grid (not scrolling bar) — more inviting

### 6.7 ProposalCard (inside drawer)

- Full width within bubble flow (agent side)
- `border-l-4 border-accent-orange`, `bg-subtle`, `border border rounded-lg`
- Header: "Approval Required" bold + action summary in mono
- Body: resource list, proposed change details
- Footer: "Approve" (`bg-accent-green`) + "Reject" (`bg-accent-red`) buttons, each with confirmation dialog

---

## 7. Theme Toggle Behavior

- On mount: read `localStorage.getItem('aap-theme')`. If null, use `window.matchMedia('(prefers-color-scheme: dark)').matches`.
- Apply by toggling `.dark` class on `<html>` element.
- On toggle: flip class + write to `localStorage`.
- Theme context available via a `ThemeProvider` wrapping the app — exposes `theme` + `toggleTheme`.
- All color tokens automatically switch via CSS custom properties — no JS-driven color changes needed.

---

## 8. Component Change Summary

| Component | Change Type | Notes |
|-----------|-------------|-------|
| `AppLayout.tsx` | Major rewrite | Remove resizable panels, add TopNav + simple layout shell |
| `globals.css` | Major rewrite | New token set, dark mode tokens, remove old HSL tokens |
| `DashboardPanel.tsx` | Moderate rewrite | New tab bar, content padding, card wrapping |
| `ChatPanel.tsx` | Renamed → `ChatDrawer.tsx` | Drawer layout, slide animation, backdrop |
| `ChatInput.tsx` | Minor update | Auto-resize textarea, icon-only send button |
| `ChatBubble.tsx` | Moderate update | New bubble styling, avatar, timestamp-on-hover |
| `UserBubble.tsx` | Moderate update | New bubble shape and colors |
| `AlertFeed.tsx` | Moderate update | Severity stripe rows, skeleton loader |
| `AlertFilters.tsx` | Minor update | Compact pill selects |
| `ObservabilityTab.tsx` | Minor update | Mono metric values, trend arrows |
| `TopologyTab.tsx` | Minor update | Category-colored icons, larger hit targets |
| `ResourcesTab.tsx` | Minor update | Category-colored type badges |
| `ProposalCard.tsx` | Minor update | Orange border, new button colors |
| `ThinkingIndicator.tsx` | Minor update | Blue dots |
| **New:** `TopNav.tsx` | New component | App chrome bar |
| **New:** `ChatDrawerProvider.tsx` | New component | Context for drawer open state + chat state |
| **New:** `ThemeProvider.tsx` | New component | Theme toggle context |
| **New:** `ChatFAB.tsx` | New component | Floating action button |

---

## 9. Out of Scope

- No changes to API routes, data fetching, or business logic
- No mobile/responsive design (desktop-only gate remains)
- No dark mode for the nav bar (always dark by design)
- No animation beyond drawer slide + FAB pulse + thinking dots
- `TraceTree` component remains unused (existing behavior preserved)
- Teams integration components not touched
