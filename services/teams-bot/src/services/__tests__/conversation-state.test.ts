import { describe, it, expect, beforeEach, vi } from "vitest";

describe("conversation-state", () => {
  beforeEach(async () => {
    vi.resetModules();
  });

  it("getThreadId() returns undefined for unknown conversation", async () => {
    const { getThreadId, _resetState } = await import("../conversation-state");
    _resetState();
    expect(getThreadId("unknown-conv-id")).toBeUndefined();
  });

  it("setThreadId() followed by getThreadId() returns the stored thread_id", async () => {
    const { getThreadId, setThreadId, _resetState } = await import(
      "../conversation-state"
    );
    _resetState();

    setThreadId("conv-1", "thread-abc", "INC-001");
    expect(getThreadId("conv-1")).toBe("thread-abc");
  });

  it("clearExpired() removes entries older than TTL", async () => {
    const { getThreadId, setThreadId, clearExpired, _resetState } =
      await import("../conversation-state");
    _resetState();

    // Manually set a thread and then advance time past TTL
    setThreadId("old-conv", "thread-old");

    // Mock Date.now to simulate time passage (24h + 1ms)
    const realNow = Date.now;
    const futureTime = realNow() + 24 * 60 * 60 * 1000 + 1;
    vi.spyOn(Date, "now").mockReturnValue(futureTime);

    const cleared = clearExpired();
    expect(cleared).toBe(1);
    expect(getThreadId("old-conv")).toBeUndefined();

    vi.spyOn(Date, "now").mockRestore();
  });

  it("_resetState() clears all entries", async () => {
    const { getThreadId, setThreadId, _resetState } = await import(
      "../conversation-state"
    );
    _resetState();

    setThreadId("conv-a", "thread-a");
    setThreadId("conv-b", "thread-b");

    _resetState();

    expect(getThreadId("conv-a")).toBeUndefined();
    expect(getThreadId("conv-b")).toBeUndefined();
  });

  it("getThreadId() refreshes lastUsed timestamp on access", async () => {
    const { getThreadId, setThreadId, _resetState } =
      await import("../conversation-state");
    _resetState();

    setThreadId("conv-fresh", "thread-fresh");

    // Advance time to 23h (under TTL)
    const realNow = Date.now;
    const nearExpiry = realNow() + 23 * 60 * 60 * 1000;
    vi.spyOn(Date, "now").mockReturnValue(nearExpiry);

    // Access refreshes the timestamp
    expect(getThreadId("conv-fresh")).toBe("thread-fresh");

    // Now advance another 23h from the refreshed point (total 46h from creation but 23h from refresh)
    const afterRefresh = nearExpiry + 23 * 60 * 60 * 1000;
    vi.spyOn(Date, "now").mockReturnValue(afterRefresh);

    // Should still be accessible because it was refreshed
    expect(getThreadId("conv-fresh")).toBe("thread-fresh");

    vi.spyOn(Date, "now").mockRestore();
  });
});
