from __future__ import annotations
"""Tests for SubscriptionRegistry — ARG-backed subscription discovery."""

import asyncio
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.subscription_registry import SubscriptionRegistry


@pytest.fixture
def mock_credential():
    return MagicMock()


@pytest.fixture
def mock_cosmos():
    cosmos = MagicMock()
    db = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value = db
    db.get_container_client.return_value = container
    return cosmos, container


class TestDiscover:
    def test_returns_subscriptions_from_arg(self, mock_credential):
        """SubscriptionClient returns enabled subscriptions."""
        fake_sub_abc = MagicMock()
        fake_sub_abc.subscription_id = "sub-abc"
        fake_sub_abc.display_name = "Sub ABC"
        fake_sub_abc.state = "Enabled"

        fake_sub_xyz = MagicMock()
        fake_sub_xyz.subscription_id = "sub-xyz"
        fake_sub_xyz.display_name = "Sub XYZ"
        fake_sub_xyz.state = "Enabled"

        mock_client = MagicMock()
        mock_client.subscriptions.list.return_value = [fake_sub_abc, fake_sub_xyz]

        mock_sub_module = MagicMock()
        mock_sub_module.SubscriptionClient.return_value = mock_client

        registry = SubscriptionRegistry(credential=mock_credential, cosmos_client=None)
        with patch.dict("sys.modules", {"azure.mgmt.subscription": mock_sub_module}):
            result = registry.discover()
        assert result == [
            {"id": "sub-abc", "name": "Sub ABC"},
            {"id": "sub-xyz", "name": "Sub XYZ"},
        ]

    def test_returns_empty_list_when_arg_unavailable(self, mock_credential):
        """No error when azure-mgmt-subscription not installed."""
        registry = SubscriptionRegistry(credential=mock_credential, cosmos_client=None)
        with patch.dict("sys.modules", {"azure.mgmt.subscription": None}):
            result = registry.discover()
        assert result == []


class TestSync:
    def test_upserts_subscriptions_to_cosmos(self, mock_credential, mock_cosmos):
        cosmos, container = mock_cosmos
        registry = SubscriptionRegistry(credential=mock_credential, cosmos_client=cosmos)
        subs = [{"id": "sub-abc", "name": "Sub ABC"}]
        registry._cache = subs

        registry.sync_to_cosmos()

        container.upsert_item.assert_called_once()
        call_args = container.upsert_item.call_args[0][0]
        assert call_args["id"] == "sub-abc"
        assert call_args["subscription_id"] == "sub-abc"
        assert call_args["name"] == "Sub ABC"
        assert "last_synced" in call_args

    def test_sync_noop_when_no_cosmos(self, mock_credential):
        """No error when cosmos_client is None."""
        registry = SubscriptionRegistry(credential=mock_credential, cosmos_client=None)
        registry._cache = [{"id": "sub-abc", "name": "Sub ABC"}]
        registry.sync_to_cosmos()  # must not raise


class TestGetAllIds:
    def test_returns_ids_from_cache(self, mock_credential):
        registry = SubscriptionRegistry(credential=mock_credential, cosmos_client=None)
        registry._cache = [{"id": "sub-abc", "name": "Sub ABC"}, {"id": "sub-xyz", "name": "Sub XYZ"}]
        assert registry.get_all_ids() == ["sub-abc", "sub-xyz"]

    def test_returns_empty_before_sync(self, mock_credential):
        registry = SubscriptionRegistry(credential=mock_credential, cosmos_client=None)
        assert registry.get_all_ids() == []


class TestRefreshLoop:
    @pytest.mark.asyncio
    async def test_refresh_loop_calls_sync_and_sleeps(self, mock_credential):
        registry = SubscriptionRegistry(credential=mock_credential, cosmos_client=None)
        call_count = 0

        async def mock_full_sync():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        registry.full_sync = mock_full_sync
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await registry.run_refresh_loop(interval_seconds=1)
        assert call_count >= 2
        mock_sleep.assert_awaited()
