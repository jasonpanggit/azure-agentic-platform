"""Tests for FastAPI dependency providers (CONCERNS 4.4)."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import importlib


class TestDependencies:
    """DefaultAzureCredential and CosmosClient initialized once per process."""

    def test_get_credential_reads_from_app_state(self):
        from services.api_gateway.dependencies import get_credential
        from fastapi import Request

        mock_cred = MagicMock(name="DefaultAzureCredential")
        mock_request = MagicMock(spec=Request)
        mock_request.app.state.credential = mock_cred

        result = get_credential(mock_request)
        assert result is mock_cred

    def test_get_cosmos_client_reads_from_app_state(self):
        from services.api_gateway.dependencies import get_cosmos_client
        from fastapi import Request

        mock_client = MagicMock(name="CosmosClient")
        mock_request = MagicMock(spec=Request)
        mock_request.app.state.cosmos_client = mock_client

        result = get_cosmos_client(mock_request)
        assert result is mock_client

    def test_get_cosmos_client_raises_503_when_none(self):
        from services.api_gateway.dependencies import get_cosmos_client
        from fastapi import Request, HTTPException

        mock_request = MagicMock(spec=Request)
        mock_request.app.state.cosmos_client = None

        with pytest.raises(HTTPException) as exc_info:
            get_cosmos_client(mock_request)
        assert exc_info.value.status_code == 503

    def test_credential_initialized_once_in_lifespan(self):
        """DefaultAzureCredential.__init__ called exactly once during app startup.

        Patches azure.identity.DefaultAzureCredential and azure.cosmos.CosmosClient
        at their canonical source locations so the reloaded module picks up the mocks.
        Sets COSMOS_ENDPOINT so the CosmosClient branch is exercised.
        """
        import services.api_gateway.main as main_module

        with patch.dict("os.environ", {"COSMOS_ENDPOINT": "https://fake.documents.azure.com:443/"}):
            with patch("azure.identity.DefaultAzureCredential") as mock_cred_cls:
                with patch("azure.cosmos.CosmosClient") as mock_cosmos_cls:
                    with patch("services.api_gateway.main._run_startup_migrations", new_callable=AsyncMock):
                        mock_cred_cls.return_value = MagicMock()
                        mock_cosmos_cls.return_value = MagicMock()

                        importlib.reload(main_module)
                        fresh_app = main_module.app

                        with TestClient(fresh_app):
                            pass  # TestClient lifecycle runs lifespan

                        assert mock_cred_cls.call_count == 1, (
                            f"DefaultAzureCredential() called {mock_cred_cls.call_count} times, expected 1"
                        )
                        assert mock_cosmos_cls.call_count == 1, (
                            f"CosmosClient() called {mock_cosmos_cls.call_count} times, expected 1"
                        )
