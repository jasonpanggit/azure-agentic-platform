"""Stub: SSE heartbeat interval test (UI-008)."""
import pytest


class TestSSEHeartbeat:
    """Tests for SSE heartbeat comment emission (UI-008).

    The SSE route handler must emit a `: heartbeat` comment every 20 seconds
    to prevent Azure Container Apps 240-second idle timeout from terminating
    the connection.
    """

    @pytest.mark.skip(reason="stub - implement in Plan 05-02")
    def test_heartbeat_sent_every_20_seconds(self):
        """Assert that the SSE route emits a :heartbeat comment every 20s."""
        pass

    @pytest.mark.skip(reason="stub - implement in Plan 05-02")
    def test_heartbeat_prevents_container_app_timeout(self):
        """Assert heartbeat is sent before 240s Container Apps timeout."""
        pass
