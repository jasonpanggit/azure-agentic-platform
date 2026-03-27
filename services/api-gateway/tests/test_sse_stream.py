"""Stub: SSE stream tests (UI-002, TRIAGE-005, TRIAGE-007)."""
import pytest


class TestSSEStream:
    """Tests for SSE token and trace streaming."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_monotonic_sequence_numbers(self, client):
        """Assert seq values are strictly increasing across the token stream."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_heartbeat_interval_20_seconds(self, client):
        """Assert heartbeat comment is sent within 25 seconds."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_last_event_id_reconnect_replays_missed(self, client):
        """Assert events since Last-Event-ID are replayed on reconnect."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_ring_buffer_evicts_oldest(self, client):
        """Assert ring buffer of 1000 — insert 1100, verify oldest evicted."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_two_event_types_token_and_trace(self, client):
        """Assert both event:token and event:trace types appear in stream."""
        pass
