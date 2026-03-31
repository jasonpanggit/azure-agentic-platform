# Web UI SaaS Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Azure AIOps web UI from a plain shadcn prototype into a polished Datadog/Grafana-style SaaS product with a full-width dashboard, collapsible AI chat drawer, always-dark top nav, and consistent light/dark theme.

**Architecture:** Remove `react-resizable-panels` and replace with sticky top nav + full-width dashboard + fixed chat drawer sliding in from the right. `AppStateContext` holds shared state (drawer open, alert count, selected incident, subscriptions, all chat state). `ThemeProvider` manages `.dark` class on `<html>` with localStorage persistence.

**Tech Stack:** Next.js 15 App Router, Tailwind v4 (`@theme` block), shadcn/ui new-york, Radix UI, lucide-react, react-markdown, MSAL.

**Spec:** `docs/superpowers/specs/2026-03-31-web-ui-saas-redesign.md`

---

## Chunk 1: Design System Foundation

### Task 1: Rewrite globals.css + update layout.tsx

**Files:**
- Modify: `services/web-ui/app/globals.css`
- Modify: `services/web-ui/app/layout.tsx`

- [ ] **Step 1: Create feature branch**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git checkout -b feature/web-ui-saas-redesign
```

Expected: `Switched to a new branch 'feature/web-ui-saas-redesign'`

- [ ] **Step 2: Rewrite globals.css**

Replace the entire file with:

```css
@import "tailwindcss";

@theme {
  /* shadcn token bridge — no hsl() wrappers, hex values pass through var() directly */
  --color-background: var(--bg-canvas);
  --color-foreground: var(--text-primary);
  --color-card: var(--bg-surface);
  --color-card-foreground: var(--text-primary);
  --color-popover: var(--bg-surface-raised);
  --color-popover-foreground: var(--text-primary);
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
  --radius: 0.5rem;

  /* Font families */
  --font-sans: var(--font-inter), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-jetbrains-mono), ui-monospace, "JetBrains Mono", monospace;

  /* Animations */
  --animate-blink-cursor: blink-cursor 1.06s step-end infinite;
  --animate-pulse-dot: pulse-dot 1.4s ease-in-out infinite;

  @keyframes blink-cursor {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }

  @keyframes pulse-dot {
    0%, 80%, 100% { opacity: 0; }
    40% { opacity: 1; }
  }
}

@layer base {
  :root {
    --bg-canvas: #F4F5F7;
    --bg-surface: #FFFFFF;
    --bg-surface-raised: #FFFFFF;
    --bg-subtle: #F0F2F5;
    --bg-nav: #0D1117;
    --bg-nav-pill: #1C2333;
    --border-nav: #30363D;
    --border: #DDE1E7;
    --border-subtle: #EBEDF0;
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
    --bg-canvas: #0D1117;
    --bg-surface: #161B22;
    --bg-surface-raised: #1C2333;
    --bg-subtle: #21262D;
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
    /* Nav tokens unchanged — always dark */
  }

  * { border-color: var(--border); }
  body { background-color: var(--bg-canvas); color: var(--text-primary); }
}

/* Chat prose — used by ChatBubble for agent markdown */
.chat-prose { font-size: 0.875rem; line-height: 1.6; color: var(--text-primary); }
.chat-prose p { margin-top: 0; margin-bottom: 0.5rem; }
.chat-prose p:last-child { margin-bottom: 0; }
.chat-prose ul, .chat-prose ol { padding-left: 1.25rem; margin-bottom: 0.5rem; }
.chat-prose li { margin-bottom: 0.25rem; }
.chat-prose strong { font-weight: 600; color: var(--text-primary); }
.chat-prose a { color: var(--accent-blue); text-decoration: underline; text-underline-offset: 2px; }
.chat-prose a:hover { opacity: 0.8; }
.chat-prose code {
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.1rem 0.35rem;
  color: var(--text-primary);
}
.chat-prose pre {
  background-color: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  overflow-x: auto;
  margin-bottom: 0.75rem;
  font-size: 0.8125rem;
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.chat-prose pre code { background: none; border: none; padding: 0; font-size: inherit; }
.chat-prose table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; margin-bottom: 0.75rem; }
.chat-prose th { text-align: left; padding: 0.375rem 0.75rem; background-color: var(--bg-subtle); border: 1px solid var(--border); font-weight: 600; color: var(--text-primary); }
.chat-prose td { padding: 0.375rem 0.75rem; border: 1px solid var(--border); color: var(--text-secondary); }
.chat-prose tr:nth-child(even) td { background-color: var(--bg-subtle); }
.chat-prose h1, .chat-prose h2, .chat-prose h3 { font-weight: 600; color: var(--text-primary); margin-top: 1rem; margin-bottom: 0.375rem; line-height: 1.4; }
.chat-prose h1 { font-size: 1rem; }
.chat-prose h2 { font-size: 0.9375rem; }
.chat-prose h3 { font-size: 0.875rem; }

@media (prefers-reduced-motion: reduce) {
  .animate-blink-cursor, .animate-pulse-dot { animation: none; }
}
```

- [ ] **Step 3: Update layout.tsx to load JetBrains Mono and add suppressHydrationWarning**

Replace the entire file:

```tsx
import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' })
const jetbrainsMono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-jetbrains-mono' })

export const metadata: Metadata = {
  title: 'Azure AIOps',
  description: 'Azure Agentic Platform — AI Operations Dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable}`}
    >
      <body className="min-h-screen font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
```

`suppressHydrationWarning` is required because `ThemeProvider` (Task 2) applies `.dark` on the client, which would otherwise cause a React hydration mismatch warning.

- [ ] **Step 4: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/app/globals.css services/web-ui/app/layout.tsx
git commit -m "feat: new design token system with shadcn bridge, dark mode, and JetBrains Mono"
```

---

### Task 2: Create ThemeProvider

**Files:**
- Create: `services/web-ui/lib/theme-context.tsx`
- Modify: `services/web-ui/app/providers.tsx`

- [ ] **Step 1: Add dark-mode flash prevention script to layout.tsx**

Edit `services/web-ui/app/layout.tsx` — inside `<html>` before `<body>`, add an inline script that applies the `.dark` class before React hydrates, preventing flash:

```tsx
// Add this between <html ...> and <body ...>:
<script
  dangerouslySetInnerHTML={{
    __html: `(function(){try{var t=localStorage.getItem('aap-theme');if(t==='dark'||(t===null&&window.matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark')}}catch(e){}})()`,
  }}
/>
```

The full layout becomes:

```tsx
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <script
        dangerouslySetInnerHTML={{
          __html: `(function(){try{var t=localStorage.getItem('aap-theme');if(t==='dark'||(t===null&&window.matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark')}}catch(e){}})()`,
        }}
      />
      <body className="min-h-screen font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
```

- [ ] **Step 2: Create `services/web-ui/lib/theme-context.tsx`**

```tsx
'use client'

import { createContext, useContext, useEffect, useState } from 'react'

type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue>({ theme: 'light', toggleTheme: () => {} })

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>('light')

  useEffect(() => {
    // Read current class state set by the inline script (avoids a second localStorage read)
    const isDark = document.documentElement.classList.contains('dark')
    setTheme(isDark ? 'dark' : 'light')
  }, [])

  function toggleTheme() {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      localStorage.setItem('aap-theme', next)
      document.documentElement.classList.toggle('dark', next === 'dark')
      return next
    })
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
```

- [ ] **Step 3: Replace providers.tsx with ThemeProvider + AppStateProvider wrappers**

Replace the entire file (AppStateProvider added here too — defined in Task 3 but providers.tsx must be complete):

```tsx
'use client'

import { useEffect, useState } from 'react'
import { MsalProvider } from '@azure/msal-react'
import { getMsalInstance } from '@/lib/msal-instance'
import { IPublicClientApplication } from '@azure/msal-browser'
import { ThemeProvider } from '@/lib/theme-context'
import { AppStateProvider } from '@/lib/app-state-context'

export function Providers({ children }: { children: React.ReactNode }) {
  const [msalInstance, setMsalInstance] = useState<IPublicClientApplication | null>(null)

  useEffect(() => {
    let cancelled = false
    const timeout = setTimeout(() => {
      if (!cancelled) getMsalInstance().then((i) => { if (!cancelled) setMsalInstance(i) })
    }, 5000)
    getMsalInstance().then((i) => {
      clearTimeout(timeout)
      if (!cancelled) setMsalInstance(i)
    })
    return () => { cancelled = true }
  }, [])

  if (!msalInstance) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Loading...</p>
      </div>
    )
  }

  return (
    <ThemeProvider>
      <AppStateProvider>
        <MsalProvider instance={msalInstance}>
          {children}
        </MsalProvider>
      </AppStateProvider>
    </ThemeProvider>
  )
}
```

Note: `AppStateProvider` will be created in Task 3. TypeScript will error until then — that's expected. Fix after Task 3.

- [ ] **Step 4: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/lib/theme-context.tsx services/web-ui/app/providers.tsx services/web-ui/app/layout.tsx
git commit -m "feat: ThemeProvider with flash-prevention inline script and localStorage persistence"
```

---

### Task 3: Create AppStateContext

**Files:**
- Create: `services/web-ui/lib/app-state-context.tsx`

The `Message` type is imported from `@/types/sse` (already defined there with `id`, `role`, `agentName`, `content`, `isStreaming`, `approvalGate`, `timestamp`). Do NOT redefine it.

- [ ] **Step 1: Create `services/web-ui/lib/app-state-context.tsx`**

```tsx
'use client'

import { createContext, useContext, useRef, useState } from 'react'
import type { Message } from '@/types/sse'

interface AppStateContextValue {
  drawerOpen: boolean
  setDrawerOpen: (open: boolean) => void
  messages: Message[]
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  isStreaming: boolean
  setIsStreaming: (v: boolean) => void
  threadId: string | null
  setThreadId: (id: string | null) => void
  runId: string | null
  setRunId: (id: string | null) => void
  runKey: number
  setRunKey: React.Dispatch<React.SetStateAction<number>>
  currentAgentRef: React.MutableRefObject<string>
  alertCount: number
  setAlertCount: (n: number) => void
  selectedIncidentId: string | null
  setSelectedIncidentId: (id: string | null) => void
  selectedSubscriptions: string[]
  setSelectedSubscriptions: (subs: string[]) => void
}

const AppStateContext = createContext<AppStateContextValue | null>(null)

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [runKey, setRunKey] = useState(0)
  const currentAgentRef = useRef('Orchestrator')
  const [alertCount, setAlertCount] = useState(0)
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null)
  const [selectedSubscriptions, setSelectedSubscriptions] = useState<string[]>([])

  return (
    <AppStateContext.Provider value={{
      drawerOpen, setDrawerOpen,
      messages, setMessages,
      isStreaming, setIsStreaming,
      threadId, setThreadId,
      runId, setRunId,
      runKey, setRunKey,
      currentAgentRef,
      alertCount, setAlertCount,
      selectedIncidentId, setSelectedIncidentId,
      selectedSubscriptions, setSelectedSubscriptions,
    }}>
      {children}
    </AppStateContext.Provider>
  )
}

export function useAppState() {
  const ctx = useContext(AppStateContext)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
```

- [ ] **Step 2: Verify TypeScript compiles cleanly**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: No errors (providers.tsx now resolves AppStateProvider import).

- [ ] **Step 3: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/lib/app-state-context.tsx
git commit -m "feat: AppStateContext — shared drawer, chat, subscriptions, and dashboard state"
```

---

## Chunk 2: Top Navigation Bar

### Task 4: Update SubscriptionSelector + create NavSubscriptionPill

**Files:**
- Modify: `services/web-ui/components/SubscriptionSelector.tsx`
- Create: `services/web-ui/components/NavSubscriptionPill.tsx`

The existing `SubscriptionSelector` has props `selected`, `onChange`, `onLoad` and renders its own trigger button inside a `Popover`. We need to add an optional `trigger` prop so `NavSubscriptionPill` can supply a custom trigger.

- [ ] **Step 1: Add `trigger` prop to SubscriptionSelector**

In `services/web-ui/components/SubscriptionSelector.tsx`, make these changes:

1. Add `trigger?: React.ReactNode` to the props interface:

```tsx
interface SubscriptionSelectorProps {
  selected: string[];
  onChange: (ids: string[]) => void;
  onLoad?: (ids: string[]) => void;
  trigger?: React.ReactNode;  // ← add this
}
```

2. Update the function signature to accept `trigger`:

```tsx
export function SubscriptionSelector({ selected, onChange, onLoad, trigger }: SubscriptionSelectorProps) {
```

3. Replace the existing `<PopoverTrigger asChild>` block (the button with "Filter subscriptions...") with:

```tsx
<PopoverTrigger asChild>
  {trigger ?? (
    <button className="flex items-center gap-2 rounded-md border border-input px-3 py-1.5 text-sm bg-background hover:bg-accent">
      Filter subscriptions...
      <ChevronsUpDown className="h-3.5 w-3.5 opacity-50" />
    </button>
  )}
</PopoverTrigger>
```

- [ ] **Step 2: Create `services/web-ui/components/NavSubscriptionPill.tsx`**

```tsx
'use client'

import { Cloud, ChevronDown } from 'lucide-react'
import { SubscriptionSelector } from './SubscriptionSelector'
import { useAppState } from '@/lib/app-state-context'

export function NavSubscriptionPill() {
  const { selectedSubscriptions, setSelectedSubscriptions } = useAppState()
  const count = selectedSubscriptions.length

  return (
    <SubscriptionSelector
      selected={selectedSubscriptions}
      onChange={setSelectedSubscriptions}
      onLoad={setSelectedSubscriptions}
      trigger={
        <button
          className="flex items-center gap-2 rounded-md px-3 h-8 text-sm text-white/90 hover:opacity-85 transition-opacity"
          style={{ background: 'var(--bg-nav-pill)', border: '1px solid var(--border-nav)' }}
        >
          <Cloud className="h-4 w-4 text-white/60" />
          <span>{count === 0 ? 'All subscriptions' : `${count} subscription${count !== 1 ? 's' : ''}`}</span>
          <ChevronDown className="h-3.5 w-3.5 text-white/60" />
        </button>
      }
    />
  )
}
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/SubscriptionSelector.tsx services/web-ui/components/NavSubscriptionPill.tsx
git commit -m "feat: add NavSubscriptionPill with always-dark nav styling"
```

---

### Task 5: Create TopNav

**Files:**
- Create: `services/web-ui/components/TopNav.tsx`

Note: The `isRefreshing` prop is wired but not yet populated from child components — this is a known deferred item. The spinner renders correctly; it just won't auto-activate until a future task wires fetch states into AppStateContext.

- [ ] **Step 1: Check if DropdownMenu shadcn component exists**

```bash
ls /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/components/ui/dropdown-menu.tsx 2>/dev/null || echo "MISSING"
```

If MISSING:
```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx shadcn@latest add dropdown-menu
```

- [ ] **Step 2: Create `services/web-ui/components/TopNav.tsx`**

```tsx
'use client'

import { Bell, RefreshCw, Sun, Moon, LogOut } from 'lucide-react'
import { useMsal } from '@azure/msal-react'
import { useTheme } from '@/lib/theme-context'
import { useAppState } from '@/lib/app-state-context'
import { NavSubscriptionPill } from './NavSubscriptionPill'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'

interface TopNavProps {
  activeTab: string
  isRefreshing?: boolean
}

export function TopNav({ activeTab, isRefreshing = false }: TopNavProps) {
  const { theme, toggleTheme } = useTheme()
  const { alertCount } = useAppState()
  const { accounts, instance } = useMsal()

  const account = accounts[0]
  const initials = account?.name
    ? account.name.split(' ').map((n: string) => n[0]).slice(0, 2).join('').toUpperCase()
    : 'U'

  return (
    <nav
      className="flex items-center justify-between px-4 h-12 w-full sticky top-0 z-50 flex-shrink-0"
      style={{ background: 'var(--bg-nav)' }}
    >
      {/* Left: logo + separator + breadcrumb */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold text-white"
            style={{ background: 'var(--accent-blue)' }}
          >
            A
          </div>
          <span className="text-sm font-semibold text-white">Azure AIOps</span>
        </div>
        <div className="w-px h-5" style={{ background: 'var(--border-nav)' }} />
        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
          {activeTab}
        </span>
      </div>

      {/* Center: subscription selector */}
      <NavSubscriptionPill />

      {/* Right: controls */}
      <div className="flex items-center gap-1">
        <button
          className="w-8 h-8 flex items-center justify-center rounded"
          style={{ color: 'var(--text-muted)' }}
          disabled
          aria-label="Refresh status"
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
        </button>

        <button
          onClick={toggleTheme}
          className="w-8 h-8 flex items-center justify-center rounded transition-colors"
          style={{ color: 'var(--text-muted)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = '#FFFFFF' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)' }}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        <button
          className="w-8 h-8 flex items-center justify-center rounded relative"
          style={{ color: 'var(--text-muted)' }}
          aria-label={`${alertCount} alerts`}
        >
          <Bell className="h-4 w-4" />
          {alertCount > 0 && (
            <span
              className="absolute top-1 right-1 min-w-[14px] h-3.5 rounded-full text-[9px] font-bold text-white flex items-center justify-center px-0.5"
              style={{ background: 'var(--accent-red)', lineHeight: 1 }}
            >
              {alertCount > 99 ? '99+' : alertCount}
            </span>
          )}
        </button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold text-white ml-1"
              style={{ background: 'var(--accent-blue)' }}
              aria-label="User menu"
            >
              {initials}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuLabel>
              <div className="font-semibold text-sm">{account?.name ?? 'User'}</div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                {account?.username ?? ''}
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => instance.logoutRedirect()}
              className="cursor-pointer"
              style={{ color: 'var(--accent-red)' }}
            >
              <LogOut className="h-4 w-4 mr-2" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </nav>
  )
}
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/TopNav.tsx services/web-ui/components/ui/
git commit -m "feat: TopNav with theme toggle, alert bell, subscription pill, and user avatar"
```

---

## Chunk 3: Chat Drawer

### Task 6: Create ChatFAB

**Files:**
- Create: `services/web-ui/components/ChatFAB.tsx`

- [ ] **Step 1: Create `services/web-ui/components/ChatFAB.tsx`**

```tsx
'use client'

import { MessageSquare, X } from 'lucide-react'
import { useAppState } from '@/lib/app-state-context'

export function ChatFAB() {
  const { drawerOpen, setDrawerOpen, isStreaming } = useAppState()

  return (
    <button
      onClick={() => setDrawerOpen(!drawerOpen)}
      className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full flex items-center justify-center text-white transition-transform hover:scale-105 active:scale-95"
      style={{
        background: 'var(--accent-blue)',
        boxShadow: isStreaming
          ? '0 0 0 4px color-mix(in srgb, var(--accent-blue) 30%, transparent), 0 4px 12px rgba(0,0,0,0.3)'
          : '0 4px 12px rgba(0,0,0,0.3)',
        animation: isStreaming ? 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite' : 'none',
      }}
      aria-label={drawerOpen ? 'Close AI chat' : 'Open AI chat'}
    >
      {drawerOpen ? <X className="h-6 w-6" /> : <MessageSquare className="h-6 w-6" />}
    </button>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/ChatFAB.tsx
git commit -m "feat: ChatFAB floating action button"
```

---

### Task 7: Rewrite ChatBubble and UserBubble

**Files:**
- Modify: `services/web-ui/components/ChatBubble.tsx`
- Modify: `services/web-ui/components/UserBubble.tsx`

- [ ] **Step 1: Rewrite `services/web-ui/components/ChatBubble.tsx`**

```tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface ChatBubbleProps {
  agentName: string
  content: string
  isStreaming?: boolean
  timestamp?: string
  isError?: boolean
}

export function ChatBubble({ agentName, content, isStreaming, timestamp, isError = false }: ChatBubbleProps) {
  if (isError) {
    return (
      <div className="group flex flex-col mb-3 max-w-[90%] self-start">
        <div
          className="rounded-lg px-3 py-2.5"
          style={{
            background: 'color-mix(in srgb, var(--accent-red) 10%, transparent)',
            borderLeft: '4px solid var(--accent-red)',
            border: '1px solid var(--border)',
            borderLeftWidth: '4px',
          }}
        >
          <div className="text-[11px] font-semibold mb-1 uppercase tracking-wide" style={{ color: 'var(--accent-red)' }}>
            System
          </div>
          <p className="text-sm" style={{ color: 'var(--text-primary)' }}>{content}</p>
        </div>
        {timestamp && (
          <span className="text-[11px] mt-1 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--text-muted)' }}>
            {timestamp}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="group flex items-start gap-2 mb-3 max-w-[90%] self-start">
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold flex-shrink-0 mt-0.5"
        style={{ background: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)', color: 'var(--accent-blue)' }}
      >
        AI
      </div>
      <div className="flex flex-col min-w-0">
        <div
          className="rounded-2xl rounded-tl-sm px-3 py-2.5"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
        >
          <div className="chat-prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            {isStreaming && (
              <span
                className="inline-block w-0.5 h-3.5 ml-0.5 animate-blink-cursor"
                style={{ background: 'var(--text-primary)' }}
              />
            )}
          </div>
        </div>
        {timestamp && (
          <span className="text-[11px] mt-1 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--text-muted)' }}>
            {timestamp}
          </span>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Rewrite `services/web-ui/components/UserBubble.tsx`**

```tsx
interface UserBubbleProps {
  content: string
  timestamp?: string
}

export function UserBubble({ content, timestamp }: UserBubbleProps) {
  return (
    <div className="group flex flex-col items-end mb-3 ml-auto max-w-[85%]">
      <div
        className="rounded-2xl rounded-br-sm px-3 py-2.5 text-sm text-white"
        style={{ background: 'var(--accent-blue)' }}
      >
        {content}
      </div>
      {timestamp && (
        <span className="text-[11px] mt-1 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--text-muted)' }}>
          {timestamp}
        </span>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/ChatBubble.tsx services/web-ui/components/UserBubble.tsx
git commit -m "feat: redesign chat bubbles with AI avatar, .chat-prose, error state, and new shapes"
```

---

### Task 8: Rewrite ThinkingIndicator and ChatInput

**Files:**
- Modify: `services/web-ui/components/ThinkingIndicator.tsx`
- Modify: `services/web-ui/components/ChatInput.tsx`

- [ ] **Step 1: Rewrite `services/web-ui/components/ThinkingIndicator.tsx`**

```tsx
export function ThinkingIndicator() {
  return (
    <div className="flex items-start gap-2 mb-3 max-w-[90%]">
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold flex-shrink-0 mt-0.5"
        style={{ background: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)', color: 'var(--accent-blue)' }}
      >
        AI
      </div>
      <div
        className="rounded-2xl rounded-tl-sm px-3 py-3 flex items-center gap-1.5"
        style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
      >
        {[0, 0.2, 0.4].map((delay, i) => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full animate-pulse-dot"
            style={{ background: 'var(--accent-blue)', animationDelay: `${delay}s` }}
          />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Rewrite `services/web-ui/components/ChatInput.tsx`**

Note: The existing `ChatInput` has `onSend: (message: string) => void` prop. The new version separates `value`/`onChange`/`onSubmit` so `ChatDrawer` can control the input via AppStateContext. This is a prop interface change — `ChatDrawer` will use the new interface; `ChatPanel.tsx` (being deleted in Task 12) used the old one.

```tsx
'use client'

import { useRef, useEffect } from 'react'
import { SendHorizonal } from 'lucide-react'

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({
  value, onChange, onSubmit, disabled = false,
  placeholder = 'Ask about any Azure resource...',
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [value])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!disabled && value.trim()) onSubmit()
    }
  }

  return (
    <div
      className="flex items-end gap-2 px-3 py-3"
      style={{ background: 'var(--bg-surface-raised)', borderTop: '1px solid var(--border)' }}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        rows={1}
        className="flex-1 resize-none text-sm rounded-lg px-3 py-2 outline-none transition-colors min-h-[36px] max-h-[120px]"
        style={{
          background: 'var(--bg-subtle)',
          border: '1px solid var(--border)',
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-sans)',
        }}
      />
      <button
        onClick={onSubmit}
        disabled={disabled || !value.trim()}
        className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-colors"
        style={{
          background: disabled || !value.trim() ? 'var(--bg-subtle)' : 'var(--accent-blue)',
          color: disabled || !value.trim() ? 'var(--text-muted)' : '#FFFFFF',
          border: '1px solid var(--border)',
        }}
        aria-label="Send message"
      >
        <SendHorizonal className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: TypeScript will report errors because `ChatPanel.tsx` still uses old `ChatInput` `onSend` prop. That's expected — `ChatPanel` is deleted in Task 12.

- [ ] **Step 4: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/ThinkingIndicator.tsx services/web-ui/components/ChatInput.tsx
git commit -m "feat: redesign ThinkingIndicator and ChatInput with new token system"
```

---

### Task 9: Create ChatDrawer

**Files:**
- Create: `services/web-ui/components/ChatDrawer.tsx`

The SSE logic is migrated from `ChatPanel.tsx`. The full implementation is provided below — do NOT copy from ChatPanel manually; use the code here which has been adapted for AppStateContext.

- [ ] **Step 1: Create `services/web-ui/components/ChatDrawer.tsx`**

```tsx
'use client'

import { useCallback, useEffect, useRef } from 'react'
import { MessageSquare, X } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useSSE, SSEEvent } from '@/lib/use-sse'
import { useAppState } from '@/lib/app-state-context'
import type { ApprovalGateTracePayload } from '@/types/sse'
import { ChatBubble } from './ChatBubble'
import { UserBubble } from './UserBubble'
import { ChatInput } from './ChatInput'
import { ThinkingIndicator } from './ThinkingIndicator'
import { ProposalCard } from './ProposalCard'

const QUICK_EXAMPLES = [
  'Show my virtual machines',
  'List VMs with high CPU usage',
  'Are there any active alerts?',
  'Show unhealthy resources',
  'Which VMs are stopped?',
  'Check storage account health',
  'Summarize recent incidents',
]

export function ChatDrawer() {
  const {
    drawerOpen, setDrawerOpen,
    messages, setMessages,
    isStreaming, setIsStreaming,
    threadId, setThreadId,
    runId, setRunId,
    runKey, setRunKey,
    currentAgentRef,
    input, setInput,  // Note: add input/setInput to AppStateContext if not present
    selectedSubscriptions,
  } = useAppState()

  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Fallback if input/setInput not yet in AppStateContext — use local state
  // (Remove this block after confirming AppStateContext has input/setInput)
  const [localInput, setLocalInput] = useState('')
  const inputValue = typeof input !== 'undefined' ? input : localInput
  const setInputValue = typeof setInput !== 'undefined' ? setInput : setLocalInput

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── SSE: token stream ──
  const handleTokenEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>
    if (data.type === 'done') {
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.isStreaming) return [...prev.slice(0, -1), { ...last, isStreaming: false }]
        return prev
      })
      setIsStreaming(false)
      return
    }
    const delta = (data.delta as string) || ''
    const agent = (data.agent as string) || currentAgentRef.current
    currentAgentRef.current = agent
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.role === 'assistant' && last.isStreaming) {
        return [...prev.slice(0, -1), { ...last, content: last.content + delta, agentName: agent }]
      }
      return [...prev, {
        id: `msg-${event.seq}`,
        role: 'assistant' as const,
        agentName: agent,
        content: delta,
        isStreaming: true,
        timestamp: new Date().toLocaleTimeString(),
      }]
    })
  }, [setMessages, setIsStreaming, currentAgentRef])

  // ── SSE: trace stream ──
  const handleTraceEvent = useCallback((event: SSEEvent) => {
    const data = event.data as Record<string, unknown>
    if (data.type === 'approval_gate') {
      const approvalGate = data as unknown as ApprovalGateTracePayload
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.role === 'assistant') {
          return [...prev.slice(0, -1), { ...last, approvalGate, isStreaming: false }]
        }
        return [...prev, {
          id: `msg-gate-${event.seq}`,
          role: 'assistant' as const,
          agentName: currentAgentRef.current,
          content: 'A remediation action requires your approval:',
          isStreaming: false,
          approvalGate,
          timestamp: new Date().toLocaleTimeString(),
        }]
      })
      setIsStreaming(false)
    }
    if (data.type === 'done') {
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.isStreaming) return [...prev.slice(0, -1), { ...last, isStreaming: false }]
        return prev
      })
      setIsStreaming(false)
    }
  }, [setMessages, setIsStreaming, currentAgentRef])

  useSSE({ threadId, runId, streamType: 'token', onEvent: handleTokenEvent, runKey })
  useSSE({ threadId, runId, streamType: 'trace', onEvent: handleTraceEvent, runKey })

  // ── Send message ──
  const handleSend = useCallback(async () => {
    const message = inputValue.trim()
    if (!message || isStreaming) return
    setInputValue('')
    setMessages((prev) => [...prev, {
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: new Date().toLocaleTimeString(),
    }])
    setIsStreaming(true)
    try {
      const res = await fetch('/api/proxy/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, thread_id: threadId, subscription_ids: selectedSubscriptions }),
      })
      if (res.ok) {
        const data = await res.json()
        setRunId(data.run_id ?? null)
        if (!threadId) { setThreadId(data.thread_id) }
        else { setRunKey((k) => k + 1) }
      } else {
        const data = await res.json().catch(() => ({}))
        const errorMsg = (data as { error?: string }).error ?? `Request failed (${res.status})`
        setIsStreaming(false)
        setMessages((prev) => [...prev, {
          id: `error-${Date.now()}`,
          role: 'assistant',
          agentName: 'System',
          content: errorMsg,
          isStreaming: false,
          timestamp: new Date().toLocaleTimeString(),
        }])
      }
    } catch {
      setIsStreaming(false)
      setMessages((prev) => [...prev, {
        id: `error-${Date.now()}`,
        role: 'assistant',
        agentName: 'System',
        content: 'Network error. Please check your connection.',
        isStreaming: false,
        timestamp: new Date().toLocaleTimeString(),
      }])
    }
  }, [inputValue, isStreaming, threadId, selectedSubscriptions, setInputValue, setMessages, setIsStreaming, setRunId, setThreadId, setRunKey])

  // ── Approvals ──
  const handleApprove = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      })
    } catch { /* ProposalCard handles its own error state */ }
  }, [])

  const handleReject = useCallback(async (approvalId: string) => {
    try {
      await fetch(`/api/proxy/approvals/${approvalId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decided_by: 'current_user' }),
      })
    } catch { /* ProposalCard handles its own error state */ }
  }, [])

  function handleExampleClick(ex: string) {
    setInputValue(ex)
  }

  return (
    <>
      {/* Backdrop */}
      {drawerOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 transition-opacity"
          style={{ top: '48px' }}
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* Drawer panel */}
      <div
        className="fixed right-0 z-45 flex flex-col transition-transform duration-300 ease-out"
        style={{
          top: '48px',
          width: '420px',
          height: 'calc(100vh - 48px)',
          background: 'var(--bg-surface)',
          borderLeft: '1px solid var(--border)',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.25)',
          transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 flex-shrink-0"
          style={{ height: '48px', background: 'var(--bg-surface-raised)', borderBottom: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: 'var(--accent-green)' }} />
            <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Azure AI</span>
          </div>
          <span
            className="text-[11px] px-2 py-0.5 rounded font-mono"
            style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
          >
            GPT-4o
          </span>
          <button
            onClick={() => setDrawerOpen(false)}
            className="w-7 h-7 flex items-center justify-center rounded transition-colors"
            style={{ color: 'var(--text-muted)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--text-primary)'
              e.currentTarget.style.background = 'var(--bg-subtle)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--text-muted)'
              e.currentTarget.style.background = 'transparent'
            }}
            aria-label="Close chat"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Message area or empty state */}
        {messages.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6 gap-4">
            <MessageSquare className="h-12 w-12" style={{ color: 'var(--text-muted)' }} />
            <p className="text-sm text-center" style={{ color: 'var(--text-secondary)' }}>
              Ask anything about your Azure infrastructure
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {QUICK_EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => handleExampleClick(ex)}
                  className="text-xs px-3 py-1.5 rounded-md transition-colors"
                  style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'color-mix(in srgb, var(--accent-blue) 10%, transparent)'
                    e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--accent-blue) 40%, transparent)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'var(--bg-subtle)'
                    e.currentTarget.style.borderColor = 'var(--border)'
                  }}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ScrollArea className="flex-1 px-4 py-3">
            <div role="log" aria-live="polite" className="flex flex-col">
              {messages.map((msg) => (
                msg.role === 'user' ? (
                  <UserBubble key={msg.id} content={msg.content} timestamp={msg.timestamp} />
                ) : (
                  <div key={msg.id}>
                    <ChatBubble
                      agentName={msg.agentName || 'Agent'}
                      content={msg.content}
                      isStreaming={msg.isStreaming || false}
                      timestamp={msg.timestamp}
                      isError={msg.agentName === 'System'}
                    />
                    {msg.approvalGate && (
                      <ProposalCard
                        approval={{
                          id: msg.approvalGate.approval_id,
                          status: 'pending',
                          risk_level: msg.approvalGate.proposal.risk_level,
                          expires_at: msg.approvalGate.expires_at,
                          proposal: {
                            description: msg.approvalGate.proposal.description,
                            target_resources: msg.approvalGate.proposal.target_resources,
                            estimated_impact: msg.approvalGate.proposal.estimated_impact,
                            reversibility: 'unknown',
                          },
                        }}
                        onApprove={() => handleApprove(msg.approvalGate!.approval_id)}
                        onReject={() => handleReject(msg.approvalGate!.approval_id)}
                      />
                    )}
                  </div>
                )
              ))}
              {isStreaming && !messages[messages.length - 1]?.isStreaming && <ThinkingIndicator />}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>
        )}

        {/* Quick chips bar (only when conversation active) */}
        {messages.length > 0 && (
          <div
            className="flex items-center gap-2 px-4 overflow-x-auto flex-shrink-0"
            style={{ height: '40px', borderTop: '1px solid var(--border)' }}
          >
            {QUICK_EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setInputValue(ex)}
                className="text-xs px-3 py-1 rounded-md whitespace-nowrap flex-shrink-0 font-medium transition-colors"
                style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
              >
                {ex}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSubmit={handleSend}
          disabled={isStreaming}
        />
      </div>
    </>
  )
}
```

- [ ] **Step 2: Add `input` and `setInput` to AppStateContext if not already present**

Open `services/web-ui/lib/app-state-context.tsx`. Check if `input: string` and `setInput` are in the interface and provider. If not, add them:

In the interface:
```tsx
input: string
setInput: (v: string) => void
```

In the provider body:
```tsx
const [input, setInput] = useState('')
```

In the value object:
```tsx
input, setInput,
```

Then remove the fallback `useState` block from `ChatDrawer.tsx` (lines starting with `// Fallback if input/setInput...`).

- [ ] **Step 3: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/ChatDrawer.tsx services/web-ui/lib/app-state-context.tsx
git commit -m "feat: ChatDrawer with SSE streaming, approval gates, drawer animation, and empty state"
```

---

## Chunk 4: Dashboard Panel Redesign

### Task 10: Redesign DashboardPanel with custom ARIA tab bar

**Files:**
- Modify: `services/web-ui/components/DashboardPanel.tsx`

- [ ] **Step 1: Rewrite `services/web-ui/components/DashboardPanel.tsx`**

```tsx
'use client'

import { useState } from 'react'
import { Bell, ClipboardList, Network, Server, Activity } from 'lucide-react'
import { AlertFeed } from './AlertFeed'
import { AlertFilters } from './AlertFilters'
import { AuditLogViewer } from './AuditLogViewer'
import { TopologyTab } from './TopologyTab'
import { ResourcesTab } from './ResourcesTab'
import { ObservabilityTab } from './ObservabilityTab'
import { useAppState } from '@/lib/app-state-context'

type TabId = 'alerts' | 'audit' | 'topology' | 'resources' | 'observability'

interface FilterState {
  severity: string
  domain: string
  status: string
}

const TABS: { id: TabId; label: string; Icon: React.FC<{ className?: string }> }[] = [
  { id: 'alerts', label: 'Alerts', Icon: Bell },
  { id: 'audit', label: 'Audit', Icon: ClipboardList },
  { id: 'topology', label: 'Topology', Icon: Network },
  { id: 'resources', label: 'Resources', Icon: Server },
  { id: 'observability', label: 'Observability', Icon: Activity },
]

interface DashboardPanelProps {
  onTabChange?: (tab: TabId) => void
}

export function DashboardPanel({ onTabChange }: DashboardPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('alerts')
  const [filters, setFilters] = useState<FilterState>({ severity: 'all', domain: 'all', status: 'all' })
  const { selectedSubscriptions, selectedIncidentId } = useAppState()

  function handleTabChange(tab: TabId) {
    setActiveTab(tab)
    onTabChange?.(tab)
  }

  function handleTabKeyDown(e: React.KeyboardEvent, index: number) {
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      const next = (index + 1) % TABS.length
      handleTabChange(TABS[next].id)
      document.getElementById(`tab-${TABS[next].id}`)?.focus()
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      const prev = (index - 1 + TABS.length) % TABS.length
      handleTabChange(TABS[prev].id)
      document.getElementById(`tab-${TABS[prev].id}`)?.focus()
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ background: 'var(--bg-canvas)' }}>
      {/* Tab bar */}
      <div
        className="flex items-end flex-shrink-0 pl-4"
        role="tablist"
        aria-label="Dashboard sections"
        style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)' }}
      >
        {TABS.map(({ id, label, Icon }, index) => {
          const isActive = activeTab === id
          return (
            <button
              key={id}
              id={`tab-${id}`}
              role="tab"
              aria-selected={isActive}
              aria-controls={`tabpanel-${id}`}
              onClick={() => handleTabChange(id)}
              onKeyDown={(e) => handleTabKeyDown(e, index)}
              className="flex items-center gap-1.5 px-4 py-3 text-[13px] transition-colors outline-none relative"
              style={{
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontWeight: isActive ? 600 : 500,
                borderBottom: isActive ? '2px solid var(--accent-blue)' : '2px solid transparent',
                marginBottom: '-1px',
                background: 'transparent',
              }}
              onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--bg-subtle)' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          )
        })}
      </div>

      {/* Tab panels */}
      <div className="flex-1 overflow-auto p-6">
        <div id="tabpanel-alerts" role="tabpanel" aria-labelledby="tab-alerts" hidden={activeTab !== 'alerts'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
              <AlertFilters filters={filters} onFiltersChange={setFilters} />
            </div>
            <AlertFeed filters={filters} selectedSubscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-audit" role="tabpanel" aria-labelledby="tab-audit" hidden={activeTab !== 'audit'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <AuditLogViewer selectedSubscriptions={selectedSubscriptions} incidentId={selectedIncidentId ?? undefined} />
          </div>
        </div>

        <div id="tabpanel-topology" role="tabpanel" aria-labelledby="tab-topology" hidden={activeTab !== 'topology'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <TopologyTab selectedSubscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-resources" role="tabpanel" aria-labelledby="tab-resources" hidden={activeTab !== 'resources'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <ResourcesTab selectedSubscriptions={selectedSubscriptions} />
          </div>
        </div>

        <div id="tabpanel-observability" role="tabpanel" aria-labelledby="tab-observability" hidden={activeTab !== 'observability'}>
          <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <ObservabilityTab selectedSubscriptions={selectedSubscriptions} />
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

If `AuditLogViewer`, `TopologyTab`, `ResourcesTab`, or `ObservabilityTab` have prop mismatches (they may have used `selectedSubscriptions` from AppLayout via a different prop name), fix their prop interfaces to accept `selectedSubscriptions: string[]`.

- [ ] **Step 3: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/DashboardPanel.tsx
git commit -m "feat: DashboardPanel with custom ARIA tab bar and card-wrapped content areas"
```

---

### Task 11: Upgrade AlertFeed with severity stripes

**Files:**
- Modify: `services/web-ui/components/AlertFeed.tsx`
- Modify: `services/web-ui/components/AlertFilters.tsx`

- [ ] **Step 1: Read AlertFeed.tsx**

```bash
cat /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/components/AlertFeed.tsx
```

Identify: where incidents are filtered, where table rows are rendered, where loading state renders skeletons.

- [ ] **Step 2: Add severity color helper and alertCount wiring to AlertFeed.tsx**

Add this helper above the component function:

```tsx
function getSeverityColor(severity: string): string {
  const s = (severity ?? '').toLowerCase()
  if (s.includes('sev0') || s.includes('critical')) return 'var(--accent-red)'
  if (s.includes('sev1') || s.includes('high')) return 'var(--accent-orange)'
  if (s.includes('sev2') || s.includes('medium')) return 'var(--accent-yellow)'
  if (s.includes('sev3') || s.includes('low')) return 'var(--accent-purple)'
  return 'var(--text-muted)'
}

function formatRelativeTime(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
```

Add `useAppState` import and `setAlertCount` call. Inside the component, after the filtered incidents are computed (find where `filteredIncidents` or equivalent is defined), add:

```tsx
const { setAlertCount } = useAppState()

// After filtering, update the count:
useEffect(() => {
  setAlertCount(filteredIncidents.length)
}, [filteredIncidents.length, setAlertCount])
```

- [ ] **Step 3: Replace table row rendering with severity-striped rows**

Find the existing `<tr>` rows in the table body. Replace each row with:

```tsx
<tr
  key={incident.incident_id || incident.id}
  className="transition-colors cursor-pointer"
  style={{ borderBottom: '1px solid var(--border-subtle)' }}
  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-subtle)' }}
  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
>
  <td className="py-3 pl-0 pr-2" style={{ borderLeft: `4px solid ${getSeverityColor(incident.severity)}`, paddingLeft: '12px' }}>
    <div className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: getSeverityColor(incident.severity) }} />
      <span className="text-[11px] font-medium" style={{ color: getSeverityColor(incident.severity) }}>
        {incident.severity}
      </span>
    </div>
  </td>
  <td className="py-3 px-2">
    <span className="text-[11px] px-2 py-0.5 rounded font-medium" style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}>
      {incident.domain}
    </span>
  </td>
  <td className="py-3 px-2 max-w-[180px]">
    <span className="text-[12px] font-semibold font-mono truncate block" style={{ color: 'var(--text-primary)' }}>
      {incident.title || incident.resource_id || incident.incident_id}
    </span>
  </td>
  <td className="py-3 px-2">
    <span className="text-[11px] px-2 py-0.5 rounded" style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}>
      {incident.status}
    </span>
  </td>
  <td className="py-3 px-2 text-right">
    <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
      {formatRelativeTime(incident.created_at)}
    </span>
  </td>
</tr>
```

- [ ] **Step 4: Replace skeleton rows with styled versions**

Find the loading skeleton rows. Replace with:

```tsx
{Array.from({ length: 4 }).map((_, i) => (
  <tr key={i}>
    <td className="py-3 pl-3 pr-2" style={{ borderLeft: '4px solid var(--bg-subtle)' }}>
      <Skeleton className="h-4 w-14" />
    </td>
    <td className="py-3 px-2"><Skeleton className="h-4 w-16" /></td>
    <td className="py-3 px-2"><Skeleton className="h-4 w-32" /></td>
    <td className="py-3 px-2"><Skeleton className="h-4 w-14" /></td>
    <td className="py-3 px-2"><Skeleton className="h-4 w-10" /></td>
  </tr>
))}
```

- [ ] **Step 5: Read and update AlertFilters.tsx**

```bash
cat /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/components/AlertFilters.tsx
```

Find each `<SelectTrigger>` and update its className/style for compact pill appearance:

```tsx
<SelectTrigger
  className="h-8 text-xs px-3 gap-1 rounded-md"
  style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
>
```

- [ ] **Step 6: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

- [ ] **Step 7: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/AlertFeed.tsx services/web-ui/components/AlertFilters.tsx
git commit -m "feat: AlertFeed with severity stripes, mono resource names, skeleton loader, and alert count wiring"
```

---

## Chunk 5: Layout Wiring + Final Polish

### Task 12: Rewrite AppLayout and delete ChatPanel

**Files:**
- Modify: `services/web-ui/components/AppLayout.tsx`
- Delete: `services/web-ui/components/ChatPanel.tsx`

- [ ] **Step 1: Rewrite `services/web-ui/components/AppLayout.tsx`**

```tsx
'use client'

import { useState } from 'react'
import { TopNav } from './TopNav'
import { DashboardPanel } from './DashboardPanel'
import { ChatDrawer } from './ChatDrawer'
import { ChatFAB } from './ChatFAB'

export function AppLayout() {
  const [activeTab, setActiveTab] = useState('Alerts')

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopNav activeTab={activeTab} />
      <div className="flex-1 overflow-hidden">
        <DashboardPanel
          onTabChange={(tab) => setActiveTab(tab.charAt(0).toUpperCase() + tab.slice(1))}
        />
      </div>
      <ChatDrawer />
      <ChatFAB />
    </div>
  )
}
```

- [ ] **Step 2: Delete ChatPanel.tsx**

```bash
rm /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/components/ChatPanel.tsx
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: No errors. If errors remain about `ChatPanel` imports, search for them:

```bash
grep -r "ChatPanel" /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/
```

Remove any remaining imports/references.

- [ ] **Step 4: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add -A services/web-ui/components/AppLayout.tsx
git rm services/web-ui/components/ChatPanel.tsx
git commit -m "feat: wire AppLayout with TopNav, DashboardPanel, ChatDrawer, ChatFAB — remove split pane"
```

---

### Task 13: Polish ProposalCard and MetricCard

**Files:**
- Modify: `services/web-ui/components/ProposalCard.tsx`
- Modify: `services/web-ui/components/MetricCard.tsx`

- [ ] **Step 1: Read ProposalCard.tsx**

```bash
cat /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/components/ProposalCard.tsx
```

- [ ] **Step 2: Update ProposalCard border and button colors**

Find the outer card container div that has `border-l-4`. Replace the dynamic `border-l-destructive` / `border-l-orange-500` Tailwind classes with inline style:

```tsx
// Find the line with className containing "border-l-4" and "border-l-destructive" or "border-l-orange-500"
// Replace the border-left color with:
style={{
  borderLeft: `4px solid ${approval.risk_level === 'critical' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
  background: 'var(--bg-subtle)',
  border: '1px solid var(--border)',
  borderLeftWidth: '4px',
}}
```

Find the Approve button (currently uses default shadcn `Button` with variant). Update to:
```tsx
style={{ background: 'var(--accent-green)', color: '#FFFFFF', border: 'none' }}
```

Find the Reject button. Update to:
```tsx
style={{ background: 'var(--accent-red)', color: '#FFFFFF', border: 'none' }}
```

- [ ] **Step 3: Read MetricCard.tsx**

```bash
cat /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/components/MetricCard.tsx
```

- [ ] **Step 4: Update MetricCard surface styling**

Find the outer card wrapper. Replace any `bg-card`, `bg-background`, or `shadow` classes with inline style:

```tsx
style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: '8px' }}
```

Find the metric value element (large number). Update typography:
```tsx
className="font-mono text-2xl font-semibold"
style={{ color: 'var(--text-primary)' }}
```

Find the label element. Update:
```tsx
className="text-xs"
style={{ color: 'var(--text-muted)' }}
```

- [ ] **Step 5: Verify TypeScript and build**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui
npx tsc --noEmit && npm run build
```

Expected: Both pass with no errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
git add services/web-ui/components/ProposalCard.tsx services/web-ui/components/MetricCard.tsx
git commit -m "feat: polish ProposalCard and MetricCard with new token system"
```

---

### Task 14: Final verification and PR

- [ ] **Step 1: Full TypeScript check**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui && npx tsc --noEmit
```

Expected: Zero errors.

- [ ] **Step 2: Production build**

```bash
npm run build
```

Expected: Completes successfully.

- [ ] **Step 3: Verify no split-pane remnants**

```bash
grep -r "resizable-panels\|PanelGroup\|PanelResizeHandle" /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/
```

Expected: No output.

- [ ] **Step 4: Verify .chat-prose is used (not old prose-sm)**

```bash
grep -r "prose prose-sm\|prose-zinc" /Users/jasonmba/workspace/azure-agentic-platform/services/web-ui/components/
```

Expected: No output.

- [ ] **Step 5: Create PR**

```bash
cd /Users/jasonmba/workspace/azure-agentic-platform
gh pr create \
  --title "feat: SaaS UI redesign — Datadog/Grafana style with dark mode and chat drawer" \
  --base main \
  --body "$(cat <<'EOF'
## Summary
- Replaces split-pane layout with full-width dashboard + collapsible AI chat drawer (FAB trigger)
- New hex design token system with shadcn bridge via @theme (no hsl() wrappers)
- Always-dark top nav: theme toggle, alert bell, subscription pill, user avatar
- Custom ARIA tab bar with keyboard navigation replacing shadcn Tabs
- ThemeProvider + localStorage persistence + flash-prevention inline script
- Severity-coded alert rows with left border stripes, mono resource names
- Redesigned chat bubbles: AI avatar, .chat-prose markdown, error state variant
- AppStateContext: single shared store for drawer, chat, subscriptions, alert count

## Test plan
- [ ] Light mode: canvas bg, white surfaces, blue accents render correctly
- [ ] Toggle dark mode: all surfaces switch including cards, drawer, inputs
- [ ] Refresh preserves dark mode selection (localStorage)
- [ ] Open chat drawer via FAB: slide animation and backdrop work
- [ ] Close drawer via backdrop click, X button, or FAB
- [ ] Tab keyboard navigation: ArrowLeft/Right moves focus between tabs
- [ ] Subscription selector pill opens existing dropdown
- [ ] User avatar dropdown shows name, tenant, sign out
- [ ] Alert rows show severity-colored left border stripes
- [ ] Chat bubbles: AI avatar left, user bubble right-aligned blue
- [ ] Streaming cursor animates in agent bubbles
- [ ] ProposalCard: orange border, green approve, red reject
- [ ] `npm run build` passes

🤖 Generated with Claude Code
EOF
)"
```

---

## Task Dependencies

```
Task 1 (globals.css + layout.tsx)     ← foundation, do first
Task 2 (ThemeProvider)                ← needs Task 1
Task 3 (AppStateContext)              ← needs Task 2
Task 4 (NavSubscriptionPill)          ← needs Task 3
Task 5 (TopNav)                       ← needs Tasks 3, 4
Task 6 (ChatFAB)                      ← needs Task 3
Task 7 (ChatBubble/UserBubble)        ← needs Task 1
Task 8 (ThinkingIndicator/ChatInput)  ← needs Task 1
Task 9 (ChatDrawer)                   ← needs Tasks 3, 6, 7, 8
Task 10 (DashboardPanel)              ← needs Tasks 1, 3
Task 11 (AlertFeed)                   ← needs Tasks 1, 3, 10
Task 12 (AppLayout + delete ChatPanel) ← needs Tasks 5, 9, 10
Task 13 (ProposalCard/MetricCard)     ← needs Task 1
Task 14 (Verification + PR)           ← needs all tasks
```
