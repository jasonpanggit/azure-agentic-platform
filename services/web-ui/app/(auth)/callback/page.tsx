'use client';

import { useEffect } from 'react';
import { useMsal } from '@azure/msal-react';
import { useRouter } from 'next/navigation';

export default function AuthCallbackPage() {
  const { instance } = useMsal();
  const router = useRouter();

  useEffect(() => {
    instance.handleRedirectPromise().then((response) => {
      if (response) {
        router.replace('/');
      }
    }).catch((error) => {
      console.error('[Auth Callback]', error);
      router.replace('/');
    });
  }, [instance, router]);

  return <div>Completing sign-in...</div>;
}
