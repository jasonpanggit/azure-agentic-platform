"""Unit tests for the Fabric User Data Function (DETECT-003).

Tests the payload mapping and auth token acquisition logic in
fabric/user-data-function/main.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Add UDF to Python path for import
UDF_PATH = str(Path(__file__).parent.parent.parent.parent.parent / "fabric" / "user-data-function")
if UDF_PATH not in sys.path:
    sys.path.insert(0, UDF_PATH)

import main as _udf_module  # noqa: E402 — import after sys.path manipulation


class TestMapDetectionResultToPayload:
    """Test the UDF's payload mapping function."""

    def test_valid_mapping(self, sample_detection_result: dict[str, Any]) -> None:
        result = _udf_module.map_detection_result_to_payload(sample_detection_result)
        assert result["incident_id"].startswith("det-")
        assert result["severity"] == "Sev1"
        assert result["domain"] == "compute"
        assert len(result["affected_resources"]) == 1
        assert result["detection_rule"] == "HighCPU"

    def test_det_prefix_on_incident_id(self, sample_detection_result: dict[str, Any]) -> None:
        result = _udf_module.map_detection_result_to_payload(sample_detection_result)
        assert result["incident_id"] == f"det-{sample_detection_result['alert_id']}"

    def test_title_concatenation(self, sample_detection_result: dict[str, Any]) -> None:
        result = _udf_module.map_detection_result_to_payload(sample_detection_result)
        assert result["title"] == "HighCPU on vm-1"

    def test_subscription_id_extraction(self) -> None:
        result = _udf_module.map_detection_result_to_payload({
            "alert_id": "a-1",
            "resource_id": "/subscriptions/my-sub/resourceGroups/rg/providers/P/T/name",
            "resource_type": "P/T",
            "subscription_id": "",
            "severity": "Sev2",
            "domain": "sre",
            "alert_rule": "test",
        })
        assert result["affected_resources"][0]["subscription_id"] == "my-sub"

    def test_fallback_subscription_id_when_no_subscriptions_in_path(self) -> None:
        result = _udf_module.map_detection_result_to_payload({
            "alert_id": "a-2",
            "resource_id": "/providers/P/T/name",
            "resource_type": "P/T",
            "subscription_id": "fallback-sub",
            "severity": "Sev3",
            "domain": "sre",
            "alert_rule": "test",
        })
        assert result["affected_resources"][0]["subscription_id"] == "fallback-sub"

    def test_title_falls_back_to_alert_id_when_no_rule(self) -> None:
        result = _udf_module.map_detection_result_to_payload({
            "alert_id": "alert-xyz",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/T/R/name",
            "resource_type": "T/R",
            "subscription_id": "sub-1",
            "severity": "Sev3",
            "domain": "sre",
            "alert_rule": "",
        })
        assert result["title"] == "alert-xyz"


class TestGetAccessToken:
    """Test token acquisition (mocked MSAL)."""

    @patch.dict(os.environ, {
        "FABRIC_SP_CLIENT_ID": "test-client-id",
        "FABRIC_SP_CLIENT_SECRET": "test-secret",
        "FABRIC_SP_TENANT_ID": "test-tenant",
        "GATEWAY_APP_SCOPE": "api://test/.default",
    })
    @patch("main.msal.ConfidentialClientApplication")
    def test_acquires_token_successfully(self, mock_msal_class: MagicMock) -> None:
        mock_app = MagicMock()
        mock_msal_class.return_value = mock_app
        mock_app.acquire_token_for_client.return_value = {"access_token": "test-token"}

        token = _udf_module.get_access_token()
        assert token == "test-token"
        mock_app.acquire_token_for_client.assert_called_once_with(scopes=["api://test/.default"])

    @patch.dict(os.environ, {
        "FABRIC_SP_CLIENT_ID": "id",
        "FABRIC_SP_CLIENT_SECRET": "secret",
        "FABRIC_SP_TENANT_ID": "tenant",
        "GATEWAY_APP_SCOPE": "scope",
    })
    @patch("main.msal.ConfidentialClientApplication")
    def test_raises_on_token_failure(self, mock_msal_class: MagicMock) -> None:
        mock_app = MagicMock()
        mock_msal_class.return_value = mock_app
        mock_app.acquire_token_for_client.return_value = {"error": "invalid_client"}

        with pytest.raises(RuntimeError, match="Token acquisition failed"):
            _udf_module.get_access_token()


class TestHandleActivatorTrigger:
    """Test the full trigger handler (mocked HTTP and auth)."""

    @patch.dict(os.environ, {
        "API_GATEWAY_URL": "https://gateway.example.com",
        "FABRIC_SP_CLIENT_ID": "id",
        "FABRIC_SP_CLIENT_SECRET": "secret",
        "FABRIC_SP_TENANT_ID": "tenant",
        "GATEWAY_APP_SCOPE": "scope",
    })
    @patch("main.requests.post")
    @patch("main.get_access_token", return_value="mock-token")
    def test_posts_to_gateway(
        self,
        mock_get_token: MagicMock,
        mock_post: MagicMock,
        sample_detection_result: dict[str, Any],
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"thread_id": "thread-1", "status": "dispatched"}
        mock_post.return_value = mock_response

        result = _udf_module.handle_activator_trigger(sample_detection_result)

        assert result["status"] == "dispatched"
        assert result["thread_id"] == "thread-1"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer mock-token"

    @patch.dict(os.environ, {
        "API_GATEWAY_URL": "https://gateway.example.com",
        "FABRIC_SP_CLIENT_ID": "id",
        "FABRIC_SP_CLIENT_SECRET": "secret",
        "FABRIC_SP_TENANT_ID": "tenant",
        "GATEWAY_APP_SCOPE": "scope",
    })
    @patch("main.requests.post")
    @patch("main.get_access_token", return_value="mock-token")
    def test_returns_error_on_non_202(
        self,
        mock_get_token: MagicMock,
        mock_post: MagicMock,
        sample_detection_result: dict[str, Any],
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        result = _udf_module.handle_activator_trigger(sample_detection_result)

        assert result["status"] == "error"
        assert result["status_code"] == 500
