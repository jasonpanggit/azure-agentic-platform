'use client';

import { useEffect } from 'react';
import { useMsal } from '@azure/msal-react';
import { loginRequest } from '@/lib/msal-config';

export default function LoginPage() {
  const { instance } = useMsal();

  useEffect(() => {
    instance.loginPopup(loginRequest).catch((err) => {
      console.error('[LoginPage] loginPopup failed:', err);
    });
  }, [instance]);

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ background: 'var(--bg-canvas)' }}
    >
      <div
        className="flex flex-col items-center gap-3"
        role="status"
        aria-live="polite"
        aria-label="Redirecting to sign-in"
      >
        <div
          className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin"
          style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }}
          aria-hidden="true"
        />
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          Redirecting to sign-in&hellip;
        </p>
      </div>
    </div>
  );
}
