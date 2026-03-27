import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      exclude: ["**/integration/**", "**/node_modules/**"],
    },
    exclude: ["**/integration/**", "**/node_modules/**"],
  },
});
