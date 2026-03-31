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
    getMsalInstance().then((i) => {
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
