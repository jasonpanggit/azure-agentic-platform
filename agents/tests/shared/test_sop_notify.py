"""Tests for agents/shared/sop_notify.py — SOP notification tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestSopNotify:
    """Verify sop_notify dispatches to Teams and/or email correctly."""

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_sends_teams_when_teams_in_channels(
        self, mock_email, mock_teams
    ):
        mock_teams.return_value = {"ok": True}
        mock_email.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="VM cpu is high",
            severity="warning",
            channels=["teams"],
            incident_id="inc-001",
            resource_name="vm1",
            sop_step="Step 2: Notify operator",
        )
        mock_teams.assert_called_once()
        mock_email.assert_not_called()
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_sends_email_when_email_in_channels(
        self, mock_email, mock_teams
    ):
        mock_email.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="test",
            severity="info",
            channels=["email"],
            incident_id="inc-002",
            resource_name="vm2",
            sop_step="Step 3",
        )
        mock_email.assert_called_once()
        mock_teams.assert_not_called()

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_sends_both_when_both_channels_specified(
        self, mock_email, mock_teams
    ):
        mock_teams.return_value = {"ok": True}
        mock_email.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="critical issue",
            severity="critical",
            channels=["teams", "email"],
            incident_id="inc-003",
            resource_name="vm3",
            sop_step="Step 2",
        )
        mock_teams.assert_called_once()
        mock_email.assert_called_once()

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_result_contains_sop_step(self, mock_email, mock_teams):
        mock_teams.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="test",
            severity="info",
            channels=["teams"],
            incident_id="inc-004",
            resource_name="vm4",
            sop_step="Step 5: escalate",
        )
        assert result["sop_step"] == "Step 5: escalate"

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_teams_failure_does_not_raise(self, mock_email, mock_teams):
        """Notification failures are logged but never raised."""
        mock_teams.side_effect = Exception("Teams unavailable")

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="test",
            severity="warning",
            channels=["teams"],
            incident_id="inc-005",
            resource_name="vm5",
            sop_step="Step 1",
        )
        # Should return error status, not raise
        assert result["status"] in ("partial", "error", "sent")

    @pytest.mark.asyncio
    @patch("agents.shared.sop_notify._send_teams_notification")
    @patch("agents.shared.sop_notify._send_email_notification")
    async def test_result_contains_channel_results(self, mock_email, mock_teams):
        mock_teams.return_value = {"ok": True}
        mock_email.return_value = {"ok": True}

        from agents.shared.sop_notify import sop_notify

        result = await sop_notify(
            message="test",
            severity="info",
            channels=["teams", "email"],
            incident_id="inc-006",
            resource_name="vm6",
            sop_step="Step 1",
        )
        assert "channels" in result
        assert "teams" in result["channels"]
        assert "email" in result["channels"]
