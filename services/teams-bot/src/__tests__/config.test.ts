import { describe, it, expect } from "vitest";
import { loadConfig } from "../config";

// Helper to set env vars and restore them
function withEnv(vars: Record<string, string | undefined>, fn: () => void): void {
  const original: Record<string, string | undefined> = {};
  for (const key of Object.keys(vars)) {
    original[key] = process.env[key];
    if (vars[key] === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = vars[key];
    }
  }
  try {
    fn();
  } finally {
    for (const key of Object.keys(original)) {
      if (original[key] === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = original[key];
      }
    }
  }
}

const requiredEnv = {
  BOT_ID: "bot-123",
  API_GATEWAY_INTERNAL_URL: "http://api-gateway.internal",
  WEB_UI_PUBLIC_URL: "https://ui.example.com",
};

describe("loadConfig", () => {
  it("throws when BOT_ID is missing", () => {
    withEnv({ ...requiredEnv, BOT_ID: undefined }, () => {
      expect(() => loadConfig()).toThrow("BOT_ID");
    });
  });

  it("throws when API_GATEWAY_INTERNAL_URL is missing", () => {
    withEnv({ ...requiredEnv, API_GATEWAY_INTERNAL_URL: undefined }, () => {
      expect(() => loadConfig()).toThrow("API_GATEWAY_INTERNAL_URL");
    });
  });

  it("throws when WEB_UI_PUBLIC_URL is missing", () => {
    withEnv({ ...requiredEnv, WEB_UI_PUBLIC_URL: undefined }, () => {
      expect(() => loadConfig()).toThrow("WEB_UI_PUBLIC_URL");
    });
  });

  it("returns default escalationIntervalMinutes of 15 when env var not set", () => {
    withEnv(
      { ...requiredEnv, ESCALATION_INTERVAL_MINUTES: undefined },
      () => {
        const config = loadConfig();
        expect(config.escalationIntervalMinutes).toBe(15);
      },
    );
  });

  it("returns default port of 3978 when env var not set", () => {
    withEnv({ ...requiredEnv, PORT: undefined }, () => {
      const config = loadConfig();
      expect(config.port).toBe(3978);
    });
  });

  it("returns correct values when all required env vars are set", () => {
    withEnv(requiredEnv, () => {
      const config = loadConfig();
      expect(config.botId).toBe("bot-123");
      expect(config.apiGatewayInternalUrl).toBe("http://api-gateway.internal");
      expect(config.webUiPublicUrl).toBe("https://ui.example.com");
    });
  });
});
