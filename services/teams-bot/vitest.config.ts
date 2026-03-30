import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    // Provide minimum required env vars so index.ts can be imported in integration tests
    env: {
      BOT_ID: "test-bot-id",
      BOT_TENANT_ID: "test-tenant-id",
      BOT_PASSWORD: "test-bot-password",
      API_GATEWAY_INTERNAL_URL: "http://api-gateway.test.internal",
      WEB_UI_PUBLIC_URL: "https://ui.test.example.com",
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      // Exclude integration tests from coverage (they need live env for meaningful coverage)
      exclude: ["**/integration/**", "**/node_modules/**"],
    },
    // Integration tests ARE included in test runs (exclude only applies to coverage above)
  },
});
