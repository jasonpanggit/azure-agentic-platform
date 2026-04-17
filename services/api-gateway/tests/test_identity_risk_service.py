from __future__ import annotations
"""Tests for identity_risk_service — mocks Graph API and Cosmos DB."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.identity_risk_service import (
    CredentialRisk,
    _build_risks_from_sp,
    _days_until,
    _severity,
    _stable_id,
    get_identity_summary,
    get_risks,
    persist_risks,
    scan_credential_risks,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _iso(days_offset: int) -> str:
    """Return an ISO timestamp offset from now by days_offset days."""
    dt = datetime.now(tz=timezone.utc) + timedelta(days=days_offset)
    return dt.isoformat()


def _make_credential(token: str = "tok-abc") -> MagicMock:
    cred = MagicMock()
    token_obj = MagicMock()
    token_obj.token = token
    cred.get_token.return_value = token_obj
    return cred


def _make_cosmos(items: List[Dict[str, Any]]) -> MagicMock:
    container = MagicMock()
    container.read_all_items.return_value = items
    container.query_items.return_value = items
    db = MagicMock()
    db.get_container_client.return_value = container
    cosmos = MagicMock()
    cosmos.get_database_client.return_value = db
    return cosmos


def _make_risk(**kwargs) -> CredentialRisk:
    defaults: Dict[str, Any] = dict(
        risk_id="rid-1",
        service_principal_id="sp-1",
        service_principal_name="My App",
        credential_type="password",
        credential_name="main-secret",
        expiry_date=_iso(-5),
        days_until_expiry=-5,
        severity="critical",
        detected_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    defaults.update(kwargs)
    return CredentialRisk(**defaults)


# ── Helper unit tests ─────────────────────────────────────────────────────────

class TestDaysUntil:
    def test_future_date_positive(self):
        expiry = _iso(10)
        assert _days_until(expiry) > 0

    def test_past_date_negative(self):
        expiry = _iso(-5)
        assert _days_until(expiry) < 0

    def test_today_is_zero(self):
        today = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        assert _days_until(today) == 0

    def test_trailing_z_stripped(self):
        expiry = _iso(15).replace("+00:00", "Z")
        assert _days_until(expiry) > 0

    def test_invalid_returns_zero(self):
        assert _days_until("not-a-date") == 0


class TestSeverity:
    def test_negative_days_is_critical(self):
        assert _severity(-1) == "critical"

    def test_zero_days_is_high(self):
        assert _severity(0) == "high"

    def test_29_days_is_high(self):
        assert _severity(29) == "high"

    def test_30_days_is_medium(self):
        assert _severity(30) == "medium"

    def test_90_days_is_medium(self):
        assert _severity(90) == "medium"


class TestStableId:
    def test_deterministic(self):
        a = _stable_id("sp-1", "key-1")
        b = _stable_id("sp-1", "key-1")
        assert a == b

    def test_different_inputs_differ(self):
        assert _stable_id("sp-1", "key-1") != _stable_id("sp-1", "key-2")


# ── _build_risks_from_sp ──────────────────────────────────────────────────────

class TestBuildRisksFromSp:
    def test_password_credential_expiring_soon_included(self):
        sp = {
            "id": "sp-abc",
            "displayName": "My App",
            "passwordCredentials": [
                {"keyId": "k1", "endDateTime": _iso(10), "displayName": "secret1"},
            ],
            "keyCredentials": [],
        }
        risks = _build_risks_from_sp(sp, datetime.now(tz=timezone.utc).isoformat())
        assert len(risks) == 1
        assert risks[0].credential_type == "password"
        assert risks[0].service_principal_name == "My App"

    def test_cert_credential_expiring_soon_included(self):
        sp = {
            "id": "sp-abc",
            "displayName": "My App",
            "passwordCredentials": [],
            "keyCredentials": [
                {"keyId": "k2", "endDateTime": _iso(20)},
            ],
        }
        risks = _build_risks_from_sp(sp, datetime.now(tz=timezone.utc).isoformat())
        assert len(risks) == 1
        assert risks[0].credential_type == "certificate"

    def test_credential_beyond_90_days_excluded(self):
        sp = {
            "id": "sp-abc",
            "displayName": "My App",
            "passwordCredentials": [
                {"keyId": "k3", "endDateTime": _iso(100)},
            ],
            "keyCredentials": [],
        }
        risks = _build_risks_from_sp(sp, datetime.now(tz=timezone.utc).isoformat())
        assert risks == []

    def test_missing_end_date_skipped(self):
        sp = {
            "id": "sp-abc",
            "displayName": "My App",
            "passwordCredentials": [{"keyId": "k4"}],
            "keyCredentials": [],
        }
        risks = _build_risks_from_sp(sp, datetime.now(tz=timezone.utc).isoformat())
        assert risks == []

    def test_expired_credential_is_critical(self):
        sp = {
            "id": "sp-abc",
            "displayName": "My App",
            "passwordCredentials": [
                {"keyId": "k5", "endDateTime": _iso(-3)},
            ],
            "keyCredentials": [],
        }
        risks = _build_risks_from_sp(sp, datetime.now(tz=timezone.utc).isoformat())
        assert risks[0].severity == "critical"

    def test_empty_credentials_returns_empty(self):
        sp = {"id": "sp-abc", "displayName": "Empty", "passwordCredentials": [], "keyCredentials": []}
        assert _build_risks_from_sp(sp, "2026-01-01T00:00:00+00:00") == []

    def test_sp_name_falls_back_to_id(self):
        sp = {
            "id": "sp-no-name",
            "passwordCredentials": [{"keyId": "k6", "endDateTime": _iso(5)}],
            "keyCredentials": [],
        }
        risks = _build_risks_from_sp(sp, datetime.now(tz=timezone.utc).isoformat())
        assert risks[0].service_principal_name == "sp-no-name"


# ── scan_credential_risks ─────────────────────────────────────────────────────

class TestScanCredentialRisks:
    def _mock_response(self, sps: List[Dict], next_link: str = None) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        data: Dict[str, Any] = {"value": sps}
        if next_link:
            data["@odata.nextLink"] = next_link
        resp.json.return_value = data
        return resp

    def test_happy_path_returns_risks(self):
        sp = {
            "id": "sp-1",
            "displayName": "App1",
            "passwordCredentials": [{"keyId": "k1", "endDateTime": _iso(5)}],
            "keyCredentials": [],
        }
        cred = _make_credential()
        with patch("services.api_gateway.identity_risk_service.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_response([sp])
            risks = scan_credential_risks(cred)
        assert len(risks) == 1
        assert risks[0].service_principal_id == "sp-1"

    def test_empty_sp_list_returns_empty(self):
        cred = _make_credential()
        with patch("services.api_gateway.identity_risk_service.requests") as mock_requests:
            mock_requests.get.return_value = self._mock_response([])
            risks = scan_credential_risks(cred)
        assert risks == []

    def test_401_returns_empty_gracefully(self):
        cred = _make_credential()
        resp = MagicMock()
        resp.status_code = 401
        resp.ok = False
        with patch("services.api_gateway.identity_risk_service.requests") as mock_requests:
            mock_requests.get.return_value = resp
            risks = scan_credential_risks(cred)
        assert risks == []

    def test_403_returns_empty_gracefully(self):
        cred = _make_credential()
        resp = MagicMock()
        resp.status_code = 403
        resp.ok = False
        with patch("services.api_gateway.identity_risk_service.requests") as mock_requests:
            mock_requests.get.return_value = resp
            risks = scan_credential_risks(cred)
        assert risks == []

    def test_network_exception_returns_empty(self):
        cred = _make_credential()
        with patch("services.api_gateway.identity_risk_service.requests") as mock_requests:
            mock_requests.get.side_effect = ConnectionError("timeout")
            risks = scan_credential_risks(cred)
        assert risks == []

    def test_token_acquisition_failure_returns_empty(self):
        cred = MagicMock()
        cred.get_token.side_effect = Exception("auth error")
        risks = scan_credential_risks(cred)
        assert risks == []

    def test_requests_none_returns_empty(self):
        cred = _make_credential()
        with patch("services.api_gateway.identity_risk_service.requests", None):
            risks = scan_credential_risks(cred)
        assert risks == []

    def test_500_error_breaks_loop_returns_partial(self):
        """Non-auth HTTP errors break the loop but return any risks collected before."""
        sp = {
            "id": "sp-1",
            "displayName": "App1",
            "passwordCredentials": [{"keyId": "k1", "endDateTime": _iso(5)}],
            "keyCredentials": [],
        }
        good_resp = self._mock_response([sp], next_link="https://graph.microsoft.com/next")
        bad_resp = MagicMock()
        bad_resp.status_code = 500
        bad_resp.ok = False
        bad_resp.text = "Internal Server Error"
        cred = _make_credential()
        with patch("services.api_gateway.identity_risk_service.requests") as mock_requests:
            mock_requests.get.side_effect = [good_resp, bad_resp]
            risks = scan_credential_risks(cred)
        assert len(risks) == 1


# ── persist_risks ─────────────────────────────────────────────────────────────

class TestPersistRisks:
    def test_upserts_each_risk(self):
        risks = [_make_risk(risk_id="r1"), _make_risk(risk_id="r2")]
        container = MagicMock()
        db = MagicMock()
        db.get_container_client.return_value = container
        cosmos = MagicMock()
        cosmos.get_database_client.return_value = db

        persist_risks(cosmos, "aap-db", risks)

        assert container.upsert_item.call_count == 2
        call_args = [c.args[0] for c in container.upsert_item.call_args_list]
        assert call_args[0]["id"] == "r1"
        assert call_args[1]["id"] == "r2"

    def test_empty_list_skips_upsert(self):
        cosmos = MagicMock()
        persist_risks(cosmos, "aap-db", [])
        cosmos.get_database_client.assert_not_called()

    def test_cosmos_exception_does_not_raise(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("cosmos down")
        risks = [_make_risk()]
        # Should not raise
        persist_risks(cosmos, "aap-db", risks)


# ── get_risks ─────────────────────────────────────────────────────────────────

class TestGetRisks:
    def _cosmos_item(self, **kwargs) -> Dict[str, Any]:
        r = asdict(_make_risk(**kwargs))
        r["id"] = r["risk_id"]
        return r

    def test_returns_all_risks_no_filter(self):
        items = [self._cosmos_item(risk_id="r1"), self._cosmos_item(risk_id="r2")]
        cosmos = _make_cosmos(items)
        result = get_risks(cosmos, "aap-db")
        assert len(result) == 2

    def test_severity_filter_uses_query(self):
        items = [self._cosmos_item(risk_id="r3", severity="critical")]
        cosmos = _make_cosmos(items)
        result = get_risks(cosmos, "aap-db", severity="critical")
        container = cosmos.get_database_client().get_container_client()
        container.query_items.assert_called_once()
        assert result[0].severity == "critical"

    def test_empty_cosmos_returns_empty(self):
        cosmos = _make_cosmos([])
        result = get_risks(cosmos, "aap-db")
        assert result == []

    def test_cosmos_exception_returns_empty(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("cosmos error")
        result = get_risks(cosmos, "aap-db")
        assert result == []


# ── get_identity_summary ──────────────────────────────────────────────────────

class TestGetIdentitySummary:
    def test_summary_counts_correctly(self):
        items = [
            asdict(_make_risk(risk_id="r1", service_principal_id="sp-1", severity="critical", days_until_expiry=-2)),
            asdict(_make_risk(risk_id="r2", service_principal_id="sp-2", severity="high", days_until_expiry=10)),
            asdict(_make_risk(risk_id="r3", service_principal_id="sp-2", severity="medium", days_until_expiry=45)),
        ]
        for i in items:
            i["id"] = i["risk_id"]
        cosmos = _make_cosmos(items)
        summary = get_identity_summary(cosmos, "aap-db")

        assert summary["total_sps_checked"] == 2       # sp-1 and sp-2 distinct
        assert summary["critical_count"] == 1
        assert summary["high_count"] == 1
        assert summary["medium_count"] == 1
        assert summary["expired_count"] == 1           # days_until_expiry < 0
        assert summary["expiring_30d_count"] == 1      # 0 <= days < 30

    def test_summary_empty_cosmos(self):
        cosmos = _make_cosmos([])
        summary = get_identity_summary(cosmos, "aap-db")
        assert summary["total_sps_checked"] == 0
        assert summary["critical_count"] == 0

    def test_summary_cosmos_error_returns_zeros(self):
        cosmos = MagicMock()
        cosmos.get_database_client.side_effect = Exception("down")
        summary = get_identity_summary(cosmos, "aap-db")
        assert summary["critical_count"] == 0
        assert summary["expired_count"] == 0
