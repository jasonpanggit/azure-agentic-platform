'use client';

import { WifiOff, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

/**
 * Offline fallback page shown by the service worker when the app is offline
 * and no cached version of the requested page is available.
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
