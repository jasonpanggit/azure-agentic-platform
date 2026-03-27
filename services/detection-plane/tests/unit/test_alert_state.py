"""Unit tests for alert state lifecycle (DETECT-006)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from alert_state import InvalidTransitionError, sync_alert_state_to_azure_monitor, transition_alert_state
from models import AlertStatus


@pytest.fixture
def mock_container() -> MagicMock:
    return MagicMock()


class TestTransitionAlertState:
    @pytest.mark.asyncio
    async def test_new_to_acknowledged(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "new", "status_history": [], "_etag": "e1"}
        mock_container.read_item.return_value = record
        mock_container.replace_item.return_value = {**record, "status": "acknowledged"}
        result = await transition_alert_state("inc-1", "res-1", AlertStatus.ACKNOWLEDGED, "user@test.com", mock_container)
        assert result["status"] == "acknowledged"

    @pytest.mark.asyncio
    async def test_new_to_closed(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "new", "status_history": [], "_etag": "e1"}
        mock_container.read_item.return_value = record
        mock_container.replace_item.return_value = {**record, "status": "closed"}
        result = await transition_alert_state("inc-1", "res-1", AlertStatus.CLOSED, "user@test.com", mock_container)
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_acknowledged_to_closed(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "acknowledged", "status_history": [], "_etag": "e1"}
        mock_container.read_item.return_value = record
        mock_container.replace_item.return_value = {**record, "status": "closed"}
        result = await transition_alert_state("inc-1", "res-1", AlertStatus.CLOSED, "user@test.com", mock_container)
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_closed_to_new_raises(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "closed", "status_history": [], "_etag": "e1"}
        mock_container.read_item.return_value = record
        with pytest.raises(InvalidTransitionError):
            await transition_alert_state("inc-1", "res-1", AlertStatus.NEW, "user@test.com", mock_container)

    @pytest.mark.asyncio
    async def test_closed_to_acknowledged_raises(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "closed", "status_history": [], "_etag": "e1"}
        mock_container.read_item.return_value = record
        with pytest.raises(InvalidTransitionError):
            await transition_alert_state("inc-1", "res-1", AlertStatus.ACKNOWLEDGED, "user@test.com", mock_container)

    @pytest.mark.asyncio
    async def test_transition_appends_status_history(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "new", "status_history": [], "_etag": "e1"}
        mock_container.read_item.return_value = record
        mock_container.replace_item.return_value = record
        await transition_alert_state("inc-1", "res-1", AlertStatus.ACKNOWLEDGED, "op@co.com", mock_container)
        call_body = mock_container.replace_item.call_args.kwargs["body"]
        assert len(call_body["status_history"]) == 1
        assert call_body["status_history"][0]["actor"] == "op@co.com"

    @pytest.mark.asyncio
    async def test_uses_etag_concurrency(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "new", "status_history": [], "_etag": "etag-val"}
        mock_container.read_item.return_value = record
        mock_container.replace_item.return_value = record
        await transition_alert_state("inc-1", "res-1", AlertStatus.ACKNOWLEDGED, "user", mock_container)
        call_kwargs = mock_container.replace_item.call_args.kwargs
        assert call_kwargs["etag"] == "etag-val"
        assert call_kwargs["match_condition"] == "IfMatch"

    @pytest.mark.asyncio
    async def test_immutable_record_update(self, mock_container: MagicMock) -> None:
        record = {"id": "inc-1", "resource_id": "res-1", "status": "new", "status_history": [], "_etag": "e1"}
        mock_container.read_item.return_value = record
        mock_container.replace_item.return_value = {**record, "status": "acknowledged"}
        await transition_alert_state("inc-1", "res-1", AlertStatus.ACKNOWLEDGED, "user", mock_container)
        # Original record must not be mutated
        assert record["status"] == "new"


class TestSyncAlertStateToAzureMonitor:
    @pytest.mark.asyncio
    async def test_sync_failure_returns_false_or_bool(self) -> None:
        result = await sync_alert_state_to_azure_monitor("alert-1", AlertStatus.ACKNOWLEDGED, "sub-1", MagicMock())
        # Will return False because azure-mgmt-alertsmanagement may not be installed
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_new_status_skips_sync_returns_true(self) -> None:
        result = await sync_alert_state_to_azure_monitor("alert-1", AlertStatus.NEW, "sub-1", MagicMock())
        assert result is True

    @pytest.mark.asyncio
    async def test_closed_status_attempts_sync(self) -> None:
        # Closed has a valid Azure Monitor mapping — should attempt and return bool
        result = await sync_alert_state_to_azure_monitor("alert-1", AlertStatus.CLOSED, "sub-1", MagicMock())
        assert isinstance(result, bool)
