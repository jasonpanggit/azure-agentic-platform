---
wave: 2
depends_on: [wave-1]
files_modified:
  - services/web-ui/package.json
  - services/web-ui/next.config.ts
  - services/web-ui/public/manifest.json
  - services/web-ui/public/sw.js
  - services/web-ui/app/offline/page.tsx
  - services/web-ui/app/api/proxy/notifications/subscribe/route.ts
autonomous: true
---

## Goal

Configure the Next.js web-UI as a Progressive Web App. Install
`@ducanh2912/next-pwa`, wrap `next.config.ts` with `withPWA`, publish a
`manifest.json` and `sw.js` (custom offline-queue additions), add an offline
fallback page, and proxy the push-subscription endpoint.

---

## Tasks

<task id="56-2-1">
### Install @ducanh2912/next-pwa in package.json

<read_first>
services/web-ui/package.json
</read_first>

<action>
Add `@ducanh2912/next-pwa` as a production dependency in
`services/web-ui/package.json`.

Insert the following entry inside the `"dependencies"` object, in alphabetical
order after `"@azure/msal-react"` and before `"@radix-ui/..."`:

```json
"@ducanh2912/next-pwa": "^10.2.9",
```

Also add the `idb` package (IndexedDB promise wrapper — used by `sw.js` for the
offline action queue) after `"cmdk"`:

```json
"idb": "^8.0.0",
```

Do NOT run `npm install` — the executor agent will do that. Only edit
`package.json`.
</action>

<acceptance_criteria>
- `package.json` contains `"@ducanh2912/next-pwa": "^10.2.9"` in `dependencies`
- `package.json` contains `"idb": "^8.0.0"` in `dependencies`
- JSON is syntactically valid (no trailing commas on last entry, etc.)
- No other dependencies are changed
</acceptance_criteria>
</task>

<task id="56-2-2">
### Wrap next.config.ts with withPWA

<read_first>
services/web-ui/next.config.ts
</read_first>

<action>
Replace the entire content of `services/web-ui/next.config.ts` with:

```typescript
import type { NextConfig } from 'next';
import withPWAInit from '@ducanh2912/next-pwa';

const withPWA = withPWAInit({
  dest: 'public',
  cacheOnFrontEndNav: true,
  aggressiveFrontEndNavCaching: true,
  reloadOnOnline: true,
  swcMinify: true,
  disable: process.env.NODE_ENV === 'development',
  workboxOptions: {
    disableDevLogs: true,
    runtimeCaching: [
      // Network-first for all API proxy routes — freshness preferred
      {
        urlPattern: /^\/api\/proxy\/.*/i,
        handler: 'NetworkFirst',
        options: {
          cacheName: 'api-proxy-cache',
          expiration: {
            maxEntries: 32,
            maxAgeSeconds: 60 * 5, // 5 minutes
          },
          networkTimeoutSeconds: 10,
        },
      },
      // Stale-while-revalidate for app pages
      {
        urlPattern: /^\/(approvals|dashboard)(\?.*)?$/i,
        handler: 'StaleWhileRevalidate',
        options: {
          cacheName: 'page-cache',
          expiration: {
            maxEntries: 16,
            maxAgeSeconds: 60 * 60, // 1 hour
          },
        },
      },
      // Cache-first for static assets (fonts, icons, images)
      {
        urlPattern: /\.(png|svg|ico|woff2?|ttf|eot)$/i,
        handler: 'CacheFirst',
        options: {
          cacheName: 'static-assets',
          expiration: {
            maxEntries: 64,
            maxAgeSeconds: 60 * 60 * 24 * 30, // 30 days
          },
        },
      },
    ],
  },
});

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
};

export default withPWA(nextConfig);
```

Key notes for the executor:
- `dest: 'public'` tells next-pwa to emit `sw.js` and workbox files into
  `public/` at build time. The custom `sw.js` written in task 56-2-4 will be
  picked up as the `customWorkerSrc` (see task 56-2-4 notes).
- `disable: process.env.NODE_ENV === 'development'` prevents the service worker
  from interfering with hot-reload in dev mode.
- The `workboxOptions.runtimeCaching` array configures precaching strategies;
  the `/api/proxy/*` network-first rule ensures approvals and incident data stay
  fresh while still working offline via the cached fallback.
</action>

<acceptance_criteria>
- `next.config.ts` imports `withPWAInit` from `@ducanh2912/next-pwa`
- `withPWA` wraps `nextConfig` in the default export
- `output: 'standalone'` and `reactStrictMode: true` are preserved
- `disable: process.env.NODE_ENV === 'development'` is present
- File is valid TypeScript (no syntax errors)
</acceptance_criteria>
</task>

<task id="56-2-3">
### Create public/manifest.json

<read_first>
services/web-ui/public/   (list directory — confirm it exists; it may be empty)
services/web-ui/app/layout.tsx  (check existing metadata / head content)
</read_first>

<action>
Create `services/web-ui/public/manifest.json` with the following content:

```json
{
  "name": "Azure Agentic Platform",
  "short_name": "AAP",
  "description": "Azure AIOps — on-call incident management and remediation approvals",
  "start_url": "/approvals",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait-primary",
  "background_color": "#0f1117",
  "theme_color": "#0078D4",
  "categories": ["business", "utilities"],
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any maskable"
    }
  ],
  "shortcuts": [
    {
      "name": "Pending Approvals",
      "short_name": "Approvals",
      "description": "View and action pending remediation approvals",
      "url": "/approvals",
      "icons": [{ "src": "/icons/icon-192.png", "sizes": "192x192" }]
    },
    {
      "name": "Dashboard",
      "short_name": "Dashboard",
      "description": "Azure platform health overview",
      "url": "/",
      "icons": [{ "src": "/icons/icon-192.png", "sizes": "192x192" }]
    }
  ],
  "screenshots": []
}
```

Notes:
- `start_url: "/approvals"` opens the mobile approvals screen directly when
  launched from the home screen.
- `background_color` matches the app's dark canvas (`#0f1117` from
  `var(--bg-canvas)` dark-mode value).
- `theme_color` is Azure Blue (`#0078D4` — the platform primary color per
  CLAUDE.md).
- Icon files (`icons/icon-192.png`, `icons/icon-512.png`) must also be created.
  Since we cannot generate real PNG files in this plan, create placeholder PNG
  stubs using the following bash command the executor must run:

```bash
mkdir -p services/web-ui/public/icons
# Create minimal 1x1 placeholder PNGs (89 bytes each — valid PNG header + IDAT)
# Replace with real icons before production.
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\xc0\x00\x00\x00\xc0\x08\x02\x00\x00\x00r\xb6^\x1c\x00\x00\x00\x19IDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82' \
  > services/web-ui/public/icons/icon-192.png
cp services/web-ui/public/icons/icon-192.png services/web-ui/public/icons/icon-512.png
```

(Production icons should be 192×192 and 512×512 Azure-branded PNGs. The
placeholder PNGs keep the manifest valid for testing without requiring a
design asset pipeline.)
</action>

<acceptance_criteria>
- `services/web-ui/public/manifest.json` exists and is valid JSON
- `name`, `short_name`, `start_url`, `display`, `theme_color` all present
- `theme_color` is `#0078D4`
- `start_url` is `/approvals`
- `icons` array has entries for 192×192 and 512×512
- `services/web-ui/public/icons/icon-192.png` and `icon-512.png` exist
</acceptance_criteria>
</task>

<task id="56-2-4">
### Create public/sw.js — custom service worker additions (offline queue)

<read_first>
services/web-ui/public/manifest.json  (just created — confirm paths)
</read_first>

<action>
Create `services/web-ui/public/sw.js` with the following content.

This file is the **custom worker source** that `@ducanh2912/next-pwa` merges
with the generated Workbox service worker at build time. It adds:
1. An **offline approval action queue** stored in IndexedDB (`aap-offline-queue`
   store). When `POST /api/proxy/approvals/*/approve` or `*/reject` is called
   while offline, the action is serialised to IndexedDB.
2. A **Background Sync handler** (`sync` event on tag `aap-approval-sync`) that
   replays queued actions when connectivity is restored.
3. A **push event handler** that shows a notification with the incident title,
   severity badge, and a deep-link action to `/approvals`.

```javascript
// sw.js — Custom service worker additions for AAP PWA (Phase 56)
// Merged into the Workbox-generated sw at build time by @ducanh2912/next-pwa.
// Do NOT import Workbox directly here — it is injected by the build tool.

const OFFLINE_QUEUE_DB = 'aap-offline-queue';
const OFFLINE_QUEUE_STORE = 'pending-actions';
const OFFLINE_QUEUE_DB_VERSION = 1;
const SYNC_TAG = 'aap-approval-sync';

// ---------------------------------------------------------------------------
// IndexedDB helpers (no external library — plain IDBOpenDBRequest)
// ---------------------------------------------------------------------------

/**
 * Open (or create) the offline queue IndexedDB database.
 * Returns a Promise<IDBDatabase>.
 */
function openQueueDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(OFFLINE_QUEUE_DB, OFFLINE_QUEUE_DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(OFFLINE_QUEUE_STORE)) {
        db.createObjectStore(OFFLINE_QUEUE_STORE, {
          keyPath: 'id',
          autoIncrement: true,
        });
      }
    };
    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Enqueue an approval action for background sync replay.
 * @param {Object} action  { url, method, body, timestamp }
 */
async function enqueueAction(action) {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readwrite');
    const store = tx.objectStore(OFFLINE_QUEUE_STORE);
    const request = store.add({ ...action, timestamp: Date.now() });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Return all queued actions (oldest first).
 * @returns {Promise<Array>}
 */
async function getAllQueuedActions() {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readonly');
    const store = tx.objectStore(OFFLINE_QUEUE_STORE);
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Remove a successfully replayed action by its IDB record id.
 * @param {number} id
 */
async function removeQueuedAction(id) {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readwrite');
    const store = tx.objectStore(OFFLINE_QUEUE_STORE);
    const request = store.delete(id);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

// ---------------------------------------------------------------------------
// Fetch intercept — queue approval actions when offline
// ---------------------------------------------------------------------------

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only intercept POST requests to approval action endpoints
  const isApprovalAction =
    event.request.method === 'POST' &&
    /\/api\/proxy\/approvals\/[^/]+\/(approve|reject)$/.test(url.pathname);

  if (!isApprovalAction) {
    // Let Workbox handle everything else via its own fetch listener
    return;
  }

  event.respondWith(
    (async () => {
      try {
        // Attempt live network request first
        const response = await fetch(event.request.clone());
        return response;
      } catch (_networkError) {
        // Offline — queue for background sync
        const clonedRequest = event.request.clone();
        const body = await clonedRequest.text();
        await enqueueAction({
          url: event.request.url,
          method: 'POST',
          body,
          headers: Object.fromEntries(event.request.headers.entries()),
        });

        // Register background sync (browser will fire 'sync' when online)
        if (self.registration.sync) {
          await self.registration.sync.register(SYNC_TAG);
        }

        // Return a synthetic 202 so the UI can show "queued" state
        return new Response(
          JSON.stringify({
            status: 'queued',
            message: 'Action queued for sync when connectivity is restored.',
          }),
          {
            status: 202,
            headers: { 'Content-Type': 'application/json' },
          }
        );
      }
    })()
  );
});

// ---------------------------------------------------------------------------
// Background Sync — replay queued approval actions
// ---------------------------------------------------------------------------

self.addEventListener('sync', (event) => {
  if (event.tag === SYNC_TAG) {
    event.waitUntil(
      (async () => {
        const queued = await getAllQueuedActions();
        for (const action of queued) {
          try {
            const response = await fetch(action.url, {
              method: action.method,
              body: action.body,
              headers: action.headers,
            });
            if (response.ok) {
              await removeQueuedAction(action.id);
            }
          } catch (_err) {
            // Still offline — leave in queue, will retry on next sync event
          }
        }
      })()
    );
  }
});

// ---------------------------------------------------------------------------
// Push event — show notification
// ---------------------------------------------------------------------------

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_e) {
    data = { title: 'Azure Agentic Platform', body: 'New incident alert' };
  }

  const severityEmoji =
    data.severity === 'Sev0' ? '🔴' : data.severity === 'Sev1' ? '🟠' : '🟡';

  const title = `${severityEmoji} ${data.severity ?? 'Alert'}: ${data.title ?? 'Incident'}`;
  const options = {
    body: `Domain: ${data.domain ?? 'unknown'} — Tap to review approvals`,
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: data.incident_id ?? 'aap-incident',
    renotify: true,
    requireInteraction: data.severity === 'Sev0',
    data: {
      url: data.url ?? '/approvals',
      incident_id: data.incident_id,
    },
    actions: [
      { action: 'open', title: 'Open Approvals' },
      { action: 'dismiss', title: 'Dismiss' },
    ],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// ---------------------------------------------------------------------------
// Notification click — navigate to /approvals
// ---------------------------------------------------------------------------

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'dismiss') {
    return;
  }

  const targetUrl = event.notification.data?.url ?? '/approvals';

  event.waitUntil(
    clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((windowClients) => {
        // Focus existing window if already open
        for (const client of windowClients) {
          if (client.url.includes(targetUrl) && 'focus' in client) {
            return client.focus();
          }
        }
        // Otherwise open a new window
        if (clients.openWindow) {
          return clients.openWindow(targetUrl);
        }
      })
  );
});
```
</action>

<acceptance_criteria>
- `services/web-ui/public/sw.js` is created
- File contains `fetch` event listener intercepting `/api/proxy/approvals/*/approve|reject`
- File contains `sync` event listener for tag `aap-approval-sync`
- File contains `push` event listener calling `self.registration.showNotification`
- File contains `notificationclick` event listener
- `openQueueDb`, `enqueueAction`, `getAllQueuedActions`, `removeQueuedAction` are
  all defined
- No imports from `node_modules` (plain browser JS, no bundler required)
</acceptance_criteria>
</task>

<task id="56-2-5">
### Create app/offline/page.tsx — offline fallback page

<read_first>
services/web-ui/app/layout.tsx     (confirm imports available: Providers wrapper)
services/web-ui/app/page.tsx       (main page pattern for reference)
services/web-ui/lib/utils.ts       (cn helper)
</read_first>

<action>
Create `services/web-ui/app/offline/page.tsx` with the following content:

```typescript
'use client';

import { WifiOff, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

/**
 * Offline fallback page shown by the service worker when the app is offline
 * and no cached version of the requested page is available.
 *
 * Configured as the `fallbackRoutes.document` in next-pwa workbox options.
 */
export default function OfflinePage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4"
         style={{ background: 'var(--bg-canvas)' }}>
      <div className="flex flex-col items-center gap-4 text-center">
        <div
          className="flex h-20 w-20 items-center justify-center rounded-full"
          style={{
            background: 'color-mix(in srgb, var(--accent-yellow) 15%, transparent)',
          }}
        >
          <WifiOff
            className="h-10 w-10"
            style={{ color: 'var(--accent-yellow)' }}
            aria-hidden="true"
          />
        </div>

        <h1
          className="text-2xl font-semibold"
          style={{ color: 'var(--text-primary)' }}
        >
          You&apos;re offline
        </h1>

        <p
          className="max-w-sm text-sm leading-relaxed"
          style={{ color: 'var(--text-muted)' }}
        >
          No internet connection detected. Pending approval actions will be
          queued and replayed automatically when connectivity is restored.
        </p>
      </div>

      <Button
        variant="outline"
        className="gap-2"
        onClick={() => window.location.reload()}
        aria-label="Retry connection"
      >
        <RefreshCw className="h-4 w-4" aria-hidden="true" />
        Try again
      </Button>

      <p
        className="text-xs"
        style={{ color: 'var(--text-muted)' }}
      >
        Previously viewed approvals may be available in cached form.
      </p>
    </div>
  );
}
```
</action>

<acceptance_criteria>
- `services/web-ui/app/offline/page.tsx` is created
- Page renders a `WifiOff` icon, heading, description, and retry button
- Uses semantic CSS custom properties (`var(--bg-canvas)`, `var(--text-primary)`,
  `var(--text-muted)`, `var(--accent-yellow)`) — no hardcoded Tailwind color classes
- Uses `color-mix(in srgb, ...)` for badge background
- `'use client'` directive is present (needed for `onClick`)
- No TypeScript errors
</acceptance_criteria>
</task>

<task id="56-2-6">
### Create app/api/proxy/notifications/subscribe/route.ts

<read_first>
services/web-ui/app/api/proxy/incidents/route.ts       (proxy pattern reference)
services/web-ui/lib/api-gateway.ts                     (getApiGatewayUrl, buildUpstreamHeaders)
services/web-ui/app/api/proxy/approvals/[approvalId]/approve/route.ts  (POST proxy reference)
</read_first>

<action>
Create the directory `services/web-ui/app/api/proxy/notifications/subscribe/`
and inside it create `route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getApiGatewayUrl, buildUpstreamHeaders } from '@/lib/api-gateway';
import { logger } from '@/lib/logger';

const log = logger.child({ route: '/api/proxy/notifications/subscribe' });

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * POST /api/proxy/notifications/subscribe
 *
 * Stores a Web Push subscription by proxying to the API gateway.
 * Called by the PWA service worker registration flow in the browser.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();
    log.info('subscribe request', { operator_id: body?.operator_id ?? 'anonymous' });

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(`${apiGatewayUrl}/api/v1/notifications/subscribe`, {
      method: 'POST',
      headers: upstreamHeaders,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      log.error('upstream error', { status: res.status, detail: errorData?.detail });
      return NextResponse.json(
        { error: errorData?.detail ?? `Gateway error: ${res.status}` },
        { status: res.status }
      );
    }

    const data = await res.json();
    log.debug('subscribed', { id: data?.id });
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}

/**
 * DELETE /api/proxy/notifications/subscribe
 *
 * Removes a Web Push subscription by proxying to the API gateway.
 */
export async function DELETE(request: NextRequest): Promise<NextResponse> {
  try {
    const apiGatewayUrl = getApiGatewayUrl();
    const body = await request.json();
    log.info('unsubscribe request');

    const upstreamHeaders = buildUpstreamHeaders(request.headers.get('Authorization'));

    const res = await fetch(`${apiGatewayUrl}/api/v1/notifications/subscribe`, {
      method: 'DELETE',
      headers: upstreamHeaders,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });

    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.ok ? 200 : res.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error('gateway unreachable', { error: message });
    return NextResponse.json(
      { error: `Failed to reach API gateway: ${message}` },
      { status: 502 }
    );
  }
}
```
</action>

<acceptance_criteria>
- File is created at `services/web-ui/app/api/proxy/notifications/subscribe/route.ts`
- Exports `POST` and `DELETE` handlers
- Uses `getApiGatewayUrl()` and `buildUpstreamHeaders()` (existing helpers)
- Uses `AbortSignal.timeout(15000)` (matches existing proxy pattern)
- `export const runtime = 'nodejs'` and `export const dynamic = 'force-dynamic'`
  are present
- No TypeScript errors
</acceptance_criteria>
</task>

---

## Verification

```bash
# 1. Confirm @ducanh2912/next-pwa is in package.json
grep "@ducanh2912/next-pwa" services/web-ui/package.json

# 2. Confirm idb is in package.json
grep '"idb"' services/web-ui/package.json

# 3. Validate manifest.json
node -e "JSON.parse(require('fs').readFileSync('services/web-ui/public/manifest.json','utf8')); console.log('manifest OK')"

# 4. Confirm sw.js exists and contains key event listeners
grep -c "addEventListener" services/web-ui/public/sw.js

# 5. TypeScript type-check next.config.ts
cd services/web-ui && npx tsc --noEmit 2>&1 | head -30

# 6. Install deps (must succeed for the build check below)
cd services/web-ui && npm install

# 7. Build check — confirms withPWA wrapping is syntactically correct
cd services/web-ui && npm run build 2>&1 | tail -20

# 8. Confirm proxy route file exists
ls services/web-ui/app/api/proxy/notifications/subscribe/route.ts

# 9. Confirm offline page exists
ls services/web-ui/app/offline/page.tsx
```

## must_haves
- [ ] `@ducanh2912/next-pwa` and `idb` added to `package.json`
- [ ] `next.config.ts` wraps `nextConfig` with `withPWA(...)`
- [ ] `disable: process.env.NODE_ENV === 'development'` prevents SW in dev mode
- [ ] `workboxOptions.runtimeCaching` has NetworkFirst for `/api/proxy/*`
- [ ] `public/manifest.json` is valid JSON with `theme_color: #0078D4` and `start_url: /approvals`
- [ ] `public/icons/icon-192.png` and `icon-512.png` exist (placeholder or real)
- [ ] `public/sw.js` contains offline-queue logic (IndexedDB) + push handler + sync handler
- [ ] `app/offline/page.tsx` uses semantic CSS vars, no hardcoded Tailwind color classes
- [ ] `app/api/proxy/notifications/subscribe/route.ts` exports `POST` and `DELETE`
- [ ] `npm run build` completes without errors
