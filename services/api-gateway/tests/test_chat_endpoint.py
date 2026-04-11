"""Tests for the chat endpoint (UI-001, UI-002)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFoundryClientEndpointResolution:
    """Tests for _get_foundry_client env var resolution."""

    def test_azure_project_endpoint_takes_precedence(self):
        """AZURE_PROJECT_ENDPOINT is preferred over FOUNDRY_ACCOUNT_ENDPOINT."""
        with patch.dict(
            "os.environ",
            {
                "AZURE_PROJECT_ENDPOINT": "https://primary.cognitiveservices.azure.com/",
                "FOUNDRY_ACCOUNT_ENDPOINT": "https://fallback.cognitiveservices.azure.com/",
            },
        ), patch(
            "services.api_gateway.foundry.AgentsClient"
        ) as mock_client_cls, patch(
            "services.api_gateway.foundry.DefaultAzureCredential"
        ):
            from services.api_gateway.foundry import _get_foundry_client

            _get_foundry_client()
            call_kwargs = mock_client_cls.call_args
            assert call_kwargs.kwargs["endpoint"] == "https://primary.cognitiveservices.azure.com/"

    def test_fallback_to_foundry_account_endpoint(self):
        """Falls back to FOUNDRY_ACCOUNT_ENDPOINT when AZURE_PROJECT_ENDPOINT is not set."""
        env = {"FOUNDRY_ACCOUNT_ENDPOINT": "https://fallback.cognitiveservices.azure.com/"}
        with patch.dict(
            "os.environ", env, clear=False
        ), patch.dict(
            "os.environ", {"AZURE_PROJECT_ENDPOINT": ""}, clear=False
        ), patch(
            "services.api_gateway.foundry.AgentsClient"
        ) as mock_client_cls, patch(
            "services.api_gateway.foundry.DefaultAzureCredential"
        ):
            # Ensure AZURE_PROJECT_ENDPOINT is not set
            import os
            os.environ.pop("AZURE_PROJECT_ENDPOINT", None)
            os.environ["FOUNDRY_ACCOUNT_ENDPOINT"] = "https://fallback.cognitiveservices.azure.com/"

            from services.api_gateway.foundry import _get_foundry_client

            _get_foundry_client()
            call_kwargs = mock_client_cls.call_args
            assert call_kwargs.kwargs["endpoint"] == "https://fallback.cognitiveservices.azure.com/"

    def test_raises_when_no_endpoint_set(self):
        """Raises ValueError when neither endpoint env var is set."""
        with patch.dict(
            "os.environ", {}, clear=True
        ):
            from services.api_gateway.foundry import _get_foundry_client

            with pytest.raises(ValueError, match="AZURE_PROJECT_ENDPOINT"):
                _get_foundry_client()


class TestChatEndpoint:
    """Tests for POST /api/v1/chat endpoint."""

    def test_valid_chat_creates_thread(self, client):
        """POST /api/v1/chat returns 202 with thread_id."""
        mock_thread = MagicMock(id="thread-test-001")
        mock_run = MagicMock(id="run-test-001")

        mock_foundry = MagicMock()
        mock_foundry.threads.create.return_value = mock_thread
        mock_foundry.messages.create.return_value = MagicMock(id="msg-test-001")
        mock_foundry.runs.create.return_value = mock_run

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

        async def mock_create_chat_thread(request, user_id, **kwargs):
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


class TestChatThreadContinuation:
    """Tests for thread continuation in chat.py (TEAMS-004)."""

    def test_chat_with_thread_id_continues_existing_thread(self, client):
        """POST /api/v1/chat with thread_id skips create_thread (TEAMS-004)."""
        mock_foundry = MagicMock()
        mock_run = MagicMock(id="run-test-001")
        mock_foundry.messages.create.return_value = MagicMock(id="msg-test-001")
        mock_foundry.runs.create.return_value = mock_run

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}):
            response = client.post(
                "/api/v1/chat",
                json={
                    "message": "follow up question",
                    "thread_id": "existing-thread-123",
                },
            )

        assert response.status_code == 202
        body = response.json()
        assert body["thread_id"] == "existing-thread-123"
        # create_thread should NOT have been called
        mock_foundry.threads.create.assert_not_called()
        # create_message and create_run should use the existing thread_id
        mock_foundry.messages.create.assert_called_once()
        call_kwargs = mock_foundry.messages.create.call_args
        assert call_kwargs.kwargs.get("thread_id") == "existing-thread-123"

    def test_chat_with_incident_id_looks_up_thread(self, client):
        """POST /api/v1/chat with incident_id looks up thread from Cosmos (TEAMS-004)."""
        mock_foundry = MagicMock()
        mock_run = MagicMock(id="run-test-001")
        mock_foundry.messages.create.return_value = MagicMock(id="msg-test-001")
        mock_foundry.runs.create.return_value = mock_run

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}), patch(
            "services.api_gateway.chat._lookup_thread_by_incident",
            return_value="thread-from-cosmos",
        ):
            response = client.post(
                "/api/v1/chat",
                json={"message": "investigate this", "incident_id": "inc-999"},
            )

        assert response.status_code == 202
        body = response.json()
        assert body["thread_id"] == "thread-from-cosmos"
        # Should not create a new thread since Cosmos returned one
        mock_foundry.threads.create.assert_not_called()

    def test_chat_with_user_id_uses_request_user_id(self, client):
        """POST /api/v1/chat with user_id uses it instead of token sub (D-07)."""
        import json

        mock_foundry = MagicMock()
        mock_thread = MagicMock(id="thread-test-001")
        mock_run = MagicMock(id="run-test-001")
        mock_foundry.threads.create.return_value = mock_thread
        mock_foundry.messages.create.return_value = MagicMock(id="msg-test-001")
        mock_foundry.runs.create.return_value = mock_run

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}):
            response = client.post(
                "/api/v1/chat",
                json={
                    "message": "check vm",
                    "user_id": "teams-user@example.com",
                },
            )

        assert response.status_code == 202
        # Verify the envelope message uses the Teams user_id
        call_args = mock_foundry.messages.create.call_args
        envelope = json.loads(call_args.kwargs["content"])
        assert envelope["payload"]["initiated_by"] == "teams-user@example.com"

    def test_chat_query_includes_arc_domain_hint(self, client):
        """Arc conversational queries include an Arc domain hint for orchestrator routing."""
        import json

        mock_foundry = MagicMock()
        mock_thread = MagicMock(id="thread-test-arc")
        mock_run = MagicMock(id="run-test-arc")
        mock_foundry.threads.create.return_value = mock_thread
        mock_foundry.messages.create.return_value = MagicMock(id="msg-test-arc")
        mock_foundry.runs.create.return_value = mock_run

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}):
            response = client.post(
                "/api/v1/chat",
                json={"message": "show my arc enabled servers"},
            )

        assert response.status_code == 202
        envelope = json.loads(mock_foundry.messages.create.call_args.kwargs["content"])
        assert envelope["message_type"] == "operator_query"
        assert envelope["payload"]["message"] == "show my arc enabled servers"
        assert envelope["payload"]["domain_hint"] == "arc"

    def test_chat_without_thread_id_creates_new_thread(self, client):
        """POST /api/v1/chat without thread_id creates a new thread (default behavior)."""
        mock_foundry = MagicMock()
        mock_thread = MagicMock(id="thread-new-001")
        mock_run = MagicMock(id="run-test-001")
        mock_foundry.threads.create.return_value = mock_thread
        mock_foundry.messages.create.return_value = MagicMock(id="msg-test-001")
        mock_foundry.runs.create.return_value = mock_run

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch.dict("os.environ", {"ORCHESTRATOR_AGENT_ID": "agent-orch-001"}):
            response = client.post(
                "/api/v1/chat",
                json={"message": "new conversation"},
            )

        assert response.status_code == 202
        body = response.json()
        assert body["thread_id"] == "thread-new-001"
        mock_foundry.threads.create.assert_called_once()


class TestGetChatResult:
    """Tests for get_chat_result() run selection and run_id targeting."""

    @pytest.mark.asyncio
    async def test_get_chat_result_picks_latest_run(self):
        """get_chat_result() with run_id polls until terminal and returns the result."""
        mock_foundry = MagicMock()

        run_old = MagicMock(id="run-old", status="completed")
        run_new = MagicMock(id="run-new", status="in_progress")
        mock_foundry.runs.list.return_value = [run_old, run_new]

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ):
            from services.api_gateway.chat import get_chat_result

            result = await get_chat_result("thread-123")

        assert result["run_status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_get_chat_result_with_run_id_targets_specific_run(self):
        """get_chat_result(run_id=...) retrieves that specific run directly."""
        mock_foundry = MagicMock()
        mock_foundry.runs.get.return_value = MagicMock(
            id="run-specific", status="queued", required_action=None
        )

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ):
            from services.api_gateway.chat import get_chat_result

            result = await get_chat_result("thread-123", run_id="run-specific")

        assert result["run_status"] == "queued"
        mock_foundry.runs.get.assert_called_once_with(
            thread_id="thread-123", run_id="run-specific"
        )
        mock_foundry.runs.list.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_chat_result_with_run_id_targets_specific_run(self):
        """get_chat_result(run_id=...) polls until the run reaches a terminal state."""
        mock_foundry = MagicMock()

        run_done = MagicMock()
        run_done.id = "run-specific"
        run_done.status.value = "completed"
        run_done.required_action = None
        mock_foundry.runs.get.return_value = run_done
        mock_foundry.messages.list.return_value = []

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            from services.api_gateway.chat import get_chat_result

            result = await get_chat_result("thread-123", run_id="run-specific")

        assert result["run_status"] == "completed"
        mock_foundry.runs.get.assert_called_with(
            thread_id="thread-123", run_id="run-specific"
        )
        mock_foundry.runs.list.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_chat_result_empty_runs_returns_not_found(self):
        """get_chat_result() returns not_found when the run cannot be retrieved."""
        mock_foundry = MagicMock()
        # Simulate run never becoming visible (all get() calls raise)
        mock_foundry.runs.get.side_effect = Exception("Run not found")

        with patch(
            "services.api_gateway.chat._get_foundry_client",
            return_value=mock_foundry,
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            from services.api_gateway.chat import get_chat_result

            result = await get_chat_result("thread-empty", run_id="run-missing")

        assert result["run_status"] == "not_found"

    @pytest.mark.asyncio
    async def test_chat_response_includes_run_id(self):
        """POST /api/v1/chat response includes run_id for targeted polling."""
        from services.api_gateway.models import ChatResponse

        resp = ChatResponse(thread_id="t-1", run_id="r-1", status="created")
        assert resp.run_id == "r-1"

    @pytest.mark.asyncio
    async def test_chat_response_run_id_defaults_to_none(self):
        """ChatResponse.run_id defaults to None for backward compat."""
        from services.api_gateway.models import ChatResponse

        resp = ChatResponse(thread_id="t-1", status="created")
        assert resp.run_id is None


class TestDomainAgentIds:
    """Tests for _DOMAIN_AGENT_IDS env-var construction (DEBT-002)."""

    def test_domain_agent_ids_built_from_env_vars(self):
        """_DOMAIN_AGENT_IDS contains IDs from all *_AGENT_ID env vars."""
        import importlib
        import services.api_gateway.chat as chat_module

        env_patch = {
            "COMPUTE_AGENT_ID": "asst_compute_001",
            "NETWORK_AGENT_ID": "asst_network_001",
            "STORAGE_AGENT_ID": "asst_storage_001",
            "SECURITY_AGENT_ID": "asst_security_001",
            "SRE_AGENT_ID": "asst_sre_001",
            "ARC_AGENT_ID": "asst_arc_001",
            "PATCH_AGENT_ID": "asst_patch_001",
            "EOL_AGENT_ID": "asst_eol_001",
        }
        with patch.dict("os.environ", env_patch, clear=False):
            importlib.reload(chat_module)
            ids = chat_module._DOMAIN_AGENT_IDS

        assert "asst_compute_001" in ids
        assert "asst_network_001" in ids
        assert "asst_storage_001" in ids
        assert "asst_security_001" in ids
        assert "asst_sre_001" in ids
        assert "asst_arc_001" in ids
        assert "asst_patch_001" in ids
        assert "asst_eol_001" in ids
        assert len(ids) == 8

    def test_domain_agent_ids_empty_when_no_env_vars(self):
        """_DOMAIN_AGENT_IDS is empty when no *_AGENT_ID env vars are set."""
        import importlib
        import services.api_gateway.chat as chat_module

        clear_env = {
            "COMPUTE_AGENT_ID": "",
            "NETWORK_AGENT_ID": "",
            "STORAGE_AGENT_ID": "",
            "SECURITY_AGENT_ID": "",
            "SRE_AGENT_ID": "",
            "ARC_AGENT_ID": "",
            "PATCH_AGENT_ID": "",
            "EOL_AGENT_ID": "",
        }
        with patch.dict("os.environ", clear_env, clear=False):
            # Remove the keys entirely so os.environ.get() returns None
            import os
            for key in clear_env:
                os.environ.pop(key, None)
            importlib.reload(chat_module)
            ids = chat_module._DOMAIN_AGENT_IDS

        assert ids == frozenset()

    def test_domain_agent_ids_empty_logs_warning(self, caplog):
        """Warning is logged when _DOMAIN_AGENT_IDS is empty at module load."""
        import importlib
        import os
        import services.api_gateway.chat as chat_module

        for key in (
            "COMPUTE_AGENT_ID", "NETWORK_AGENT_ID", "STORAGE_AGENT_ID",
            "SECURITY_AGENT_ID", "SRE_AGENT_ID", "ARC_AGENT_ID",
            "PATCH_AGENT_ID", "EOL_AGENT_ID",
        ):
            os.environ.pop(key, None)

        import logging
        with caplog.at_level(logging.WARNING, logger="services.api_gateway.chat"):
            importlib.reload(chat_module)

        if not chat_module._DOMAIN_AGENT_IDS:
            assert any("COMPUTE_AGENT_ID" in r.message for r in caplog.records), (
                "Expected warning about missing agent IDs was not logged"
            )

    def test_domain_agent_ids_partial_env_vars(self):
        """_DOMAIN_AGENT_IDS contains only the IDs that are set."""
        import importlib
        import os
        import services.api_gateway.chat as chat_module

        # Clear all agent ID env vars first
        for key in (
            "COMPUTE_AGENT_ID", "NETWORK_AGENT_ID", "STORAGE_AGENT_ID",
            "SECURITY_AGENT_ID", "SRE_AGENT_ID", "ARC_AGENT_ID",
            "PATCH_AGENT_ID", "EOL_AGENT_ID",
        ):
            os.environ.pop(key, None)

        with patch.dict("os.environ", {"COMPUTE_AGENT_ID": "asst_compute_x", "SRE_AGENT_ID": "asst_sre_x"}, clear=False):
            importlib.reload(chat_module)
            ids = chat_module._DOMAIN_AGENT_IDS

        assert ids == frozenset({"asst_compute_x", "asst_sre_x"})

    def test_no_hardcoded_asst_ids_in_chat_module(self):
        """Verify no hardcoded asst_* IDs remain in chat.py source."""
        import inspect
        import services.api_gateway.chat as chat_module

        source = inspect.getsource(chat_module)
        # None of the 8 original hardcoded IDs should appear
        hardcoded_ids = [
            "asst_rPDw83BXGrmNDE73xMy6IFE5",
            "asst_ynlfwck70rb2olLGohZSWoKz",
            "asst_BDm56ofymsrQnbdvutNmP7fI",
            "asst_bHgDk44qPDLoqqMsln4GjPoK",
            "asst_4JoNlqMcQC3WPq9cTpowFfPe",
            "asst_YFobGKxsDGo9j1oIrimzWyfL",
            "asst_AEFTnaxXKMpOUCmjiLWhzlsW",
            "asst_hUNs2ASp1WsrMvGvuwA5T495",
        ]
        for asst_id in hardcoded_ids:
            assert asst_id not in source, f"Hardcoded agent ID still present: {asst_id}"
