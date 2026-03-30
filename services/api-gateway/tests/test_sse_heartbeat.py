"""SSE heartbeat tests — moved to web UI service.

The SSE heartbeat (UI-008) is implemented in the Next.js web UI at:
  services/web-ui/app/api/stream/route.ts

Tests for the heartbeat are in:
  services/web-ui/__tests__/stream.test.ts

These Python stubs are kept as placeholders to avoid breaking pytest
collection — they are permanently skipped with an explanatory message.
"""
import pytest


class TestSSEHeartbeat:
    """SSE heartbeat tests — see services/web-ui/__tests__/stream.test.ts."""

    @pytest.mark.skip(
        reason=(
            "SSE heartbeat is implemented in services/web-ui/app/api/stream/route.ts "
            "(TypeScript/Next.js). Tests are in services/web-ui/__tests__/stream.test.ts. "
            "This Python file is kept as a tombstone to document the move."
        )
    )
    def test_heartbeat_sent_every_20_seconds(self):
        pass

    @pytest.mark.skip(
        reason=(
            "SSE heartbeat is implemented in services/web-ui/app/api/stream/route.ts. "
            "See services/web-ui/__tests__/stream.test.ts for the Jest implementation."
        )
    )
    def test_heartbeat_prevents_container_app_timeout(self):
        pass
