'use client';

import React, { useState, useEffect, useMemo } from 'react';
import {
  FluentProvider,
  webLightTheme,
  webDarkTheme,
} from '@fluentui/react-components';
import { MsalProvider } from '@azure/msal-react';
import { getMsalInstance } from '@/lib/msal-instance';

type ThemeMode = 'light' | 'dark';

export function Providers({ children }: { children: React.ReactNode }) {
  const [themeMode, setThemeMode] = useState<ThemeMode>('light');
  const [msalReady, setMsalReady] = useState(false);

  const msalInstance = useMemo(() => getMsalInstance(), []);

  useEffect(() => {
    // Restore theme preference from localStorage
    const saved = localStorage.getItem('aap-theme') as ThemeMode | null;
    if (saved === 'dark' || saved === 'light') {
      setThemeMode(saved);
    }

    // Initialize MSAL then handle any pending redirect promise.
    // Use a timeout fallback so a stalled handleRedirectPromise never
    // blocks the app from rendering indefinitely.
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

  const theme = themeMode === 'dark' ? webDarkTheme : webLightTheme;

  if (!msalReady) {
    return (
      <FluentProvider theme={theme}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
          Loading...
        </div>
      </FluentProvider>
    );
  }

  return (
    <MsalProvider instance={msalInstance}>
      <FluentProvider theme={theme}>
        {children}
      </FluentProvider>
    </MsalProvider>
  );
}
