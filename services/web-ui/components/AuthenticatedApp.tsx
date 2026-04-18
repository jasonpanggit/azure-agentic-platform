'use client';

import React from 'react';
import {
  AuthenticatedTemplate,
  UnauthenticatedTemplate,
  useMsal,
} from '@azure/msal-react';
import { Button } from '@/components/ui/button';
import { loginRequest } from '@/lib/msal-config';
import { DesktopOnlyGate } from './DesktopOnlyGate';
import { AppLayout } from './AppLayout';

const DEV_MODE = process.env.NEXT_PUBLIC_DEV_MODE === 'true';

export function AuthenticatedApp() {
  const { instance } = useMsal();

  if (DEV_MODE) {
    return (
      <DesktopOnlyGate minWidth={800}>
        <AppLayout />
      </DesktopOnlyGate>
    );
  }

  const handleLogin = () => {
    instance.loginPopup(loginRequest).catch((err) => {
      console.error('[AuthenticatedApp] loginPopup failed:', err);
    });
  };

  return (
    <>
      <AuthenticatedTemplate>
        <DesktopOnlyGate minWidth={800}>
          <AppLayout />
        </DesktopOnlyGate>
      </AuthenticatedTemplate>
      <UnauthenticatedTemplate>
        <div className="flex flex-col items-center justify-center h-screen gap-6">
          <h1 className="text-2xl font-semibold">Azure Agentic Platform</h1>
          <p className="text-sm text-muted-foreground">Sign in to access the operations dashboard.</p>
          <Button onClick={handleLogin}>Sign In</Button>
        </div>
      </UnauthenticatedTemplate>
    </>
  );
}
