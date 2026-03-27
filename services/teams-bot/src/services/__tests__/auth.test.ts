import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Save original env
const originalEnv = { ...process.env };

describe("auth service", () => {
  beforeEach(() => {
    vi.resetModules();
    // Clear AZURE_CLIENT_ID to default to dev mode
    delete process.env.AZURE_CLIENT_ID;
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("isDevelopmentMode() returns true when AZURE_CLIENT_ID is not set", async () => {
    delete process.env.AZURE_CLIENT_ID;
    const { isDevelopmentMode } = await import("../auth");
    expect(isDevelopmentMode()).toBe(true);
  });

  it("isDevelopmentMode() returns false when AZURE_CLIENT_ID is set", async () => {
    process.env.AZURE_CLIENT_ID = "some-client-id";
    const { isDevelopmentMode } = await import("../auth");
    expect(isDevelopmentMode()).toBe(false);
  });

  it("getGatewayToken() returns 'dev-token' in dev mode", async () => {
    delete process.env.AZURE_CLIENT_ID;
    const { getGatewayToken } = await import("../auth");
    const token = await getGatewayToken();
    expect(token).toBe("dev-token");
  });

  it("getGatewayToken() returns 'dev-token' with custom scope in dev mode", async () => {
    delete process.env.AZURE_CLIENT_ID;
    const { getGatewayToken } = await import("../auth");
    const token = await getGatewayToken("custom-client-id");
    expect(token).toBe("dev-token");
  });
});
