'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { MsalProvider } from '@azure/msal-react';
import { getMsalInstance } from '@/lib/msal-instance';

export function Providers({ children }: { children: React.ReactNode }) {
  const [msalReady, setMsalReady] = useState(false);

  const msalInstance = useMemo(() => getMsalInstance(), []);

  useEffect(() => {
    msalInstance.initialize().then(() => {
      const redirectPromise = msalInstance.handleRedirectPromise();
      const timeout = new Promise<null>(resolve => setTimeout(() => resolve(null), 5000));
      Promise.race([redirectPromise, timeout]).then(() => {
        setMsalReady(true);
      }).catch(() => {
        setMsalReady(true);
      });
    }).catch(() => {
      setMsalReady(true);
    });
  }, [msalInstance]);

  if (!msalReady) {
    return (
      <div className="flex items-center justify-center h-screen text-sm text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <MsalProvider instance={msalInstance}>
      {children}
    </MsalProvider>
  );
}
