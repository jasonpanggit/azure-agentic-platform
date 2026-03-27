"""Tests for teams_notifier.py refactored to use bot internal notify endpoint (D-04, D-11)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestTeamsNotifier:
    """Tests for the refactored teams_notifier.py (Phase 6 bot integration)."""

    @pytest.mark.asyncio
    async def test_notify_teams_sends_to_bot_internal_url(self):
        """notify_teams() POSTs to TEAMS_BOT_INTERNAL_URL/teams/internal/notify."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "sent", "message_id": "msg-001"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("services.api_gateway.teams_notifier.httpx.AsyncClient", return_value=mock_client), \
             patch("services.api_gateway.teams_notifier.TEAMS_BOT_INTERNAL_URL", "http://bot:3978"), \
             patch("services.api_gateway.teams_notifier.TEAMS_CHANNEL_ID", "channel-001"):
            from services.api_gateway.teams_notifier import notify_teams

            result = await notify_teams(
                card_type="alert",
                payload={"incident_id": "inc-001", "alert_title": "CPU High"},
            )

        assert result is not None
        assert result["status"] == "sent"
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/teams/internal/notify" in call_args.args[0]
        request_body = call_args.kwargs["json"]
        assert request_body["card_type"] == "alert"
        assert request_body["channel_id"] == "channel-001"

    @pytest.mark.asyncio
    async def test_notify_teams_returns_none_when_url_not_configured(self):
        """notify_teams() returns None when TEAMS_BOT_INTERNAL_URL is empty."""
        with patch("services.api_gateway.teams_notifier.TEAMS_BOT_INTERNAL_URL", ""), \
             patch("services.api_gateway.teams_notifier.TEAMS_CHANNEL_ID", "channel-001"):
            from services.api_gateway.teams_notifier import notify_teams

            result = await notify_teams(
                card_type="alert",
                payload={"incident_id": "inc-001"},
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_notify_teams_returns_none_when_channel_not_configured(self):
        """notify_teams() returns None when TEAMS_CHANNEL_ID is empty."""
        with patch("services.api_gateway.teams_notifier.TEAMS_BOT_INTERNAL_URL", "http://bot:3978"), \
             patch("services.api_gateway.teams_notifier.TEAMS_CHANNEL_ID", ""):
            from services.api_gateway.teams_notifier import notify_teams

            result = await notify_teams(
                card_type="alert",
                payload={"incident_id": "inc-001"},
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_post_approval_card_wrapper(self):
        """post_approval_card() calls notify_teams() with card_type='approval'."""
        with patch("services.api_gateway.teams_notifier.notify_teams", new=AsyncMock(return_value={"status": "sent"})) as mock_notify:
            from services.api_gateway.teams_notifier import post_approval_card

            result = await post_approval_card(
                approval_id="appr-001",
                thread_id="thread-001",
                proposal={"description": "Restart VM"},
                risk_level="high",
                expires_at="2026-03-27T15:00:00Z",
            )

        assert result is not None
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["card_type"] == "approval"
        assert call_kwargs["payload"]["approval_id"] == "appr-001"

    @pytest.mark.asyncio
    async def test_post_alert_card_wrapper(self):
        """post_alert_card() calls notify_teams() with card_type='alert'."""
        with patch("services.api_gateway.teams_notifier.notify_teams", new=AsyncMock(return_value={"status": "sent"})) as mock_notify:
            from services.api_gateway.teams_notifier import post_alert_card

            result = await post_alert_card(
                incident_id="inc-001",
                alert_title="CPU High",
                resource_name="vm-prod-01",
                severity="Sev1",
                subscription_name="prod-sub",
                domain="compute",
                timestamp="2026-03-27T14:00:00Z",
            )

        assert result is not None
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["card_type"] == "alert"
        assert call_kwargs["payload"]["incident_id"] == "inc-001"

    @pytest.mark.asyncio
    async def test_post_outcome_card_wrapper(self):
        """post_outcome_card() calls notify_teams() with card_type='outcome'."""
        with patch("services.api_gateway.teams_notifier.notify_teams", new=AsyncMock(return_value={"status": "sent"})) as mock_notify:
            from services.api_gateway.teams_notifier import post_outcome_card

            result = await post_outcome_card(
                incident_id="inc-001",
                approval_id="appr-001",
                action_description="Restart VM",
                outcome_status="success",
                duration_seconds=12,
                resulting_resource_state="Running",
                approver_upn="operator@contoso.com",
                executed_at="2026-03-27T15:05:00Z",
            )

        assert result is not None
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        assert call_kwargs["card_type"] == "outcome"
        assert call_kwargs["payload"]["approval_id"] == "appr-001"

    @pytest.mark.asyncio
    async def test_notify_teams_handles_http_error_gracefully(self):
        """notify_teams() returns None on HTTP error (no crash)."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("services.api_gateway.teams_notifier.httpx.AsyncClient", return_value=mock_client), \
             patch("services.api_gateway.teams_notifier.TEAMS_BOT_INTERNAL_URL", "http://bot:3978"), \
             patch("services.api_gateway.teams_notifier.TEAMS_CHANNEL_ID", "channel-001"):
            from services.api_gateway.teams_notifier import notify_teams

            result = await notify_teams(
                card_type="alert",
                payload={"incident_id": "inc-001"},
            )

        assert result is None
