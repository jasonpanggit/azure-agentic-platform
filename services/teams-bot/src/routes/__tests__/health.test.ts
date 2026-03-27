import { describe, it, expect } from "vitest";
import express from "express";
import request from "supertest";
import { healthRouter } from "../../routes/health";

const app = express();
app.use(healthRouter);

describe("GET /health", () => {
  it("returns 200 with status 'ok'", async () => {
    const res = await request(app).get("/health");
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
  });

  it("response body contains version '1.0.0'", async () => {
    const res = await request(app).get("/health");
    expect(res.body.version).toBe("1.0.0");
  });
});
