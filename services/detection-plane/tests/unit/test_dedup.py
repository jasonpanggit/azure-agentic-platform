"""Unit tests for two-layer deduplication (DETECT-005)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from dedup import (
    DedupResult,
    collapse_duplicate,
    correlate_alert,
    create_incident_record,
    dedup_layer1,
    dedup_layer2,
)
from models import AlertStatus


@pytest.fixture
def mock_container() -> MagicMock:
    """Create a mock Cosmos DB ContainerProxy."""
    return MagicMock()


class TestDedupLayer1:
    """Layer 1: Time-window collapse tests."""

    @pytest.mark.asyncio
    async def test_no_existing_incident(self, mock_container: MagicMock) -> None:
        mock_container.query_items.return_value = iter([])
        result = await dedup_layer1("res-1", "rule-1", mock_container)
        assert result.is_duplicate is False
        assert result.existing_record is None

    @pytest.mark.asyncio
    async def test_existing_incident_within_window(self, mock_container: MagicMock) -> None:
        existing = {"id": "inc-1", "resource_id": "res-1", "detection_rule": "rule-1", "status": "new"}
        mock_container.query_items.return_value = iter([existing])
        result = await dedup_layer1("res-1", "rule-1", mock_container)
        assert result.is_duplicate is True
        assert result.existing_record == existing
        assert result.layer == "layer1"

    @pytest.mark.asyncio
    async def test_closed_incident_not_matched(self, mock_container: MagicMock) -> None:
        # Query filters out closed incidents — empty result
        mock_container.query_items.return_value = iter([])
        result = await dedup_layer1("res-1", "rule-1", mock_container)
        assert result.is_duplicate is False

    @pytest.mark.asyncio
    async def test_layer1_uses_partition_key(self, mock_container: MagicMock) -> None:
        mock_container.query_items.return_value = iter([])
        await dedup_layer1("res-1", "rule-1", mock_container)
        call_kwargs = mock_container.query_items.call_args.kwargs
        assert call_kwargs.get("partition_key") == "res-1"

    @pytest.mark.asyncio
    async def test_layer1_result_has_no_layer_on_miss(self, mock_container: MagicMock) -> None:
        mock_container.query_items.return_value = iter([])
        result = await dedup_layer1("res-1", "rule-1", mock_container)
        assert result.layer is None


class TestDedupLayer2:
    """Layer 2: Open-incident correlation tests."""

    @pytest.mark.asyncio
    async def test_no_open_incident(self, mock_container: MagicMock) -> None:
        mock_container.query_items.return_value = iter([])
        result = await dedup_layer2("res-1", mock_container)
        assert result.is_duplicate is False

    @pytest.mark.asyncio
    async def test_open_incident_exists(self, mock_container: MagicMock) -> None:
        existing = {"id": "inc-1", "resource_id": "res-1", "status": "new"}
        mock_container.query_items.return_value = iter([existing])
        result = await dedup_layer2("res-1", mock_container)
        assert result.is_duplicate is True
        assert result.layer == "layer2"

    @pytest.mark.asyncio
    async def test_acknowledged_incident_is_open(self, mock_container: MagicMock) -> None:
        existing = {"id": "inc-1", "resource_id": "res-1", "status": "acknowledged"}
        mock_container.query_items.return_value = iter([existing])
        result = await dedup_layer2("res-1", mock_container)
        assert result.is_duplicate is True
        assert result.existing_record == existing


class TestCollapseDuplicate:
    """Layer 1: Collapse duplicate with ETag."""

    @pytest.mark.asyncio
    async def test_increments_duplicate_count(self, mock_container: MagicMock) -> None:
        existing = {"id": "inc-1", "resource_id": "res-1", "duplicate_count": 2, "_etag": "etag-1"}
        mock_container.replace_item.return_value = {**existing, "duplicate_count": 3}
        result = await collapse_duplicate(existing, mock_container)
        assert result["duplicate_count"] == 3
        mock_container.replace_item.assert_called_once()
        call_kwargs = mock_container.replace_item.call_args.kwargs
        assert call_kwargs.get("match_condition") == "IfMatch"

    @pytest.mark.asyncio
    async def test_uses_etag(self, mock_container: MagicMock) -> None:
        existing = {"id": "inc-1", "resource_id": "res-1", "duplicate_count": 0, "_etag": "my-etag"}
        mock_container.replace_item.return_value = {**existing, "duplicate_count": 1}
        await collapse_duplicate(existing, mock_container)
        call_kwargs = mock_container.replace_item.call_args.kwargs
        assert call_kwargs.get("etag") == "my-etag"

    @pytest.mark.asyncio
    async def test_immutable_pattern_no_mutation(self, mock_container: MagicMock) -> None:
        existing = {"id": "inc-1", "resource_id": "res-1", "duplicate_count": 0, "_etag": "etag-1"}
        mock_container.replace_item.return_value = {**existing, "duplicate_count": 1}
        await collapse_duplicate(existing, mock_container)
        # Original record should be unchanged
        assert existing["duplicate_count"] == 0


class TestCorrelateAlert:
    """Layer 2: Correlate alert to existing incident."""

    @pytest.mark.asyncio
    async def test_appends_correlated_alert(self, mock_container: MagicMock) -> None:
        existing = {
            "id": "inc-1", "resource_id": "res-1",
            "correlated_alerts": [], "_etag": "etag-1",
        }
        mock_container.replace_item.return_value = {
            **existing, "correlated_alerts": [{"alert_id": "alert-2"}],
        }
        result = await correlate_alert(
            existing, "alert-2", "Sev1", "rule-2", mock_container,
        )
        assert len(result["correlated_alerts"]) == 1
        mock_container.replace_item.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_etag_match_condition(self, mock_container: MagicMock) -> None:
        existing = {
            "id": "inc-1", "resource_id": "res-1",
            "correlated_alerts": [], "_etag": "etag-42",
        }
        mock_container.replace_item.return_value = {**existing}
        await correlate_alert(existing, "a-2", "Sev2", "rule-x", mock_container)
        call_kwargs = mock_container.replace_item.call_args.kwargs
        assert call_kwargs.get("match_condition") == "IfMatch"
        assert call_kwargs.get("etag") == "etag-42"


class TestCreateIncidentRecord:
    """Create new incident record."""

    @pytest.mark.asyncio
    async def test_creates_record_with_correct_fields(self, mock_container: MagicMock) -> None:
        mock_container.create_item.return_value = {"id": "inc-1"}
        result = await create_incident_record(
            incident_id="inc-1",
            resource_id="res-1",
            severity="Sev1",
            domain="compute",
            detection_rule="rule-1",
            affected_resources=[{"resource_id": "res-1"}],
            container=mock_container,
        )
        mock_container.create_item.assert_called_once()
        call_body = mock_container.create_item.call_args.kwargs["body"]
        assert call_body["id"] == "inc-1"
        assert call_body["resource_id"] == "res-1"
        assert call_body["status"] == "new"
        assert len(call_body["status_history"]) == 1
        assert call_body["status_history"][0]["status"] == "new"

    @pytest.mark.asyncio
    async def test_initial_status_is_new(self, mock_container: MagicMock) -> None:
        mock_container.create_item.return_value = {"id": "inc-2"}
        await create_incident_record(
            incident_id="inc-2",
            resource_id="res-2",
            severity="Sev0",
            domain="network",
            detection_rule="rule-net",
            affected_resources=[],
            container=mock_container,
        )
        call_body = mock_container.create_item.call_args.kwargs["body"]
        assert call_body["status"] == AlertStatus.NEW.value

    @pytest.mark.asyncio
    async def test_duplicate_count_starts_at_zero(self, mock_container: MagicMock) -> None:
        mock_container.create_item.return_value = {"id": "inc-3"}
        await create_incident_record(
            incident_id="inc-3",
            resource_id="res-3",
            severity="Sev2",
            domain="storage",
            detection_rule="rule-storage",
            affected_resources=[],
            container=mock_container,
        )
        call_body = mock_container.create_item.call_args.kwargs["body"]
        assert call_body["duplicate_count"] == 0
