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
| `--bg-nav-pill` | `#1C2333` | `#1C2333` | Subscription pill background (always dark) |
| `--border-nav` | `#30363D` | `#30363D` | Nav borders and separators (always dark) |
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

**Nav-context tokens** (`--bg-nav`, `--bg-nav-pill`, `--border-nav`) are intentionally non-themeable — they use fixed dark values in both light and dark mode. This is the Datadog design signature: consistently dark chrome regardless of content theme.

### 2.2 shadcn Token Bridging

The existing shadcn/ui primitives (`Button`, `Badge`, `Dialog`, `Select`, `Table`, `Skeleton`, etc.) reference the legacy HSL token names (`--background`, `--foreground`, `--primary`, `--muted`, `--border`, `--destructive`, etc.) via Tailwind utilities like `bg-background`, `text-foreground`, `border-border`. These must continue to work unchanged.

**The integration point:** The existing `globals.css` `@theme` block wraps token values in `hsl()`:
```css
@theme {
  --color-background: hsl(var(--background));  /* expects bare HSL channels */
  --color-primary: hsl(var(--primary));
  /* etc. */
}
```
This means shadcn tokens must store **bare HSL channels** (e.g., `207 90% 42%`), not hex values. The new design tokens in Section 2.1 use hex for readability in the spec, but the implementation must convert them to HSL channels.

**Strategy: Rewrite `@theme` + `:root` together.** The `@theme` block is rewritten to drop the `hsl()` wrappers and reference the new tokens directly as complete color values. The legacy shadcn token names are kept as aliases:

```css
/* globals.css */

@theme {
  /* Rewrite: reference new tokens directly (no hsl() wrapper) */
  --color-background: var(--bg-canvas);
  --color-foreground: var(--text-primary);
  --color-card: var(--bg-surface);
  --color-card-foreground: var(--text-primary);
  --color-primary: var(--accent-blue);
  --color-primary-foreground: #FFFFFF;
  --color-secondary: var(--bg-subtle);
  --color-secondary-foreground: var(--text-secondary);
  --color-muted: var(--bg-subtle);
  --color-muted-foreground: var(--text-muted);
  --color-accent: var(--bg-subtle);
  --color-accent-foreground: var(--text-primary);
  --color-destructive: var(--accent-red);
  --color-destructive-foreground: #FFFFFF;
  --color-border: var(--border);
  --color-input: var(--border);
  --color-ring: var(--accent-blue);
  --color-popover: var(--bg-surface-raised);
  --color-popover-foreground: var(--text-primary);
  /* Border radius preserved */
  --radius: 0.5rem;
}

:root {
  /* New design tokens (hex) */
  --bg-canvas: #F4F5F7;
  --bg-surface: #FFFFFF;
  --bg-surface-raised: #FFFFFF;
  --bg-subtle: #F0F2F5;
  --bg-nav: #0D1117;
  --bg-nav-pill: #1C2333;
  --border: #DDE1E7;
  --border-subtle: #EBEDF0;
  --border-nav: #30363D;
  --text-primary: #0D1117;
  --text-secondary: #57606A;
  --text-muted: #8C959F;
  --accent-blue: #0969DA;
  --accent-green: #1A7F37;
  --accent-yellow: #9A6700;
  --accent-red: #CF222E;
  --accent-orange: #BC4C00;
  --accent-purple: #8250DF;
}

.dark {
  /* Dark mode overrides */
  --bg-canvas: #0D1117;
  --bg-surface: #161B22;
  --bg-surface-raised: #1C2333;
  --bg-subtle: #21262D;
  /* --bg-nav, --bg-nav-pill, --border-nav unchanged (always dark) */
  --border: #30363D;
  --border-subtle: #21262D;
  --text-primary: #E6EDF3;
  --text-secondary: #8B949E;
  --text-muted: #6E7681;
  --accent-blue: #388BFD;
  --accent-green: #3FB950;
  --accent-yellow: #D29922;
  --accent-red: #F85149;
  --accent-orange: #DB6D28;
  --accent-purple: #A371F7;
}
```

Key points:
- `@theme` references the new design tokens via `var()` — no more bare HSL channels, no `hsl()` wrappers
- All 18 shadcn primitives work unchanged: `bg-background` → `var(--color-background)` → `var(--bg-canvas)` → `#F4F5F7`
- `--popover` and `--popover-foreground` are included (used by `SubscriptionSelector` Command/Popover)
- `--border` name is used for the design token directly — no collision or self-reference; `@theme` maps `--color-border: var(--border)`
- No changes needed to any `components/ui/*.tsx` file

### 2.3 Severity → Color Mapping

Consistent across all tabs and the chat drawer:

| Severity | Color Token | Left Border | Dot Badge |
|----------|-------------|-------------|-----------|
| Sev0 (Critical) | `--accent-red` | ✓ | ✓ |
| Sev1 (High) | `--accent-orange` | ✓ | ✓ |
| Sev2 (Medium) | `--accent-yellow` | ✓ | ✓ |
| Sev3 (Low) | `--accent-purple` | ✓ | ✓ |
| Healthy | `--accent-green` | ✓ | ✓ |

### 2.4 Typography

| Use | Font | Size | Weight |
|-----|------|------|--------|
| UI body | Inter | 14px | 400 |
| Dense data (tables, lists) | Inter | 13px | 400 |
| Labels, chips | Inter | 12px | 500 |
| Headings (card titles) | Inter | 14px | 600 |
| Metric values | JetBrains Mono | 20–24px | 600 |
| IDs, resource names, code | JetBrains Mono | 12–13px | 400 |

**Font loading:** Both Inter and JetBrains Mono must be loaded via `next/font/google` in `app/layout.tsx`. JetBrains Mono is already referenced as `--font-mono` in the current `@theme` block but is not yet loaded — add it alongside Inter:

```ts
// app/layout.tsx
import { Inter, JetBrains_Mono } from 'next/font/google'
const inter = Inter({ subsets: ['latin'], variable: '--font-inter' })
const jetbrainsMono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono' })
```

Apply both `font.variable` classes to the `<html>` element.

### 2.5 Depth Model

Three elevation levels, expressed through **background + border** (no box shadows except drawer):

| Level | Token | Border | Usage |
|-------|-------|--------|-------|
| Canvas | `--bg-canvas` | none | Page background |
| Surface | `--bg-surface` | `1px --border` | Cards, tab content, drawer body |
| Raised | `--bg-surface-raised` | `1px --border` | Drawer header/footer, dropdowns, tooltips |

The chat drawer gets a single `box-shadow: -4px 0 24px rgba(0,0,0,0.25)` to lift it above the backdrop.

### 2.6 Border Radius

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
- Separator: `1px` vertical line `var(--border-nav)` `20px` tall

**Breadcrumb**
- Shows active tab name, `--text-muted` in nav context (light gray `#6E7681`)
- Updates on tab change via prop from `DashboardPanel`

**Subscription Selector — `NavSubscriptionPill`**
- A new thin wrapper component that acts as the trigger for the existing `SubscriptionSelector` Popover
- Pill styling: `background: var(--bg-nav-pill)`, `border: 1px solid var(--border-nav)`, white text, `border-radius: 6px`, `height: 32px`, `px-3`
- Content: `Cloud` icon (16px, muted white) + "N subscription(s)" + `ChevronDown` icon
- Hover: `opacity: 0.85`
- Opens the existing `SubscriptionSelector` Popover/Command dropdown unchanged

**Right controls (left → right)**
- **Refresh indicator:** `16px` lucide `RefreshCw` icon, `color: #6E7681`, spins (CSS `animate-spin`) while any fetch is in-flight. Muted when idle.
- **Theme toggle:** `Sun` icon (dark mode — click to go light) / `Moon` icon (light mode — click to go dark). `32px` icon button, `color: #8B949E`, hover white. Persists to `localStorage` key `aap-theme`. See Section 7.
- **Notifications bell:** `Bell` icon + red `8px` count badge (positioned top-right). Badge hidden when count is 0. Count sourced from `AppStateContext` (see Section 4.1). Color `--accent-red`.
- **User avatar:** `32px` circle, initials from MSAL `account.name`. `background: var(--accent-blue)`, white text `12px 600`. Clicking opens a small dropdown (`bg-surface-raised`, `border border`, `shadow`): name (bold `14px`), tenant (`12px --text-muted`), `<hr>`, "Sign out" (`--accent-red` text).

---

## 4. Main Layout

### 4.1 Shell Structure & Shared State

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
- `AppLayout` becomes a simple flex-col: TopNav + DashboardPanel + ChatFAB + ChatDrawer
- Introduce **`AppStateContext`** (in `ChatDrawerProvider.tsx`) that holds:
  - `drawerOpen: boolean` + `setDrawerOpen`
  - All current chat state from `ChatPanel` (messages, threadId, streaming, etc.)
  - `alertCount: number` — populated by `AlertFeed`, consumed by `TopNav` bell badge
  - `selectedIncidentId: string | null` — preserved from old `AppLayout`, flows to `DashboardPanel`
- `ThemeProvider` wraps above `AppStateContext` in `providers.tsx` — see Section 7

### 4.2 Dashboard Tab Bar

Sits at the top of `DashboardPanel`, full width, `bg-surface` with `border-b border`.

```
[padding-left: 16px]
[Bell Alerts]  [Clipboard Audit]  [Network Topology]  [Server Resources]  [Activity Observability]
```

- Each tab: icon (16px) + label, `13px 500`, `px-4 py-3`
- Inactive: `--text-secondary`, transparent bg, hover `--bg-subtle`
- Active: `--text-primary`, `2px` bottom border `--accent-blue`, `font-600`
- Implemented as a custom `role="tablist"` flex bar (replacing shadcn `Tabs`) with full ARIA:
  - Container: `role="tablist"`
  - Each button: `role="tab"`, `aria-selected={active}`, `id="tab-{name}"`, `aria-controls="tabpanel-{name}"`
  - Each content area: `role="tabpanel"`, `id="tabpanel-{name}"`, `aria-labelledby="tab-{name}"`
  - Keyboard navigation: `ArrowLeft` / `ArrowRight` moves focus between tabs; `Enter` / `Space` activates focused tab
- Active state managed in `DashboardPanel` via `useState<TabId>`

### 4.3 Tab Content Area

- `padding: 24px`
- Each tab renders its content inside `bg-surface` cards with `1px solid var(--border)`, `border-radius: 8px`
- Scrolls independently (dashboard is the scroll container, `overflow-y: auto`)

---

## 5. Dashboard Tab Upgrades

### 5.1 Alerts Tab

**Header row** (flex, space-between):
- Left: 3 filter pills (Severity / Domain / Status) — compact `Select` with icon prefix, `height: 32px`, `bg-subtle` background
- Right: "N alerts" count in `--text-secondary` + Export button (outline, small)
- Alert count updates `AppStateContext.alertCount` so `TopNav` bell badge stays in sync

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
- 2×2 metric card grid — cards get the surface treatment (`bg-surface border rounded-lg`)
- Metric values: `font-mono 24px 600 --text-primary`, label `12px --text-muted`
- Trend indicators: small `↑` (green) / `↓` (red) colored arrows next to values

---

## 6. Chat Drawer

### 6.1 Trigger: FAB (`ChatFAB.tsx`)

- Fixed position: `bottom: 24px`, `right: 24px`, `z-index: 50`
- `56px` circle, `background: var(--accent-blue)`, white `MessageSquare` icon (24px)
- Subtle `box-shadow: 0 0 0 4px rgba(9,105,218,0.2)` pulse animation (`animate-pulse`) when streaming
- When drawer open: shows `X` icon instead of `MessageSquare`, same size/position
- Reads `drawerOpen` + `isStreaming` from `AppStateContext`

### 6.2 Drawer Layout (`ChatDrawer.tsx`)

- `width: 420px`, `height: calc(100vh - 48px)` (sits below nav)
- `position: fixed`, `top: 48px`, `right: 0`, `z-index: 45`
- `background: var(--bg-surface)`, `border-left: 1px solid var(--border)`, `box-shadow: -4px 0 24px rgba(0,0,0,0.25)`
- Slides in/out: `transform: translateX(100%)` ↔ `translateX(0)`, `transition: transform 300ms ease-out`
- Backdrop: `position: fixed`, `inset: 48px 0 0 0`, `background: rgba(0,0,0,0.4)`, `z-index: 40`, fades in/out with `transition: opacity 200ms`; click closes drawer

**Internal flex layout (column, full height):**
```
┌─────────────────────────────────┐  ← bg-surface-raised, border-b, 48px, flex-shrink-0
│  [AI dot] Azure AI   [GPT-4o]   │
├─────────────────────────────────┤  ← flex-grow, overflow-y-auto, px-4 py-3
│  Message history                │
├─────────────────────────────────┤  ← border-t, 40px, horizontal scroll, flex-shrink-0
│  Quick chips                    │
├─────────────────────────────────┤  ← bg-surface-raised, border-t, min 60px, flex-shrink-0
│  [textarea]          [→ Send]   │
└─────────────────────────────────┘
```

### 6.3 Drawer Header

- `background: var(--bg-surface-raised)`, `border-bottom: 1px solid var(--border)`, `48px height`, `px-4`
- Left: `8px` circle `background: var(--accent-green)` (online dot) + "Azure AI" `14px 600 --text-primary`
- Center: `GPT-4o` chip — `background: var(--bg-subtle)`, `border: 1px solid var(--border)`, `font-mono 11px --text-secondary`, `border-radius: 4px`, `px-2 py-0.5`
- Right: `X` icon button `16px`, `color: var(--text-muted)`, hover `var(--text-primary)`, `border-radius: 4px`, hover `background: var(--bg-subtle)`

### 6.4 Message Bubbles

**User bubble:**
- Right-aligned, `max-width: 85%`
- `background: var(--accent-blue)`, `color: white`, `border-radius: 16px 16px 4px 16px`
- `font-size: 14px`, `padding: 10px 14px`, `margin-left: auto`

**Agent bubble:**
- Left-aligned with `24px` avatar, `max-width: 90%`
- Bubble: `background: var(--bg-subtle)`, `border: 1px solid var(--border)`, `border-radius: 16px 16px 16px 4px`
- `font-size: 14px`, `padding: 10px 14px`
- Avatar: `24px` circle, `background: color-mix(in srgb, var(--accent-blue) 20%, transparent)`, `color: var(--accent-blue)`, `font-size: 10px 600`, "AI" initials
- Markdown rendered with `.chat-prose` styles (update code block bg to `var(--bg-subtle)` / dark-mode `var(--bg-subtle)` instead of hardcoded HSL value)
- Streaming: blinking cursor `▋` at end of partial text

**Error / system message bubble:**
- Left-aligned (same position as agent bubble, no avatar)
- `background: color-mix(in srgb, var(--accent-red) 10%, transparent)`, `border-left: 4px solid var(--accent-red)`, `border-radius: 8px`
- `color: var(--text-primary)`, `font-size: 13px`, `padding: 10px 14px`
- Label: "System" in `var(--accent-red)` `11px 600` above message text

**Timestamps:** `11px var(--text-muted)`, shown on hover only, below bubble, `margin-top: 2px`

**ThinkingIndicator:** 3 dots, `color: var(--accent-blue)`, staggered pulse

### 6.5 Quick Chips Bar

- `height: 40px`, `overflow-x: auto`, `display: flex`, `gap: 8px`, `padding: 0 16px`, `align-items: center`
- Each chip: `background: var(--bg-subtle)`, `border: 1px solid var(--border)`, `font-size: 12px 500 --text-secondary`, `padding: 4px 12px`, `border-radius: 6px`, `white-space: nowrap`, `cursor: pointer`
- Hover: `background: color-mix(in srgb, var(--accent-blue) 10%, transparent)`, `border-color: color-mix(in srgb, var(--accent-blue) 40%, transparent)`
- Hidden when `messages.length === 0` (empty state shown instead)

### 6.6 Empty State (inside drawer)

When no messages yet, the message history area shows centered content:
- `MessageSquare` icon `48px var(--text-muted)`
- "Ask anything about your Azure infrastructure" — `14px var(--text-secondary)`
- Chips rendered in a `display: flex; flex-wrap: wrap; gap: 8px; justify-content: center` grid (2–3 per row depending on text) — more inviting than a horizontal scroll bar

### 6.7 ProposalCard (inside drawer)

- Full width within bubble flow (agent side, no avatar)
- `border-left: 4px solid var(--accent-orange)`, `background: var(--bg-subtle)`, `border: 1px solid var(--border)`, `border-radius: 8px`, `padding: 12px`
- Header: "Approval Required" `13px 600 --text-primary` + action summary `font-mono 12px --text-secondary`
- Body: resource list and proposed change details, `13px --text-secondary`
- Footer: "Approve" button (`background: var(--accent-green)`, white text) + "Reject" button (`background: var(--accent-red)`, white text), each with existing confirmation dialog

### 6.8 Input Area

- `background: var(--bg-surface-raised)`, `border-top: 1px solid var(--border)`, `padding: 12px`
- `Textarea`: auto-resize 1–4 lines, `background: var(--bg-subtle)`, `border: 1px solid var(--border)`, `border-radius: 8px`, `font-size: 14px`, `padding: 8px 12px`; `Enter` sends, `Shift+Enter` newlines
- Send button: icon-only `→` arrow (`SendHorizonal` lucide icon), `32px` circle, `background: var(--accent-blue)` when enabled, `var(--bg-subtle)` + `var(--text-muted)` when disabled/empty

---

## 7. Theme Toggle Behavior

- **Provider location:** `ThemeProvider` wraps at the `providers.tsx` level, outside `MsalProvider`, so login page, desktop gate, and main app all inherit the theme.
- **On mount:** Read `localStorage.getItem('aap-theme')`. If null, use `window.matchMedia('(prefers-color-scheme: dark)').matches` to set initial theme. Apply `.dark` class to `<html>`.
- **On toggle:** Flip `.dark` class on `<html>` + write `'light'` or `'dark'` to `localStorage('aap-theme')`.
- **Context:** `ThemeProvider` exposes `{ theme: 'light' | 'dark', toggleTheme: () => void }` via `useTheme()` hook.
- **CSS mechanism:** All color tokens switch automatically via `:root` vs `.dark` CSS custom properties — no JS-driven inline styles needed.

---

## 8. Component Change Summary

| Component | Change Type | Notes |
|-----------|-------------|-------|
| `AppLayout.tsx` | Major rewrite | Remove resizable panels; add TopNav + ChatFAB + ChatDrawer; `selectedIncidentId` preserved in AppStateContext |
| `globals.css` | Major rewrite | New token set, shadcn alias bridge, dark mode tokens, JetBrains Mono variable, update `.chat-prose` code block bg to use tokens |
| `app/layout.tsx` | Minor update | Add `JetBrains_Mono` font loading alongside Inter |
| `app/providers.tsx` | Minor update | Add `ThemeProvider` wrapper (outermost) |
| `DashboardPanel.tsx` | Moderate rewrite | Custom ARIA tab bar replaces shadcn Tabs; content padding; card wrapping; exposes `alertCount` via AppStateContext |
| `ChatPanel.tsx` | Renamed → `ChatDrawer.tsx` | Drawer layout, slide animation, backdrop; error bubble styling |
| `ChatInput.tsx` | Minor update | Auto-resize textarea; icon-only send button |
| `ChatBubble.tsx` | Moderate update | New bubble styling, avatar, timestamp-on-hover, error state variant |
| `UserBubble.tsx` | Moderate update | New bubble shape and colors |
| `AlertFeed.tsx` | Moderate update | Severity stripe rows; skeleton loader; updates `AppStateContext.alertCount` |
| `AlertFilters.tsx` | Minor update | Compact pill selects |
| `AuditLogViewer.tsx` | Moderate update | Mono timestamps, agent chip styling, outcome badge colors |
| `ObservabilityTab.tsx` | Minor update | Surface card wrapper, mono metric values, trend arrows |
| `MetricCard.tsx` | Minor update | Surface card treatment, mono value typography |
| `AgentLatencyCard.tsx` | Minor update | Mono values, surface card |
| `PipelineLagCard.tsx` | Minor update | Mono values, surface card |
| `ApprovalQueueCard.tsx` | Minor update | Mono values, surface card |
| `ActiveErrorsCard.tsx` | Minor update | Error color tokens, surface card |
| `TimeRangeSelector.tsx` | Minor update | Token-based styling |
| `TopologyTab.tsx` | Minor update | Category-colored icons, larger hit targets |
| `ResourcesTab.tsx` | Minor update | Category-colored type badges |
| `ProposalCard.tsx` | Minor update | Orange border, new button colors |
| `ThinkingIndicator.tsx` | Minor update | `--accent-blue` dots |
| `AuthenticatedApp.tsx` | Minor update | Update to use new shadcn alias tokens (inherits automatically via bridge) |
| `DesktopOnlyGate.tsx` | Minor update | Update to use new shadcn alias tokens (inherits automatically via bridge) |
| **New:** `TopNav.tsx` | New component | App chrome bar; always dark; breadcrumb, NavSubscriptionPill, refresh, theme toggle, bell, avatar |
| **New:** `NavSubscriptionPill.tsx` | New component | Thin trigger wrapper for existing SubscriptionSelector popover; always-dark nav styling |
| **New:** `ChatDrawerProvider.tsx` | New component | `AppStateContext` — drawer open state, chat state, alertCount, selectedIncidentId |
| **New:** `ThemeProvider.tsx` | New component | Theme context; wraps at providers.tsx level |
| **New:** `ChatFAB.tsx` | New component | Floating action button; reads drawerOpen + isStreaming from AppStateContext |

---

## 9. Out of Scope

- No changes to API routes, data fetching, or business logic
- No mobile/responsive design (desktop-only gate remains)
- No dark mode for the nav bar (always dark by design)
- No animation beyond drawer slide + FAB pulse + thinking dots
- `TraceTree` component remains unused (existing behavior preserved)
- Teams integration components not touched
- Notification bell count is wired via `AppStateContext` — this is a minor state-plumbing change, not a logic change (no new fetches)
