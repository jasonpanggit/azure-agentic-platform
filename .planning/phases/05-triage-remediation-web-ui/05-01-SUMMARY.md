# Plan 05-01 Summary — Web UI Foundation

**Status:** ✅ Complete
**Date:** 2026-03-27
**Branch:** `phase-5-wave-0-test-infrastructure`

---

## What Was Built

Plan 05-01 established the structural foundation for the Azure AIOps web UI — the Next.js App Router skeleton, MSAL authentication gates, the split-pane shell layout, auth route pages, and the Docker/CI delivery pipeline.

---

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 5-01-01 | MSAL PKCE configuration and singleton instance | `b8183a2` |
| 5-01-02 | Providers component (FluentProvider + MsalProvider) | `df8071d` |
| 5-01-03 | Root layout, page entry point, AuthenticatedApp, DesktopOnlyGate | `fa8d60b` |
| 5-01-04 | AppLayout split-pane, ChatPanel shell, DashboardPanel shell, SubscriptionSelector | `457a340` |
| 5-01-05 | MSAL login and callback pages | `c24cac3` |
| 5-01-06 | Dockerfile and CI workflow | `bfaa4d6` |

---

## Files Created

### Authentication Layer
- `services/web-ui/lib/msal-config.ts` — PKCE config with tenant/client env vars, loginRequest scopes
- `services/web-ui/lib/msal-instance.ts` — Singleton PublicClientApplication with lazy init
- `services/web-ui/app/providers.tsx` — FluentProvider + MsalProvider wrapper with theme toggle

### App Shell
- `services/web-ui/app/layout.tsx` — Root layout with Segoe UI Variable font, Providers wrapper
- `services/web-ui/app/page.tsx` — Homepage entry point rendering AuthenticatedApp
- `services/web-ui/components/AuthenticatedApp.tsx` — MSAL auth gates (Authenticated/Unauthenticated templates), login button
- `services/web-ui/components/DesktopOnlyGate.tsx` — Enforces ≥1200px viewport with resize listener

### Layout Components
- `services/web-ui/components/AppLayout.tsx` — react-resizable-panels split-pane (35/65 default), 4-tab dashboard, top bar
- `services/web-ui/components/ChatPanel.tsx` — Shell placeholder (replaced by Plan 05-02 Task 5-02-05)
- `services/web-ui/components/DashboardPanel.tsx` — Shell placeholder (replaced by Plan 05-05 Task 5-05-06)
- `services/web-ui/components/SubscriptionSelector.tsx` — Multiselect Combobox with placeholder subs

### Auth Routes
- `services/web-ui/app/(auth)/login/page.tsx` — Triggers loginRedirect on mount
- `services/web-ui/app/(auth)/callback/page.tsx` — Handles handleRedirectPromise, routes to /

### Delivery
- `services/web-ui/Dockerfile` — Multi-stage (node:20-slim builder + runner), standalone output, non-root user
- `.github/workflows/web-ui-build.yml` — CI trigger on web-ui/** path, delegates to docker-push.yml

---

## Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| `autoSaveId="aap-main-layout"` on PanelGroup | Persists user's preferred chat/dashboard split ratio in localStorage |
| `(auth)` route group | Isolates login/callback pages from root layout to prevent Providers double-wrapping |
| `DesktopOnlyGate` uses `useState(true)` default | Avoids hydration mismatch — SSR renders full content, client corrects on resize check |
| Shell placeholders for ChatPanel/DashboardPanel | Preserves correct props interface contract; Plans 05-02 and 05-05 drop in replacements |
| Standalone Next.js output in Dockerfile | Required for Container Apps deployment without full node_modules; smaller image |

---

## Deferred to Later Plans

| Component | Plan | Reason |
|-----------|------|--------|
| Full chat UI (message history, streaming, input) | 05-02 | Requires SSE stream API from Plan 05-03 |
| AlertFeed, AuditLogViewer, resource grid | 05-05 | Requires Cosmos/ARM data contracts from Plans 05-03/05-04 |
| Real subscription list from ARM | 05-03 | Requires API gateway subscription endpoint |
| Theme toggle UI control | 05-02 | Minor; Providers already supports dark/light, just needs a toggle button |
