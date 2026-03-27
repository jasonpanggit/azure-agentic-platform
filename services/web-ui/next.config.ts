import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  transpilePackages: [
    '@fluentui/react-components',
    '@fluentui/react-icons',
  ],
};

export default nextConfig;
