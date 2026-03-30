import { describe, it, expect } from "vitest";
import request from "supertest";
import type { Express } from "express";

/**
 * Teams bot integration tests.
 *
 * These tests verify the bot Express server is wired correctly — health
 * endpoint returns 200, and /api/messages route is registered in the
 * Express router stack.
 *
 * The /api/messages route deliberately uses Express router introspection
 * rather than a live HTTP call because CloudAdapter.process() performs an
 * outbound network call to login.microsoftonline.com for JWT validation,
 * which hangs indefinitely in offline CI environments.
 *
 * Full Teams round-trip tests (requiring live Teams environment + bot
 * registration) are kept as inner it.skip with explicit reason strings.
 */

// Import the Express app (not the listen call)
// app is exported from index.ts: export { app }; // For testing
import { app } from "../../index";

/** Collect all registered routes from an Express app's router stack. */
function getRegisteredRoutes(expressApp: Express): Array<{ method: string; path: string }> {
  const routes: Array<{ method: string; path: string }> = [];
  // Express stores routes in app._router.stack
  const stack = (expressApp as unknown as { _router: { stack: Array<{ route?: { path: string; methods: Record<string, boolean> } }> } })._router?.stack ?? [];
  for (const layer of stack) {
    if (layer.route) {
      const methods = Object.keys(layer.route.methods).map((m) => m.toUpperCase());
      for (const method of methods) {
        routes.push({ method, path: layer.route.path as string });
      }
    }
  }
  return routes;
}

describe("Teams bot integration tests", () => {

  describe("Active tests — run in CI without live environment", () => {

    it("GET /health returns 200 (liveness probe)", async () => {
      const response = await request(app).get("/health");
      expect(response.status).toBe(200);
      expect(response.body).toMatchObject({ status: expect.stringMatching(/ok|healthy/) });
    });

    it("POST /api/messages route is registered in the Express router (route existence check)", () => {
      // CloudAdapter.process() makes outbound calls to login.microsoftonline.com for JWT
      // validation, which hangs in offline CI. Verify route registration via router introspection
      // instead — this proves the endpoint is wired without triggering Bot Framework auth.
      const routes = getRegisteredRoutes(app);
      const messagesRoute = routes.find(
        (r) => r.method === "POST" && r.path === "/api/messages"
      );
      expect(
        messagesRoute,
        "POST /api/messages must be registered — route not found in Express router stack"
      ).toBeDefined();
    });

  });

  describe("Phase 6 integration tests (require live Teams environment)", () => {

    it.skip("SC-1: Natural-language message routed to Orchestrator returns triage summary within 30s", async () => {
      // Requires: registered Teams bot, live Foundry endpoint, real auth token
      // Send "investigate the CPU alert on vm-prod-01" to the bot
      // Assert: response is a structured triage summary within 30 seconds
    });

    it.skip("SC-2: Alert fires -> Adaptive Card posted to channel within 10s of Cosmos record creation", async () => {
      // Requires: Teams channel, Cosmos DB with live data, bot registration
    });

    it.skip("SC-3: Approval card posted -> operator clicks Reject -> Cosmos updated -> card updated in-place", async () => {
      // Requires: Teams channel, high-risk remediation proposal, live approval flow
    });

    it.skip("SC-4: Web UI and Teams share same thread_id for an incident", async () => {
      // Requires: live Web UI + Teams bot running against same Foundry instance
    });

    it.skip("SC-5: Unacted approval triggers escalation reminder after configured interval", async () => {
      // Requires: pending approval in Cosmos, running escalation scheduler, Teams channel
    });

    it.skip("SC-6: Approved remediation executes -> outcome card posted within 60s", async () => {
      // Requires: synthetic low-risk remediation, full Foundry agent pipeline
    });

  });

});
