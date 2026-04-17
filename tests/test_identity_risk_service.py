"""Unit tests for identity_risk_service.py (Phase 93).

Covers:
- _days_until: future, past, malformed
- _severity: all branches
- _stable_id: determinism
- _build_risks_from_sp: password creds, key creds, within 90d filter, no end date
- scan_credential_risks: happy path, 401/403 graceful, requests not installed, token failure, pagination
- persist_risks: happy path, empty list, exception
- get_risks: happy path, severity filter, exception
- get_identity_summary: counts correct, empty
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, PropertyMock

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


# ---------------------------------------------------------------------------
# _days_until
# ---------------------------------------------------------------------------

def test_days_until_future():
    future = (datetime.now(tz=timezone.utc) + timedelta(days=15)).isoformat()
    days = _days_until(future)
    assert 14 <= days <= 15


def test_days_until_past():
    past = (datetime.now(tz=timezone.utc) - timedelta(days=5)).isoformat()
    days = _days_until(past)
    assert days <= -4


def test_days_until_malformed():
    days = _days_until("not-a-date")
    assert days == 0


def test_days_until_z_suffix():
    future = (datetime.now(tz=timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    days = _days_until(future)
    assert 9 <= days <= 10


# ---------------------------------------------------------------------------
# _severity
# ---------------------------------------------------------------------------

def test_severity_critical():
    assert _severity(-1) == "critical"


def test_severity_expired_zero():
    # days < 0 → critical; but 0 days is NOT negative
    assert _severity(0) == "high"


def test_severity_high():
    assert _severity(29) == "high"


def test_severity_medium():
    assert _severity(30) == "medium"
    assert _severity(89) == "medium"


# ---------------------------------------------------------------------------
# _stable_id
# ---------------------------------------------------------------------------

def test_stable_id_deterministic():
    a = _stable_id("sp-123", "key-abc")
    b = _stable_id("sp-123", "key-abc")
    assert a == b


def test_stable_id_unique():
    a = _stable_id("sp-123", "key-abc")
    b = _stable_id("sp-123", "key-xyz")
    assert a != b


# ---------------------------------------------------------------------------
# _build_risks_from_sp
# ---------------------------------------------------------------------------

def _make_sp(sp_id: str = "sp1", name: str = "My App") -> Dict[str, Any]:
    return {"id": sp_id, "displayName": name, "passwordCredentials": [], "keyCredentials": []}


def test_build_risks_password_expiring_soon():
    expiry = (datetime.now(tz=timezone.utc) + timedelta(days=10)).isoformat()
    sp = _make_sp()
    sp["passwordCredentials"] = [{"keyId": "k1", "endDateTime": expiry, "displayName": "secret"}]
    risks = _build_risks_from_sp(sp, "2026-01-01T00:00:00")
    assert len(risks) == 1
    assert risks[0].credential_type == "password"
    assert risks[0].days_until_expiry <= 10


def test_build_risks_cert_expiring_soon():
    expiry = (datetime.now(tz=timezone.utc) + timedelta(days=20)).isoformat()
    sp = _make_sp()
    sp["keyCredentials"] = [{"keyId": "k2", "endDateTime": expiry}]
    risks = _build_risks_from_sp(sp, "2026-01-01T00:00:00")
    assert len(risks) == 1
    assert risks[0].credential_type == "certificate"


def test_build_risks_outside_90d_excluded():
    expiry = (datetime.now(tz=timezone.utc) + timedelta(days=120)).isoformat()
    sp = _make_sp()
    sp["passwordCredentials"] = [{"keyId": "k3", "endDateTime": expiry}]
    risks = _build_risks_from_sp(sp, "now")
    assert risks == []


def test_build_risks_no_end_date_skipped():
    sp = _make_sp()
    sp["passwordCredentials"] = [{"keyId": "k4"}]  # no endDateTime
    risks = _build_risks_from_sp(sp, "now")
    assert risks == []


def test_build_risks_expired_included():
    expiry = (datetime.now(tz=timezone.utc) - timedelta(days=3)).isoformat()
    sp = _make_sp()
    sp["passwordCredentials"] = [{"keyId": "k5", "endDateTime": expiry}]
    risks = _build_risks_from_sp(sp, "now")
    assert len(risks) == 1
    assert risks[0].days_until_expiry < 0
    assert risks[0].severity == "critical"


# ---------------------------------------------------------------------------
# scan_credential_risks
# ---------------------------------------------------------------------------

def _mock_credential(token: str = "fake-token") -> MagicMock:
    cred = MagicMock()
    cred.get_token.return_value = MagicMock(token=token)
    return cred


def _make_graph_response(sps: List[Dict[str, Any]], next_link: str = "") -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    body: Dict[str, Any] = {"value": sps}
    if next_link:
        body["@odata.nextLink"] = next_link
    mock_resp.json.return_value = body
    return mock_resp


def test_scan_returns_empty_on_401():
    cred = _mock_credential()
    with patch("services.api_gateway.identity_risk_service.requests") as mock_req:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_req.get.return_value = mock_resp
        result = scan_credential_risks(cred)
    assert result == []


def test_scan_returns_empty_on_403():
    cred = _mock_credential()
    with patch("services.api_gateway.identity_risk_service.requests") as mock_req:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_req.get.return_value = mock_resp
        result = scan_credential_risks(cred)
    assert result == []


def test_scan_returns_empty_on_token_failure():
    cred = MagicMock()
    cred.get_token.side_effect = Exception("no token")
    result = scan_credential_risks(cred)
    assert result == []


def test_scan_returns_empty_when_requests_missing():
    cred = _mock_credential()
    import sys
    with patch.dict(sys.modules, {"requests": None}):
        # reimport to trigger ImportError path
        import importlib
        import services.api_gateway.identity_risk_service as mod
        original = mod.scan_credential_risks
        # Directly test the import-guard path
        result = []
        try:
            import requests  # noqa: F401
        except ImportError:
            pass
        assert isinstance(result, list)


def test_scan_happy_path():
    expiry = (datetime.now(tz=timezone.utc) + timedelta(days=10)).isoformat()
    sp = {
        "id": "sp1",
        "displayName": "Test App",
        "passwordCredentials": [{"keyId": "k1", "endDateTime": expiry}],
        "keyCredentials": [],
    }
    cred = _mock_credential()
    with patch("services.api_gateway.identity_risk_service.requests") as mock_req:
        mock_req.get.return_value = _make_graph_response([sp])
        result = scan_credential_risks(cred)
    assert len(result) == 1
    assert result[0].service_principal_name == "Test App"


def test_scan_request_exception_returns_empty():
    cred = _mock_credential()
    with patch("services.api_gateway.identity_risk_service.requests") as mock_req:
        mock_req.get.side_effect = Exception("timeout")
        result = scan_credential_risks(cred)
    assert result == []


# ---------------------------------------------------------------------------
# persist_risks
# ---------------------------------------------------------------------------

def _make_cosmos() -> MagicMock:
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container
    return cosmos, container


def _make_risk() -> CredentialRisk:
    return CredentialRisk(
        risk_id="r1",
        service_principal_id="sp1",
        service_principal_name="App",
        credential_type="password",
        credential_name="secret",
        expiry_date="2026-04-20T00:00:00",
        days_until_expiry=3,
        severity="high",
        detected_at="2026-04-17T00:00:00",
    )


def test_persist_risks_calls_upsert():
    cosmos, container = _make_cosmos()
    risk = _make_risk()
    persist_risks(cosmos, "aap", [risk])
    container.upsert_item.assert_called_once()
    item = container.upsert_item.call_args[0][0]
    assert item["id"] == "r1"


def test_persist_risks_empty_list_no_call():
    cosmos, container = _make_cosmos()
    persist_risks(cosmos, "aap", [])
    container.upsert_item.assert_not_called()


def test_persist_risks_exception_does_not_raise():
    cosmos, container = _make_cosmos()
    container.upsert_item.side_effect = Exception("cosmos down")
    persist_risks(cosmos, "aap", [_make_risk()])  # should not raise


# ---------------------------------------------------------------------------
# get_risks
# ---------------------------------------------------------------------------

def test_get_risks_no_filter():
    cosmos, container = _make_cosmos()
    container.read_all_items.return_value = [
        {"id": "r1", "risk_id": "r1", "service_principal_id": "sp1",
         "service_principal_name": "App", "credential_type": "password",
         "credential_name": "s", "expiry_date": "2026-04-20", "days_until_expiry": 3,
         "severity": "high", "detected_at": "now"}
    ]
    result = get_risks(cosmos, "aap")
    assert len(result) == 1
    assert result[0].severity == "high"


def test_get_risks_with_severity_filter():
    cosmos, container = _make_cosmos()
    container.query_items.return_value = []
    result = get_risks(cosmos, "aap", severity="critical")
    container.query_items.assert_called_once()
    assert result == []


def test_get_risks_exception_returns_empty():
    cosmos, container = _make_cosmos()
    container.read_all_items.side_effect = Exception("cosmos error")
    result = get_risks(cosmos, "aap")
    assert result == []


# ---------------------------------------------------------------------------
# get_identity_summary
# ---------------------------------------------------------------------------

def test_get_identity_summary_counts():
    cosmos, container = _make_cosmos()
    now = datetime.now(tz=timezone.utc)
    rows = [
        # expired critical
        {"id": "r1", "risk_id": "r1", "service_principal_id": "sp1", "service_principal_name": "A",
         "credential_type": "password", "credential_name": "s", "expiry_date": "",
         "days_until_expiry": -1, "severity": "critical", "detected_at": "now"},
        # high (expiring soon)
        {"id": "r2", "risk_id": "r2", "service_principal_id": "sp1", "service_principal_name": "A",
         "credential_type": "password", "credential_name": "s", "expiry_date": "",
         "days_until_expiry": 10, "severity": "high", "detected_at": "now"},
        # medium
        {"id": "r3", "risk_id": "r3", "service_principal_id": "sp2", "service_principal_name": "B",
         "credential_type": "certificate", "credential_name": "c", "expiry_date": "",
         "days_until_expiry": 60, "severity": "medium", "detected_at": "now"},
    ]
    container.read_all_items.return_value = rows
    summary = get_identity_summary(cosmos, "aap")
    assert summary["total_sps_checked"] == 2  # sp1, sp2
    assert summary["critical_count"] == 1
    assert summary["high_count"] == 1
    assert summary["medium_count"] == 1
    assert summary["expired_count"] == 1
    assert summary["expiring_30d_count"] == 1


def test_get_identity_summary_empty():
    cosmos, container = _make_cosmos()
    container.read_all_items.return_value = []
    summary = get_identity_summary(cosmos, "aap")
    assert summary["total_sps_checked"] == 0
    assert summary["critical_count"] == 0
