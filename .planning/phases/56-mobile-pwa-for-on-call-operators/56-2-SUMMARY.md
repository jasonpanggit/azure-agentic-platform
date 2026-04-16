---
status: complete
completed: "2026-04-16"
---

## What Was Built

Progressive Web App configuration for the Next.js web UI — installable on mobile, offline approval queueing, Web Push notifications.

## Files Created/Modified

| File | Action |
|------|--------|
| `services/web-ui/package.json` | Added `@ducanh2912/next-pwa ^10.2.9` and `idb ^8.0.0` |
| `services/web-ui/next.config.ts` | Wrapped NextConfig with withPWA — NetworkFirst for API proxy, StaleWhileRevalidate for pages, CacheFirst for assets, disabled in dev |
| `services/web-ui/public/manifest.json` | Web App Manifest — `start_url: /approvals`, Azure Blue `#0078D4`, shortcuts to Approvals + Dashboard |
| `services/web-ui/public/sw.js` | Custom service worker — IndexedDB offline queue, Background Sync replay, Web Push handler with severity emoji, notification click → /approvals |
| `services/web-ui/public/icons/icon-192.png` | Placeholder icon (replace with real Azure-branded PNG before launch) |
| `services/web-ui/public/icons/icon-512.png` | Placeholder icon |
| `services/web-ui/app/offline/page.tsx` | Offline fallback page — WifiOff icon, semantic CSS vars, retry button |
| `services/web-ui/app/api/proxy/notifications/subscribe/route.ts` | POST + DELETE proxy to `/api/v1/notifications/subscribe` |
| `services/web-ui/app/layout.tsx` | Added manifest link, themeColor, appleWebApp, viewport metadata |

## Key Decisions

- **@ducanh2912/next-pwa**: Most actively maintained next-pwa fork, works with Next.js 15 App Router
- **Offline queue**: Plain IndexedDB (no external lib) in sw.js — avoids bundler requirements in service worker context
- **Background Sync**: Approval actions queued offline and replayed via `sync` event tag `aap-approval-sync`
- **Disabled in dev**: `disable: process.env.NODE_ENV === 'development'` prevents SW from interfering with hot-reload
- **swcMinify removed**: Not a valid PluginOptions field in @ducanh2912/next-pwa v10 — removed to fix TypeScript error

## TypeScript Status

- Zero Phase 56 errors after `npm install` and `swcMinify` removal
- One pre-existing error in `OpsTab.test.tsx:56` (unrelated to Phase 56)
