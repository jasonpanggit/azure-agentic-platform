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

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ background: 'var(--bg-canvas)' }}
    >
      <div
        className="flex flex-col items-center gap-3"
        role="status"
        aria-live="polite"
        aria-label="Completing sign-in"
      >
        <div
          className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin"
          style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }}
          aria-hidden="true"
        />
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          Completing sign-in&hellip;
        </p>
      </div>
    </div>
  );
}
