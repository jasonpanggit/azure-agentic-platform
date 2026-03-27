import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the auth module
vi.mock("../auth", () => ({
  getGatewayToken: vi.fn().mockResolvedValue("test-token"),
}));

// Mock global fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

import { GatewayClient } from "../gateway-client";

const BASE_URL = "http://api-gateway.internal";

describe("GatewayClient", () => {
  let client: GatewayClient;

  beforeEach(() => {
    client = new GatewayClient(BASE_URL, "test-client-id");
    mockFetch.mockReset();
  });

  describe("chat()", () => {
    it("sends POST to /api/v1/chat with correct body and Bearer token", async () => {
      const responseBody = { thread_id: "thread-123", status: "created" };
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(responseBody),
      });

      const result = await client.chat({
        message: "What's wrong with vm-prod-01?",
        user_id: "operator@contoso.com",
        thread_id: "existing-thread",
      });

      expect(mockFetch).toHaveBeenCalledWith(
        `${BASE_URL}/api/v1/chat`,
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "Content-Type": "application/json",
            Authorization: "Bearer test-token",
          }),
          body: JSON.stringify({
            message: "What's wrong with vm-prod-01?",
            user_id: "operator@contoso.com",
            thread_id: "existing-thread",
          }),
        }),
      );
      expect(result).toEqual(responseBody);
    });

    it("throws on non-2xx response", async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
      });

      await expect(
        client.chat({ message: "test" }),
      ).rejects.toThrow("Chat failed: 500 Internal Server Error");
    });
  });

  describe("approveProposal()", () => {
    it("sends POST to correct URL with decided_by in body", async () => {
      mockFetch.mockResolvedValue({ ok: true });

      await client.approveProposal("appr-1", "thread-1", "admin@contoso.com");

      expect(mockFetch).toHaveBeenCalledWith(
        `${BASE_URL}/api/v1/approvals/appr-1/approve?thread_id=thread-1`,
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            Authorization: "Bearer test-token",
          }),
          body: JSON.stringify({ decided_by: "admin@contoso.com" }),
        }),
      );
    });

    it("throws on non-2xx response", async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 410,
        statusText: "Gone",
      });

      await expect(
        client.approveProposal("appr-1", "thread-1", "admin@contoso.com"),
      ).rejects.toThrow("Approve failed: 410");
    });
  });

  describe("rejectProposal()", () => {
    it("sends POST to correct URL with decided_by in body", async () => {
      mockFetch.mockResolvedValue({ ok: true });

      await client.rejectProposal("appr-2", "thread-2", "ops@contoso.com");

      expect(mockFetch).toHaveBeenCalledWith(
        `${BASE_URL}/api/v1/approvals/appr-2/reject?thread_id=thread-2`,
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            Authorization: "Bearer test-token",
          }),
          body: JSON.stringify({ decided_by: "ops@contoso.com" }),
        }),
      );
    });
  });

  describe("listPendingApprovals()", () => {
    it("sends GET to /api/v1/approvals?status=pending", async () => {
      const approvals = [
        { id: "appr-1", status: "pending", agent_name: "compute" },
      ];
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(approvals),
      });

      const result = await client.listPendingApprovals();

      expect(mockFetch).toHaveBeenCalledWith(
        `${BASE_URL}/api/v1/approvals?status=pending`,
        expect.objectContaining({
          method: "GET",
          headers: expect.objectContaining({
            Authorization: "Bearer test-token",
          }),
        }),
      );
      expect(result).toEqual(approvals);
    });

    it("throws on non-2xx response", async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
      });

      await expect(client.listPendingApprovals()).rejects.toThrow(
        "List pending approvals failed: 503",
      );
    });
  });
});
