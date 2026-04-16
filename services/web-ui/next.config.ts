import type { NextConfig } from 'next';
import withPWAInit from '@ducanh2912/next-pwa';

const withPWA = withPWAInit({
  dest: 'public',
  cacheOnFrontEndNav: true,
  aggressiveFrontEndNavCaching: true,
  reloadOnOnline: true,
  disable: process.env.NODE_ENV === 'development',
  workboxOptions: {
    disableDevLogs: true,
    runtimeCaching: [
      // Network-first for all API proxy routes — freshness preferred
      {
        urlPattern: /^\/api\/proxy\/.*/i,
        handler: 'NetworkFirst',
        options: {
          cacheName: 'api-proxy-cache',
          expiration: {
            maxEntries: 32,
            maxAgeSeconds: 60 * 5, // 5 minutes
          },
          networkTimeoutSeconds: 10,
        },
      },
      // Stale-while-revalidate for app pages
      {
        urlPattern: /^\/(approvals|dashboard)(\?.*)?$/i,
        handler: 'StaleWhileRevalidate',
        options: {
          cacheName: 'page-cache',
          expiration: {
            maxEntries: 16,
            maxAgeSeconds: 60 * 60, // 1 hour
          },
        },
      },
      // Cache-first for static assets (fonts, icons, images)
      {
        urlPattern: /\.(png|svg|ico|woff2?|ttf|eot)$/i,
        handler: 'CacheFirst',
        options: {
          cacheName: 'static-assets',
          expiration: {
            maxEntries: 64,
            maxAgeSeconds: 60 * 60 * 24 * 30, // 30 days
          },
        },
      },
    ],
  },
});

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
};

export default withPWA(nextConfig);
