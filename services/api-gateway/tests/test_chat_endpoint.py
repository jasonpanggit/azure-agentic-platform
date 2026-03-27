"""Stub: Chat endpoint tests (UI-001, UI-002)."""
import pytest


class TestChatEndpoint:
    """Tests for POST /api/v1/chat endpoint."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_valid_chat_creates_thread(self, client):
        """POST /api/v1/chat returns 202 with thread_id."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_chat_requires_message(self, client):
        """POST /api/v1/chat without message returns 422."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-02")
    def test_chat_attaches_to_existing_incident(self, client, mock_foundry_client):
        """POST with incident_id reuses existing thread."""
        pass
