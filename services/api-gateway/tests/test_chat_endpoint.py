"""Tests for the chat endpoint (UI-001, UI-002)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestChatEndpoint:
    """Tests for POST /api/v1/chat endpoint."""

    def test_valid_chat_creates_thread(self, client):
        """POST /api/v1/chat returns 202 with thread_id."""
        mock_thread = MagicMock(id="thread-test-001")
        mock_run = MagicMock(id="run-test-001")

        mock_foundry = MagicMock()
        mock_foundry.agents.create_thread.return_value = mock_thread
        mock_foundry.agents.create_message.return_value = MagicMock(id="msg-test-001")
        mock_foundry.agents.create_run.return_value = mock_run

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}):
            response = client.post(
                "/api/v1/chat",
                json={"message": "check vm-prod-01"},
            )

        assert response.status_code == 202
        body = response.json()
        assert "thread_id" in body
        assert body["thread_id"] == "thread-test-001"

    def test_chat_requires_message(self, client):
        """POST /api/v1/chat without message returns 422."""
        response = client.post("/api/v1/chat", json={})
        assert response.status_code == 422

    def test_chat_attaches_to_existing_incident(self, client, mock_foundry_client):
        """POST with incident_id reuses existing thread."""
        captured_args = {}

        async def mock_create_chat_thread(request, user_id):
            captured_args["incident_id"] = request.incident_id
            return {"thread_id": "thread-test-001", "run_id": "run-test-001"}

        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"message": "triage this", "incident_id": "inc-001"},
            )

        assert response.status_code == 202
        assert captured_args.get("incident_id") == "inc-001"

    def test_chat_request_accepts_thread_id(self):
        """ChatRequest model accepts optional thread_id field (TEAMS-004)."""
        from services.api_gateway.models import ChatRequest

        req = ChatRequest(message="hello", thread_id="test-thread")
        assert req.thread_id == "test-thread"

    def test_chat_request_accepts_user_id(self):
        """ChatRequest model accepts optional user_id field (D-07)."""
        from services.api_gateway.models import ChatRequest

        req = ChatRequest(message="hello", user_id="user@example.com")
        assert req.user_id == "user@example.com"

    def test_chat_request_defaults_thread_id_to_none(self):
        """ChatRequest thread_id defaults to None when not provided."""
        from services.api_gateway.models import ChatRequest

        req = ChatRequest(message="hello")
        assert req.thread_id is None

    def test_chat_request_defaults_user_id_to_none(self):
        """ChatRequest user_id defaults to None when not provided."""
        from services.api_gateway.models import ChatRequest

        req = ChatRequest(message="hello")
        assert req.user_id is None
