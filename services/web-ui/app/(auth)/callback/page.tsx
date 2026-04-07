'use client';

import { useEffect, useRef } from 'react';
import { useMsal } from '@azure/msal-react';
import { useRouter } from 'next/navigation';

export default function AuthCallbackPage() {
  const { instance, accounts } = useMsal();
  const router = useRouter();
  const redirected = useRef(false);

  // Primary: redirect as soon as an account is available (reactive).
  // This handles the case where providers.tsx already called
  // handleRedirectPromise() before this page mounted, so accounts
  // may appear without this page ever seeing a non-null response.
  useEffect(() => {
    if (accounts.length > 0 && !redirected.current) {
      redirected.current = true;
      router.replace('/');
    }
  }, [accounts, router]);

  // Fallback: if handleRedirectPromise hasn't been called yet (edge case),
  // call it here and redirect on completion.
  useEffect(() => {
    instance.handleRedirectPromise()
      .then((response) => {
        if (response && !redirected.current) {
          redirected.current = true;
          router.replace('/');
        }
      })
      .catch((error) => {
        console.error('[Auth Callback]', error);
        if (!redirected.current) {
          redirected.current = true;
          router.replace('/');
        }
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

