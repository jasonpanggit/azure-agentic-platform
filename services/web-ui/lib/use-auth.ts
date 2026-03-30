'use client';

import { useMemo } from 'react';
import { useMsal } from '@azure/msal-react';
import { AccountInfo } from '@azure/msal-browser';

/**
 * Extracts the currently authenticated user from MSAL, with a
 * dev-mode bypass when NEXT_PUBLIC_DEV_MODE=true.
 *
 * Returns `null` when unauthenticated (and not in dev mode).
 * Returns a synthetic dev account when NEXT_PUBLIC_DEV_MODE is true.
 * Returns the first active MSAL account in production.
 */
export interface AuthUser {
  name: string;
  email: string;
  accountId: string;
}

const DEV_USER: AuthUser = {
  name: 'Dev User',
  email: 'dev@example.com',
  accountId: 'dev-account-id',
};

function msalAccountToUser(account: AccountInfo): AuthUser {
  return {
    name: account.name ?? account.username,
    email: account.username,
    accountId: account.homeAccountId,
  };
}

export function useAuth(): AuthUser | null {
  const { accounts } = useMsal();

  return useMemo(() => {
    if (process.env.NEXT_PUBLIC_DEV_MODE === 'true') {
      return DEV_USER;
    }
    const account = accounts[0];
    if (!account) {
      return null;
    }
    return msalAccountToUser(account);
  }, [accounts]);
}
