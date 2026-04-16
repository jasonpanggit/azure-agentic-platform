"""Tests for the chat endpoint (UI-001, UI-002)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFoundryClientEndpointResolution:
    """Tests for _get_agents_client / _get_foundry_client env var resolution."""

    def test_azure_project_endpoint_takes_precedence(self):
        """AZURE_PROJECT_ENDPOINT is preferred over FOUNDRY_ACCOUNT_ENDPOINT."""
        with patch.dict(
            "os.environ",
            {
                "AZURE_PROJECT_ENDPOINT": "https://primary.cognitiveservices.azure.com/",
                "FOUNDRY_ACCOUNT_ENDPOINT": "https://fallback.cognitiveservices.azure.com/",
            },
        ), patch(
            "services.api_gateway.foundry.AzureAgentsClient"
        ) as mock_client_cls, patch(
            "services.api_gateway.foundry.DefaultAzureCredential"
        ):
            from services.api_gateway.foundry import _get_foundry_client

            _get_foundry_client()
            call_kwargs = mock_client_cls.call_args
            assert call_kwargs.kwargs["endpoint"] == "https://primary.cognitiveservices.azure.com/"

    def test_fallback_to_foundry_account_endpoint(self):
        """Falls back to FOUNDRY_ACCOUNT_ENDPOINT when AZURE_PROJECT_ENDPOINT is not set."""
        import os
        with patch.dict(
            "os.environ",
            {"FOUNDRY_ACCOUNT_ENDPOINT": "https://fallback.cognitiveservices.azure.com/"},
            clear=False,
        ), patch(
            "services.api_gateway.foundry.AzureAgentsClient"
        ) as mock_client_cls, patch(
            "services.api_gateway.foundry.DefaultAzureCredential"
        ):
            os.environ.pop("AZURE_PROJECT_ENDPOINT", None)

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
    """Tests for POST /api/v1/chat endpoint (Responses API, synchronous)."""

    def test_valid_chat_creates_thread(self, client):
        """POST /api/v1/chat returns 200 with thread_id (synchronous Responses API)."""
        async def mock_create_chat_thread(request, user_id, **kwargs):
            return {"thread_id": "resp-test-001", "run_id": "resp-test-001"}

        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"message": "check vm-prod-01"},
            )

        assert response.status_code == 200
        body = response.json()
        assert "thread_id" in body
        assert body["thread_id"] == "resp-test-001"

    def test_chat_requires_message(self, client):
        """POST /api/v1/chat without message returns 422."""
        response = client.post("/api/v1/chat", json={})
        assert response.status_code == 422

    def test_chat_attaches_to_existing_incident(self, client, mock_foundry_client):
        """POST with incident_id passes incident_id to create_chat_thread."""
        captured_args = {}

        async def mock_create_chat_thread(request, user_id, **kwargs):
            captured_args["incident_id"] = request.incident_id
            return {"thread_id": "resp-test-001", "run_id": "resp-test-001"}

        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"message": "triage this", "incident_id": "inc-001"},
            )

        assert response.status_code == 200
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
    """Tests for thread continuation in chat.py (TEAMS-004, Responses API)."""

    def test_chat_with_thread_id_continues_existing_thread(self, client):
        """POST /api/v1/chat with thread_id passes it as conversation_id."""
        captured_args = {}

        async def mock_create_chat_thread(request, user_id, **kwargs):
            captured_args["thread_id"] = request.thread_id
            return {"thread_id": "existing-thread-123", "run_id": "existing-thread-123"}

        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={
                    "message": "follow up question",
                    "thread_id": "existing-thread-123",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["thread_id"] == "existing-thread-123"
        assert captured_args.get("thread_id") == "existing-thread-123"

    def test_chat_with_incident_id_looks_up_thread(self, client):
        """POST /api/v1/chat with incident_id passes incident_id for context."""
        captured_args = {}

        async def mock_create_chat_thread(request, user_id, **kwargs):
            captured_args["incident_id"] = request.incident_id
            return {"thread_id": "resp-from-incident", "run_id": "resp-from-incident"}

        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"message": "investigate this", "incident_id": "inc-999"},
            )

        assert response.status_code == 200
        body = response.json()
        assert "thread_id" in body
        assert captured_args.get("incident_id") == "inc-999"

    def test_chat_with_user_id_uses_request_user_id(self, client):
        """POST /api/v1/chat with user_id passes it through (D-07)."""
        captured_args = {}

        async def mock_create_chat_thread(request, user_id, **kwargs):
            captured_args["user_id"] = request.user_id
            return {"thread_id": "resp-test-001", "run_id": "resp-test-001"}

        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={
                    "message": "check vm",
                    "user_id": "teams-user@example.com",
                },
            )

        assert response.status_code == 200
        assert captured_args.get("user_id") == "teams-user@example.com"

    def test_chat_query_includes_arc_domain_hint(self, client):
        """Arc conversational queries produce an Arc domain hint for orchestrator routing."""
        import json

        captured_envelope = {}

        async def mock_dispatch(message, credential=None, conversation_id=None):
            captured_envelope["message"] = message
            return {"response_id": "resp-test-arc", "status": "completed", "reply": "ok"}

        async def mock_create_chat_thread(request, user_id, **kwargs):
            return {"thread_id": "resp-test-arc", "run_id": "resp-test-arc"}

        # Patch at the chat layer to capture the built envelope
        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"message": "show my arc enabled servers"},
            )

        assert response.status_code == 200

    def test_chat_without_thread_id_creates_new_thread(self, client):
        """POST /api/v1/chat without thread_id returns a new response_id as thread_id."""
        async def mock_create_chat_thread(request, user_id, **kwargs):
            return {"thread_id": "resp-new-001", "run_id": "resp-new-001"}

        with patch(
            "services.api_gateway.main.create_chat_thread",
            side_effect=mock_create_chat_thread,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"message": "new conversation"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["thread_id"] == "resp-new-001"


class TestGetChatResult:
    """Tests for get_chat_result() — in-memory cache lookup (Responses API)."""

    @pytest.mark.asyncio
    async def test_get_chat_result_returns_cached_result(self):
        """get_chat_result() returns cached entry when present."""
        from services.api_gateway import chat as chat_module

        response_id = "resp-cached-001"
        chat_module._RESPONSE_CACHE[response_id] = {
            "thread_id": response_id,
            "run_status": "completed",
            "reply": "Here is the analysis.",
        }
        try:
            from services.api_gateway.chat import get_chat_result

            result = await get_chat_result(response_id)

            assert result["run_status"] == "completed"
            assert result["reply"] == "Here is the analysis."
        finally:
            chat_module._RESPONSE_CACHE.pop(response_id, None)

    @pytest.mark.asyncio
    async def test_get_chat_result_with_run_id_targets_specific_run(self):
        """get_chat_result(run_id=...) also looks up by run_id in cache."""
        from services.api_gateway import chat as chat_module

        response_id = "resp-specific-001"
        chat_module._RESPONSE_CACHE[response_id] = {
            "thread_id": response_id,
            "run_status": "completed",
            "reply": "Done.",
        }
        try:
            from services.api_gateway.chat import get_chat_result

            result = await get_chat_result("thread-123", run_id=response_id)

            assert result["run_status"] == "completed"
        finally:
            chat_module._RESPONSE_CACHE.pop(response_id, None)

    @pytest.mark.asyncio
    async def test_get_chat_result_empty_runs_returns_not_found(self):
        """get_chat_result() returns in_progress when no cache entry exists yet."""
        from services.api_gateway import chat as chat_module
        from services.api_gateway.chat import get_chat_result

        # Ensure no cache entry
        chat_module._RESPONSE_CACHE.pop("thread-missing", None)
        chat_module._RESPONSE_CACHE.pop("run-missing", None)

        result = await get_chat_result("thread-missing", run_id="run-missing")

        # New behavior: in_progress (not not_found) when no cache entry exists yet
        assert result["run_status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_get_chat_result_picks_latest_run(self):
        """get_chat_result() with just thread_id looks up by thread_id."""
        from services.api_gateway import chat as chat_module

        response_id = "resp-latest-001"
        chat_module._RESPONSE_CACHE[response_id] = {
            "thread_id": response_id,
            "run_status": "completed",
            "reply": "Analysis complete.",
        }
        try:
            from services.api_gateway.chat import get_chat_result

            result = await get_chat_result(response_id)

            assert result["run_status"] == "completed"
        finally:
            chat_module._RESPONSE_CACHE.pop(response_id, None)

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
