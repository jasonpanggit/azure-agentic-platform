'use client'

import { useEffect, useState } from 'react'
import { MsalProvider } from '@azure/msal-react'
import { getMsalInstance } from '@/lib/msal-instance'
import { IPublicClientApplication } from '@azure/msal-browser'
import { ThemeProvider } from '@/lib/theme-context'
import { AppStateProvider } from '@/lib/app-state-context'

export function Providers({ children }: { children: React.ReactNode }) {
  const [msalInstance, setMsalInstance] = useState<IPublicClientApplication | null>(null)
  const [msalError, setMsalError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getMsalInstance()
      .then((i) => {
        if (!cancelled) setMsalInstance(i)
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('[Providers] MSAL init failed:', err)
          setMsalError(err instanceof Error ? err.message : 'Authentication initialisation failed')
        }
      })
    return () => { cancelled = true }
  }, [])

  if (msalError) {
    return (
      <div className="flex h-screen items-center justify-center flex-col gap-3">
        <p className="text-sm font-medium">Sign-in unavailable</p>
        <p className="text-xs text-muted-foreground max-w-xs text-center">{msalError}</p>
        <button
          className="text-xs underline"
          onClick={() => window.location.reload()}
        >
          Retry
        </button>
      </div>
    )
  }

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
