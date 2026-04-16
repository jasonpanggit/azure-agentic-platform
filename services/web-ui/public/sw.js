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

  const isApprovalAction =
    event.request.method === 'POST' &&
    /\/api\/proxy\/approvals\/[^/]+\/(approve|reject)$/.test(url.pathname);

  if (!isApprovalAction) {
    return;
  }

  event.respondWith(
    (async () => {
      try {
        const response = await fetch(event.request.clone());
        return response;
      } catch (_networkError) {
        const clonedRequest = event.request.clone();
        const body = await clonedRequest.text();
        await enqueueAction({
          url: event.request.url,
          method: 'POST',
          body,
          headers: Object.fromEntries(event.request.headers.entries()),
        });

        if (self.registration.sync) {
          await self.registration.sync.register(SYNC_TAG);
        }

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
            // Still offline — leave in queue
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
        for (const client of windowClients) {
          if (client.url.includes(targetUrl) && 'focus' in client) {
            return client.focus();
          }
        }
        if (clients.openWindow) {
          return clients.openWindow(targetUrl);
        }
      })
  );
});
