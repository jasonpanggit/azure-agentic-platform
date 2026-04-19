from __future__ import annotations
"""Unit tests for firewall_endpoints.py (Phase 104).

Tests cover:
- GET /api/v1/firewall/rules → 200
- GET /api/v1/firewall/audit → 200
- GET /api/v1/firewall/audit?severity=critical → filtered results
- GET /api/v1/firewall/audit?severity=invalid → 422
"""

import os
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.firewall_endpoints import router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    from unittest.mock import MagicMock
    app = FastAPI()
    app.include_router(router)
    app.state.credential = MagicMock(name="DefaultAzureCredential")
    with patch("services.api_gateway.firewall_endpoints.verify_token", return_value={"sub": "test"}):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Rules endpoint
# ---------------------------------------------------------------------------


class TestFirewallRulesEndpoint:
    def test_get_rules_200(self, client: TestClient):
        mock_result = {
            "firewalls": [{"firewall_name": "fw-prod"}],
            "rules": [{"rule_name": "allow-https"}],
            "count": 1,
        }
        with patch(
            "services.api_gateway.firewall_endpoints.get_cached",
            return_value=mock_result,
        ):
            res = client.get("/api/v1/firewall/rules")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        assert len(data["rules"]) == 1

    def test_get_rules_empty_subscriptions(self, client: TestClient):
        mock_result = {"firewalls": [], "rules": [], "count": 0}
        with patch(
            "services.api_gateway.firewall_endpoints.get_cached",
            return_value=mock_result,
        ):
            res = client.get("/api/v1/firewall/rules")
        assert res.status_code == 200
        assert res.json()["count"] == 0


# ---------------------------------------------------------------------------
# Audit endpoint
# ---------------------------------------------------------------------------


class TestFirewallAuditEndpoint:
    def test_get_audit_200(self, client: TestClient):
        mock_result = {
            "findings": [
                {
                    "firewall_name": "fw-prod",
                    "rule_name": "allow-all",
                    "collection_name": "net-col",
                    "issue_type": "too_wide_source",
                    "severity": "critical",
                    "detail": "Wildcard source",
                    "remediation": "Restrict source",
                }
            ],
            "summary": {"critical": 1, "high": 0, "medium": 0, "total": 1},
            "generated_at": "2026-04-19T00:00:00+00:00",
        }
        with patch(
            "services.api_gateway.firewall_endpoints.get_cached",
            return_value=mock_result,
        ):
            res = client.get("/api/v1/firewall/audit")
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["total"] == 1
        assert len(data["findings"]) == 1
        assert "generated_at" in data

    def test_get_audit_severity_filter_applied(self, client: TestClient):
        mock_result = {
            "findings": [],
            "summary": {"critical": 0, "high": 0, "medium": 0, "total": 0},
            "generated_at": "2026-04-19T00:00:00+00:00",
        }
        with patch(
            "services.api_gateway.firewall_endpoints.get_cached",
            return_value=mock_result,
        ) as mock_cache:
            res = client.get("/api/v1/firewall/audit?severity=critical")
        assert res.status_code == 200
        # Verify the cache key includes severity
        call_kwargs = mock_cache.call_args
        assert call_kwargs is not None
        key_arg = call_kwargs.kwargs.get("key") or call_kwargs.args[0]
        assert "critical" in key_arg

    def test_get_audit_invalid_severity_returns_422(self, client: TestClient):
        res = client.get("/api/v1/firewall/audit?severity=bogus")
        assert res.status_code == 422
        assert "severity" in res.json()["error"]

    def test_get_audit_no_firewalls_returns_empty(self, client: TestClient):
        mock_result = {
            "findings": [],
            "summary": {"critical": 0, "high": 0, "medium": 0, "total": 0},
            "generated_at": "2026-04-19T00:00:00+00:00",
        }
        with patch(
            "services.api_gateway.firewall_endpoints.get_cached",
            return_value=mock_result,
        ):
            res = client.get("/api/v1/firewall/audit")
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["total"] == 0
        assert data["findings"] == []
