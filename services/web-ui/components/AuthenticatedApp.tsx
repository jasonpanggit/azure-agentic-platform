'use client';

import React from 'react';
import {
  AuthenticatedTemplate,
  UnauthenticatedTemplate,
} from '@azure/msal-react';
import { Button, Text, makeStyles, tokens } from '@fluentui/react-components';
import { useMsal } from '@azure/msal-react';
import { loginRequest } from '@/lib/msal-config';
import { DesktopOnlyGate } from './DesktopOnlyGate';
import { AppLayout } from './AppLayout';

const useStyles = makeStyles({
  loginContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100vh',
    gap: tokens.spacingVerticalL,
  },
});

export function AuthenticatedApp() {
  const { instance } = useMsal();
  const styles = useStyles();

  const handleLogin = () => {
    instance.loginRedirect(loginRequest);
  };

  return (
    <>
      <AuthenticatedTemplate>
        <DesktopOnlyGate minWidth={1200}>
          <AppLayout />
        </DesktopOnlyGate>
      </AuthenticatedTemplate>
      <UnauthenticatedTemplate>
        <div className={styles.loginContainer}>
          <Text as="h1" size={800} weight="semibold">
            Azure AIOps
          </Text>
          <Text>Sign in to access the operations dashboard.</Text>
          <Button appearance="primary" onClick={handleLogin}>
            Sign In
          </Button>
        </div>
      </UnauthenticatedTemplate>
    </>
  );
}
