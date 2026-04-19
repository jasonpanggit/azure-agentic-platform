"""Tests for shared/approval_manager.py — container=None self-init path."""
from unittest.mock import MagicMock, patch

import pytest


class TestCreateApprovalRecordContainerNone:

    @patch("agents.shared.approval_manager.DefaultAzureCredential")
    @patch("agents.shared.approval_manager.CosmosClient")
    def test_container_none_initialises_cosmos_from_env(
        self, mock_cosmos_cls, mock_cred_cls
    ):
        """When container=None, must initialise CosmosClient from COSMOS_ENDPOINT."""
        import os
        mock_container = MagicMock()
        mock_container.create_item.return_value = {"id": "appr_test"}
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container
        mock_cosmos_cls.return_value.get_database_client.return_value = mock_db

        from agents.shared.approval_manager import create_approval_record

        with patch.dict(os.environ, {"COSMOS_ENDPOINT": "https://test.documents.azure.com:443/", "COSMOS_DATABASE_NAME": "aap"}):
            result = create_approval_record(
                container=None,
                thread_id="thread-1",
                incident_id="inc-1",
                agent_name="sre-agent",
                proposal={"action": "restart"},
                resource_snapshot={"vm": "vm-1"},
                risk_level="low",
            )

        mock_cosmos_cls.assert_called_once()
        mock_db.get_container_client.assert_called_once_with("approvals")
        mock_container.create_item.assert_called_once()
        assert result == {"id": "appr_test"}

    @patch("agents.shared.approval_manager.DefaultAzureCredential")
    @patch("agents.shared.approval_manager.CosmosClient")
    def test_container_none_missing_endpoint_raises(
        self, mock_cosmos_cls, mock_cred_cls
    ):
        """Missing COSMOS_ENDPOINT must raise ValueError, not AttributeError."""
        import os
        from agents.shared.approval_manager import create_approval_record

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("COSMOS_ENDPOINT", None)
            with pytest.raises(ValueError, match="COSMOS_ENDPOINT"):
                create_approval_record(
                    container=None,
                    thread_id="t",
                    incident_id="i",
                    agent_name="sre-agent",
                    proposal={},
                    resource_snapshot={},
                    risk_level="low",
                )
