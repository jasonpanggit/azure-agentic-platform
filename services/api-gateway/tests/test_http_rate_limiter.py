"""Tests for per-IP HTTP rate limiter (CONCERNS 1.5)."""
import time
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.api_gateway.http_rate_limiter import HttpRateLimiter


class TestHttpRateLimiter:
    """Tests for HttpRateLimiter sliding window logic."""

    def test_allows_requests_within_limit(self):
        limiter = HttpRateLimiter(max_per_minute=5)
        for _ in range(5):
            result = limiter.check("127.0.0.1")
            assert result is True

    def test_blocks_request_exceeding_limit(self):
        limiter = HttpRateLimiter(max_per_minute=5)
        for _ in range(5):
            limiter.check("127.0.0.1")
        assert limiter.check("127.0.0.1") is False

    def test_different_ips_tracked_independently(self):
        limiter = HttpRateLimiter(max_per_minute=2)
        limiter.check("1.2.3.4")
        limiter.check("1.2.3.4")
        assert limiter.check("1.2.3.4") is False
        # Different IP should still pass
        assert limiter.check("5.6.7.8") is True

    def test_retry_after_seconds_returned_on_block(self):
        limiter = HttpRateLimiter(max_per_minute=1)
        limiter.check("127.0.0.1")
        retry_after = limiter.retry_after("127.0.0.1")
        assert 0 < retry_after <= 60

    def test_record_appended_after_allow(self):
        limiter = HttpRateLimiter(max_per_minute=10)
        limiter.check("10.0.0.1")
        assert len(limiter._windows["10.0.0.1"]) == 1

    def test_window_expiry_allows_requests_after_60_seconds(self):
        """After 60 seconds, the sliding window expires and requests are allowed again."""
        import unittest.mock

        call_count = [0]
        start_time = time.monotonic()

        def fake_monotonic():
            call_count[0] += 1
            # check #1 uses calls 1-2 (clean + append), check #2 uses call 3 (clean only)
            # From call #4 onward (the 3rd check), simulate 61 seconds have passed
            if call_count[0] <= 3:
                return start_time
            return start_time + 61.0

        limiter = HttpRateLimiter(max_per_minute=1)

        with unittest.mock.patch('time.monotonic', fake_monotonic):
            # Use up the limit
            assert limiter.check("127.0.0.1") is True
            assert limiter.check("127.0.0.1") is False
            # After 61 seconds (simulated), should be allowed again
            assert limiter.check("127.0.0.1") is True


class TestRateLimitEndpoints:
    """Integration tests — rate limiter wired on /api/v1/chat and /api/v1/incidents."""

    def _make_app_with_limiter(self, chat_limit: int, incidents_limit: int) -> FastAPI:
        """Build a minimal FastAPI app with rate limiter middleware for testing."""
        app = FastAPI()
        chat_limiter = HttpRateLimiter(max_per_minute=chat_limit)
        incidents_limiter = HttpRateLimiter(max_per_minute=incidents_limit)

        @app.post("/api/v1/chat")
        async def chat_endpoint(request: Request):
            ip = request.client.host if request.client else "unknown"
            if not chat_limiter.check(ip):
                retry = chat_limiter.retry_after(ip)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": "Rate limit exceeded", "retry_after": retry},
                    status_code=429,
                )
            return {"status": "ok"}

        @app.get("/api/v1/incidents")
        async def incidents_endpoint(request: Request):
            ip = request.client.host if request.client else "unknown"
            if not incidents_limiter.check(ip):
                retry = incidents_limiter.retry_after(ip)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": "Rate limit exceeded", "retry_after": retry},
                    status_code=429,
                )
            return {"incidents": []}

        return app

    def test_chat_returns_429_on_11th_request(self):
        app = self._make_app_with_limiter(chat_limit=10, incidents_limit=30)
        client = TestClient(app)
        for i in range(10):
            resp = client.post("/api/v1/chat", json={})
            assert resp.status_code == 200, f"Request {i+1} should be allowed"
        resp = client.post("/api/v1/chat", json={})
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"] == "Rate limit exceeded"
        assert "retry_after" in body

    def test_incidents_returns_429_on_31st_request(self):
        app = self._make_app_with_limiter(chat_limit=10, incidents_limit=30)
        client = TestClient(app)
        for i in range(30):
            resp = client.get("/api/v1/incidents")
            assert resp.status_code == 200, f"Request {i+1} should be allowed"
        resp = client.get("/api/v1/incidents")
        assert resp.status_code == 429
