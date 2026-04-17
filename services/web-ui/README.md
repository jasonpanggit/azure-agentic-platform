# Web UI

Next.js 15 (App Router) web dashboard for the Azure Agentic Platform. Provides 7 operational tabs (Alerts, Audit, Topology, Resources, Observability, Patch, AKS) alongside a full-width conversational chat panel and resource-scoped VM/AKS chat. Streams agent responses in real time via SSE.

## Tech Stack
- Next.js 15 (App Router, Node.js runtime)
- Tailwind CSS v3 + shadcn/ui (New York preset)
- `lucide-react` icons
- MSAL (`@azure/msal-browser`) — popup-based Entra ID authentication
- Playwright (`@playwright/test`) — E2E tests
- Jest — unit/component tests
- Docker (Container Apps deployment, public ingress)

## Key Files / Directories

- `app/layout.tsx` — Root layout; applies Inter font, CSS tokens, MSAL provider
- `app/page.tsx` — Main dashboard shell: tab navigation + chat panel side-by-side
- `app/providers.tsx` — React context providers (MSAL, theme, query client)
- `app/(auth)/` — MSAL login/logout pages and auth guard
- `app/api/` — Next.js Route Handlers
  - `app/api/proxy/*/route.ts` — Proxy routes to API Gateway (`getApiGatewayUrl()` + 15 s timeout)
  - `app/api/chat/route.ts` — SSE streaming endpoint; relays Foundry agent token events to the browser
- `components/` — Feature components (alerts table, topology graph, chat panel, approval dialog, etc.)
- `components/ui/` — shadcn/ui base components (18 components)
- `lib/` — Utilities: `msal-instance.ts`, `api.ts`, `useResizable.ts`, semantic token helpers
- `types/` — Shared TypeScript types for API responses and UI state
- `tailwind.config.ts` — Tailwind config; extends with AAP semantic color tokens
- `globals.css` — CSS custom properties (`--accent-*`, `--bg-canvas`, `--text-primary`, `--border`)
- `next.config.ts` — Next.js config (API rewrites, image domains)
- `playwright.config.ts` — Playwright E2E config
- `jest.config.js` — Jest unit test config
- `Dockerfile` — Container image definition
- `__tests__/` — Jest unit tests
- `app/api/proxy/*/route.ts` tests live alongside their route files

## Running Locally

```bash
cd services/web-ui
npm install
npm run dev
# Open http://localhost:3000
```

> Requires `NEXT_PUBLIC_API_GATEWAY_URL`, `NEXT_PUBLIC_MSAL_CLIENT_ID`, and `NEXT_PUBLIC_MSAL_TENANT_ID` in a `.env.local` file. MSAL auth can be disabled for local dev by setting `NEXT_PUBLIC_AUTH_DISABLED=true`.

## CSS Conventions

Use semantic CSS custom properties — never hardcoded Tailwind color classes:

```tsx
// ✅ Correct
<span style={{ color: 'var(--accent-blue)' }} />
<Badge className="badge-blue" />   // uses color-mix token

// ❌ Wrong
<span className="text-blue-600" />
```
