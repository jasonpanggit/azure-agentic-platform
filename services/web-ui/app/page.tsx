import { AuthenticatedApp } from '@/components/AuthenticatedApp';

// Disable static prerendering — the app relies on client-side MSAL auth and
// dynamic dashboard state; force-dynamic avoids SSR module resolution errors
// that occur when Next.js tries to statically prerender deeply nested client
// components (DashboardPanel → CapacityTab / DriftTab etc.).
export const dynamic = 'force-dynamic';

export default function HomePage() {
  return <AuthenticatedApp />;
}
