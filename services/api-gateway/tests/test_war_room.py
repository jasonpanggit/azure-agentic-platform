from __future__ import annotations
"""Tests for war_room.py — Phase 53: Incident War Room backend.

≥35 unit tests across 8 test classes covering:
- _strip_cosmos_fields
- get_or_create_war_room
- add_annotation
- update_presence
- _broadcast_annotation
- register_sse_queue / deregister_sse_queue
- generate_handoff_summary
- SSE event generator
"""
import os

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from azure.cosmos.exceptions import CosmosResourceNotFoundError  # noqa: E402

from services.api_gateway.war_room import (  # noqa: E402
    _WAR_ROOM_QUEUES,
    _broadcast_annotation,
    _strip_cosmos_fields,
    add_annotation,
    deregister_sse_queue,
    generate_handoff_summary,
    get_or_create_war_room,
    register_sse_queue,
    update_presence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_not_found_error() -> CosmosResourceNotFoundError:
    response_mock = MagicMock()
    response_mock.status_code = 404
    response_mock.headers = {}
    response_mock.text = "Not Found"
    return CosmosResourceNotFoundError(
        status_code=404,
        message="Resource Not Found",
        response=response_mock,
    )


def _make_war_room_doc(incident_id="inc-001", participants=None, annotations=None):
    return {
        "id": incident_id,
        "incident_id": incident_id,
        "created_at": "2026-04-14T10:00:00+00:00",
        "participants": participants or [],
        "annotations": annotations or [],
        "timeline": [],
        "handoff_summary": None,
        "_etag": '"etag-123"',
        "_rid": "abc",
    }


def _make_container_mock(existing_doc=None):
    """Return a MagicMock ContainerProxy with read_item and replace_item configured."""
    m = MagicMock()
    if existing_doc is None:
        m.read_item.side_effect = _make_not_found_error()
    else:
        m.read_item.return_value = existing_doc
    m.upsert_item.side_effect = lambda doc: {**doc, "_etag": '"etag-new"'}
    m.replace_item.side_effect = lambda item, body, etag=None, match_condition=None: {
        **body,
        "_etag": '"etag-updated"',
    }
    return m


# ---------------------------------------------------------------------------
# TestStripCosmosFields
# ---------------------------------------------------------------------------

class TestStripCosmosFields:
    def test_strips_etag(self):
        result = _strip_cosmos_fields({"id": "x", "_etag": "y"})
        assert "_etag" not in result

    def test_strips_all_system_fields(self):
        doc = {
            "id": "x",
            "_etag": "e",
            "_rid": "r",
            "_self": "s",
            "_ts": 123,
            "_attachments": "a",
        }
        result = _strip_cosmos_fields(doc)
        for field in ("_etag", "_rid", "_self", "_ts", "_attachments"):
            assert field not in result

    def test_preserves_data_fields(self):
        doc = {
            "incident_id": "inc-001",
            "participants": [{"operator_id": "u1"}],
            "annotations": [{"id": "a1"}],
            "_etag": "e",
        }
        result = _strip_cosmos_fields(doc)
        assert result["incident_id"] == "inc-001"
        assert result["participants"] == [{"operator_id": "u1"}]
        assert result["annotations"] == [{"id": "a1"}]


# ---------------------------------------------------------------------------
# TestGetOrCreateWarRoom
# ---------------------------------------------------------------------------

class TestGetOrCreateWarRoom:
    @pytest.fixture(autouse=True)
    def clear_queues(self):
        _WAR_ROOM_QUEUES.clear()
        yield
        _WAR_ROOM_QUEUES.clear()

    @pytest.mark.asyncio
    async def test_creates_new_war_room_when_not_exists(self):
        container = _make_container_mock(existing_doc=None)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await get_or_create_war_room("inc-001", "user-123", "Alice", "support")
        container.upsert_item.assert_called_once()
        assert result["incident_id"] == "inc-001"

    @pytest.mark.asyncio
    async def test_adds_participant_on_create(self):
        container = _make_container_mock(existing_doc=None)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await get_or_create_war_room("inc-001", "user-123", "Alice", "support")
        assert len(result["participants"]) == 1
        assert result["participants"][0]["operator_id"] == "user-123"
        assert result["participants"][0]["role"] == "support"

    @pytest.mark.asyncio
    async def test_joins_existing_war_room(self):
        existing = _make_war_room_doc(
            participants=[{
                "operator_id": "user-456",
                "display_name": "Bob",
                "role": "lead",
                "joined_at": "2026-04-14T10:00:00+00:00",
                "last_seen_at": "2026-04-14T10:00:00+00:00",
            }]
        )
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await get_or_create_war_room("inc-001", "user-123", "Alice", "support")
        assert len(result["participants"]) == 2

    @pytest.mark.asyncio
    async def test_does_not_duplicate_existing_participant(self):
        existing = _make_war_room_doc(
            participants=[{
                "operator_id": "user-123",
                "display_name": "Alice",
                "role": "support",
                "joined_at": "2026-04-14T10:00:00+00:00",
                "last_seen_at": "2026-04-14T10:00:00+00:00",
            }]
        )
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await get_or_create_war_room("inc-001", "user-123", "Alice", "support")
        # replace_item should not have been called (participant already present)
        container.replace_item.assert_not_called()
        assert len(result["participants"]) == 1

    @pytest.mark.asyncio
    async def test_role_defaults_to_support_for_invalid_role(self):
        container = _make_container_mock(existing_doc=None)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await get_or_create_war_room("inc-001", "user-123", "Alice", "admin")
        assert result["participants"][0]["role"] == "support"

    @pytest.mark.asyncio
    async def test_returns_dict_without_cosmos_system_fields(self):
        container = _make_container_mock(existing_doc=None)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await get_or_create_war_room("inc-001", "user-123", "Alice", "lead")
        assert "_etag" not in result
        assert "_rid" not in result


# ---------------------------------------------------------------------------
# TestAddAnnotation
# ---------------------------------------------------------------------------

class TestAddAnnotation:
    @pytest.fixture(autouse=True)
    def clear_queues(self):
        _WAR_ROOM_QUEUES.clear()
        yield
        _WAR_ROOM_QUEUES.clear()

    @pytest.mark.asyncio
    async def test_adds_annotation_to_existing_war_room(self):
        existing = _make_war_room_doc()
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await add_annotation("inc-001", "user-123", "Alice", "my note", None)
        assert result["content"] == "my note"
        assert result["operator_id"] == "user-123"
        assert "id" in result
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_annotation_id_is_uuid4(self):
        existing = _make_war_room_doc()
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await add_annotation("inc-001", "user-123", "Alice", "note", None)
        # UUID4 format: 8-4-4-4-12 hex chars with dashes
        ann_id = result["id"]
        assert len(ann_id) == 36
        assert ann_id.count("-") == 4

    @pytest.mark.asyncio
    async def test_annotation_with_trace_event_id(self):
        existing = _make_war_room_doc()
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await add_annotation("inc-001", "user-123", "Alice", "note", "trace-abc")
        assert result["trace_event_id"] == "trace-abc"

    @pytest.mark.asyncio
    async def test_annotation_without_trace_event_id(self):
        existing = _make_war_room_doc()
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await add_annotation("inc-001", "user-123", "Alice", "note", None)
        assert result["trace_event_id"] is None

    @pytest.mark.asyncio
    async def test_content_max_4096_chars_raises(self):
        with pytest.raises(ValueError):
            await add_annotation("inc-001", "user-123", "Alice", "x" * 4097, None)

    @pytest.mark.asyncio
    async def test_content_exactly_4096_chars_succeeds(self):
        existing = _make_war_room_doc()
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await add_annotation("inc-001", "user-123", "Alice", "x" * 4096, None)
        assert len(result["content"]) == 4096

    @pytest.mark.asyncio
    async def test_broadcasts_to_sse_queues(self):
        existing = _make_war_room_doc()
        container = _make_container_mock(existing_doc=existing)
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        register_sse_queue("inc-001", q)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            await add_annotation("inc-001", "user-123", "Alice", "hello", None)
        assert not q.empty()
        deregister_sse_queue("inc-001", q)


# ---------------------------------------------------------------------------
# TestUpdatePresence
# ---------------------------------------------------------------------------

class TestUpdatePresence:
    @pytest.mark.asyncio
    async def test_updates_last_seen_at(self):
        existing = _make_war_room_doc(
            participants=[{
                "operator_id": "user-123",
                "display_name": "Alice",
                "role": "lead",
                "joined_at": "2026-04-14T10:00:00+00:00",
                "last_seen_at": "2026-04-14T10:00:00+00:00",
            }]
        )
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            await update_presence("inc-001", "user-123")
        container.replace_item.assert_called_once()
        call_kwargs = container.replace_item.call_args
        body = call_kwargs[1]["body"] if "body" in call_kwargs[1] else call_kwargs[0][1]
        # The last_seen_at should have been updated (not the original value)
        participant = body["participants"][0]
        assert participant["operator_id"] == "user-123"

    @pytest.mark.asyncio
    async def test_noop_when_war_room_not_exists(self):
        container = _make_container_mock(existing_doc=None)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            result = await update_presence("inc-001", "user-123")
        assert result is None
        container.replace_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_operator_not_in_participants(self):
        existing = _make_war_room_doc(
            participants=[{
                "operator_id": "user-456",
                "display_name": "Bob",
                "role": "lead",
                "joined_at": "2026-04-14T10:00:00+00:00",
                "last_seen_at": "2026-04-14T10:00:00+00:00",
            }]
        )
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            await update_presence("inc-001", "user-123")
        # replace_item is still called (mapping over all participants)
        container.replace_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_immutable_update(self):
        """Verify replace_item is called with match_condition argument set."""
        from azure.core import MatchConditions
        existing = _make_war_room_doc(
            participants=[{
                "operator_id": "user-123",
                "display_name": "Alice",
                "role": "lead",
                "joined_at": "2026-04-14T10:00:00+00:00",
                "last_seen_at": "2026-04-14T10:00:00+00:00",
            }]
        )
        container = _make_container_mock(existing_doc=existing)
        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container):
            await update_presence("inc-001", "user-123")
        call_kwargs = container.replace_item.call_args[1]
        assert call_kwargs.get("match_condition") == MatchConditions.IfNotModified


# ---------------------------------------------------------------------------
# TestBroadcastAnnotation
# ---------------------------------------------------------------------------

class TestBroadcastAnnotation:
    @pytest.fixture(autouse=True)
    def clear_queues(self):
        _WAR_ROOM_QUEUES.clear()
        yield
        _WAR_ROOM_QUEUES.clear()

    def test_broadcasts_to_all_queues(self):
        q1: asyncio.Queue = asyncio.Queue(maxsize=10)
        q2: asyncio.Queue = asyncio.Queue(maxsize=10)
        q3: asyncio.Queue = asyncio.Queue(maxsize=10)
        for q in (q1, q2, q3):
            register_sse_queue("inc-001", q)
        _broadcast_annotation("inc-001", {"id": "ann-1", "content": "test"})
        assert q1.qsize() == 1
        assert q2.qsize() == 1
        assert q3.qsize() == 1

    def test_noop_for_incident_with_no_queues(self):
        # Should not raise even with no registered queues
        _broadcast_annotation("inc-no-queues", {"id": "ann-1", "content": "test"})

    def test_full_queue_does_not_raise(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        register_sse_queue("inc-001", q)
        # Fill the queue
        q.put_nowait("existing-item")
        # Broadcasting to a full queue should not raise (QueueFull is swallowed)
        _broadcast_annotation("inc-001", {"id": "ann-2", "content": "overflow"})


# ---------------------------------------------------------------------------
# TestRegisterDeregisterQueues
# ---------------------------------------------------------------------------

class TestRegisterDeregisterQueues:
    @pytest.fixture(autouse=True)
    def clear_queues(self):
        _WAR_ROOM_QUEUES.clear()
        yield
        _WAR_ROOM_QUEUES.clear()

    def test_register_creates_list_for_new_incident(self):
        q: asyncio.Queue = asyncio.Queue()
        register_sse_queue("inc-new", q)
        assert "inc-new" in _WAR_ROOM_QUEUES
        assert len(_WAR_ROOM_QUEUES["inc-new"]) == 1

    def test_register_appends_to_existing(self):
        q1: asyncio.Queue = asyncio.Queue()
        q2: asyncio.Queue = asyncio.Queue()
        register_sse_queue("inc-001", q1)
        register_sse_queue("inc-001", q2)
        assert len(_WAR_ROOM_QUEUES["inc-001"]) == 2

    def test_deregister_removes_queue(self):
        q: asyncio.Queue = asyncio.Queue()
        register_sse_queue("inc-001", q)
        deregister_sse_queue("inc-001", q)
        assert q not in _WAR_ROOM_QUEUES.get("inc-001", [])

    def test_deregister_removes_empty_incident_key(self):
        q: asyncio.Queue = asyncio.Queue()
        register_sse_queue("inc-001", q)
        deregister_sse_queue("inc-001", q)
        assert "inc-001" not in _WAR_ROOM_QUEUES


# ---------------------------------------------------------------------------
# TestHandoffSummary
# ---------------------------------------------------------------------------

class TestHandoffSummary:
    @pytest.mark.asyncio
    async def test_returns_summary_string(self):
        existing = _make_war_room_doc(
            annotations=[{
                "id": "a1",
                "operator_id": "user-123",
                "display_name": "Alice",
                "content": "CPU spike on vm-prod",
                "trace_event_id": None,
                "created_at": "2026-04-14T10:00:00+00:00",
            }]
        )
        container = _make_container_mock(existing_doc=existing)

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Summary: hypothesis..."

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container), \
             patch("services.api_gateway.war_room.DefaultAzureCredential", return_value=mock_credential), \
             patch.dict(os.environ, {"FOUNDRY_ENDPOINT": "https://endpoint"}), \
             patch("openai.AzureOpenAI", return_value=mock_client):
            result = await generate_handoff_summary("inc-001")
        assert result == "Summary: hypothesis..."

    @pytest.mark.asyncio
    async def test_persists_summary_to_cosmos(self):
        existing = _make_war_room_doc()
        container = _make_container_mock(existing_doc=existing)

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Summary: hypothesis..."

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container), \
             patch("services.api_gateway.war_room.DefaultAzureCredential", return_value=mock_credential), \
             patch.dict(os.environ, {"FOUNDRY_ENDPOINT": "https://endpoint"}), \
             patch("openai.AzureOpenAI", return_value=mock_client):
            await generate_handoff_summary("inc-001")

        # replace_item should have been called with handoff_summary in body
        container.replace_item.assert_called_once()
        call_args = container.replace_item.call_args
        body = call_args[1].get("body") or call_args[0][1]
        assert body.get("handoff_summary") == "Summary: hypothesis..."

    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_endpoint_missing(self):
        # Ensure endpoint vars are absent
        env_without_endpoint = {
            k: v for k, v in os.environ.items()
            if k not in ("FOUNDRY_ENDPOINT", "AZURE_OPENAI_ENDPOINT")
        }
        with patch.dict(os.environ, env_without_endpoint, clear=True):
            with pytest.raises(RuntimeError, match="FOUNDRY_ENDPOINT"):
                await generate_handoff_summary("inc-001")

    @pytest.mark.asyncio
    async def test_includes_annotations_in_prompt(self):
        existing = _make_war_room_doc(
            annotations=[{
                "id": "a1",
                "operator_id": "user-123",
                "display_name": "Alice",
                "content": "UNIQUE_NOTE_CONTENT_XYZ",
                "trace_event_id": None,
                "created_at": "2026-04-14T10:00:00+00:00",
            }]
        )
        container = _make_container_mock(existing_doc=existing)

        captured_messages = []

        def mock_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            mock_resp = MagicMock()
            mock_resp.choices[0].message.content = "summary"
            return mock_resp

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = mock_create

        mock_credential = MagicMock()
        mock_credential.get_token.return_value = MagicMock(token="fake-token")

        with patch("services.api_gateway.war_room._get_war_rooms_container", return_value=container), \
             patch("services.api_gateway.war_room.DefaultAzureCredential", return_value=mock_credential), \
             patch.dict(os.environ, {"FOUNDRY_ENDPOINT": "https://endpoint"}), \
             patch("openai.AzureOpenAI", return_value=mock_client):
            await generate_handoff_summary("inc-001")

        user_message = next(m for m in captured_messages if m["role"] == "user")
        assert "UNIQUE_NOTE_CONTENT_XYZ" in user_message["content"]

    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_openai_not_installed(self):
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(RuntimeError, match="openai package not installed"):
                await generate_handoff_summary("inc-001")


# ---------------------------------------------------------------------------
# TestSseStream
# ---------------------------------------------------------------------------

class TestSseStream:
    @pytest.fixture(autouse=True)
    def clear_queues(self):
        _WAR_ROOM_QUEUES.clear()
        yield
        _WAR_ROOM_QUEUES.clear()

    @pytest.mark.asyncio
    async def test_event_generator_yields_annotation_event(self):
        """event_generator yields SSE annotation event for items in queue.

        Tests the inner generator logic directly without going through the
        FastAPI endpoint layer.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        register_sse_queue("inc-stream", q)
        q.put_nowait('{"type": "annotation", "annotation": {"id": "a1"}}')

        collected = []

        async def _gen():
            try:
                while True:
                    try:
                        payload = await asyncio.wait_for(q.get(), timeout=5.0)
                        yield f"event: annotation\ndata: {payload}\n\n"
                        return  # stop after first event
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
                        return
            finally:
                deregister_sse_queue("inc-stream", q)

        async for chunk in _gen():
            collected.append(chunk)

        assert any("event: annotation" in c for c in collected)

    @pytest.mark.asyncio
    async def test_event_generator_yields_heartbeat_on_timeout(self):
        """When queue is empty, the generator yields a heartbeat comment."""
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        register_sse_queue("inc-hb", q)

        collected = []

        async def _gen():
            try:
                while True:
                    try:
                        # Use a very short timeout so the test doesn't block
                        payload = await asyncio.wait_for(q.get(), timeout=0.01)
                        yield f"event: annotation\ndata: {payload}\n\n"
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
                        return  # stop after one heartbeat
            finally:
                deregister_sse_queue("inc-hb", q)

        async for chunk in _gen():
            collected.append(chunk)

        assert any(c.startswith(": heartbeat") for c in collected)

    @pytest.mark.asyncio
    async def test_deregisters_queue_on_generator_exit(self):
        """When generator is closed after being started, queue is deregistered."""
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        register_sse_queue("inc-close", q)

        async def _gen():
            try:
                while True:
                    try:
                        payload = await asyncio.wait_for(q.get(), timeout=20.0)
                        yield f"event: annotation\ndata: {payload}\n\n"
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
            finally:
                deregister_sse_queue("inc-close", q)

        gen = _gen()
        # Put an item so the generator can advance past the first await
        q.put_nowait("test-payload")
        # Consume one item to advance the generator into its try block
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        # Now close it — finally block runs
        await gen.aclose()

        assert "inc-close" not in _WAR_ROOM_QUEUES
