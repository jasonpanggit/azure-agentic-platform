'use client';

import { useEffect } from 'react';
import { useMsal } from '@azure/msal-react';
import { loginRequest } from '@/lib/msal-config';

export default function LoginPage() {
  const { instance } = useMsal();

  useEffect(() => {
    instance.loginRedirect(loginRequest);
  }, [instance]);

  return <div>Redirecting to sign-in...</div>;
}
