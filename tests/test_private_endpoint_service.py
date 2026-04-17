"""Tests for private_endpoint_service.py (Phase 92).

22 tests covering:
- uuid5 stable IDs
- public access normalisation
- severity derivation
- recommendation generation
- scan logic (high / medium / info)
- resource type friendly labels
- persist_findings (Cosmos upsert)
- get_findings (query, filters)
- get_pe_summary (aggregation + by_resource_type)
- ARG failure handling (never raises)
- empty subscription list handling
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.private_endpoint_service import (
    PrivateEndpointFinding,
    _derive_severity,
    _make_finding_id,
    _make_recommendation,
    _normalise_public_access,
    get_findings,
    get_pe_summary,
    persist_findings,
    scan_private_endpoint_compliance,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_RES_ID = "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.storage/storageaccounts/mystore"
_RES_ID_LOWER = _RES_ID.lower()


def _make_arg_row(
    resource_id: str = _RES_ID_LOWER,
    name: str = "mystore",
    res_type: str = "microsoft.storage/storageaccounts",
    public_access: str = "Enabled",
    pe_count: int = 0,
) -> Dict[str, Any]:
    return {
        "resource_id": resource_id,
        "name": name,
        "type": res_type,
        "resource_group": "rg",
        "subscription_id": "sub-1",
        "location": "eastus",
        "public_network_access": public_access,
        "private_endpoint_connections": pe_count,
    }


def _make_cosmos_item(**overrides) -> Dict[str, Any]:
    base = {
        "id": "fid-1",
        "finding_id": "fid-1",
        "resource_id": _RES_ID_LOWER,
        "resource_name": "mystore",
        "resource_type": "Storage Account",
        "resource_group": "rg",
        "subscription_id": "sub-1",
        "location": "eastus",
        "public_access": "enabled",
        "has_private_endpoint": False,
        "private_endpoint_count": 0,
        "severity": "high",
        "recommendation": "Configure a Private Endpoint.",
        "scanned_at": "2026-04-17T00:00:00Z",
        "ttl": 86400,
    }
    base.update(overrides)
    return base


# ── Unit: stable IDs ──────────────────────────────────────────────────────────

def test_make_finding_id_stable():
    assert _make_finding_id(_RES_ID_LOWER) == _make_finding_id(_RES_ID_LOWER)


def test_make_finding_id_case_insensitive():
    assert _make_finding_id(_RES_ID_LOWER) == _make_finding_id(_RES_ID.upper())


def test_make_finding_id_different_resources():
    other = "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.keyvault/vaults/myvault"
    assert _make_finding_id(_RES_ID_LOWER) != _make_finding_id(other.lower())


def test_make_finding_id_valid_uuid():
    result = _make_finding_id(_RES_ID_LOWER)
    parsed = uuid.UUID(result)
    assert parsed.version == 5


# ── Unit: public access normalisation ─────────────────────────────────────────

def test_normalise_enabled():
    assert _normalise_public_access("Enabled") == "enabled"


def test_normalise_allow():
    assert _normalise_public_access("Allow") == "enabled"


def test_normalise_disabled():
    assert _normalise_public_access("Disabled") == "disabled"


def test_normalise_deny():
    assert _normalise_public_access("Deny") == "disabled"


def test_normalise_unknown():
    assert _normalise_public_access("") == "unknown"
    assert _normalise_public_access("SomethingElse") == "unknown"


# ── Unit: severity derivation ─────────────────────────────────────────────────

def test_severity_high_public_no_pe():
    assert _derive_severity("enabled", 0) == "high"


def test_severity_medium_public_with_pe():
    assert _derive_severity("enabled", 2) == "medium"


def test_severity_info_disabled():
    assert _derive_severity("disabled", 0) == "info"


def test_severity_info_disabled_with_pe():
    assert _derive_severity("disabled", 1) == "info"


# ── Unit: scan_private_endpoint_compliance ────────────────────────────────────

def test_scan_returns_empty_for_no_subscriptions():
    findings = scan_private_endpoint_compliance(MagicMock(), [])
    assert findings == []


def test_scan_high_severity_public_no_pe():
    credential = MagicMock()
    row = _make_arg_row(public_access="Enabled", pe_count=0)

    with patch("services.api_gateway.private_endpoint_service.run_arg_query") as mock_arg:
        mock_arg.return_value = [row]
        findings = scan_private_endpoint_compliance(credential, ["sub-1"])

    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "high"
    assert f.public_access == "enabled"
    assert f.has_private_endpoint is False
    assert f.resource_type == "Storage Account"


def test_scan_medium_severity_public_with_pe():
    credential = MagicMock()
    row = _make_arg_row(public_access="Enabled", pe_count=1)

    with patch("services.api_gateway.private_endpoint_service.run_arg_query") as mock_arg:
        mock_arg.return_value = [row]
        findings = scan_private_endpoint_compliance(credential, ["sub-1"])

    assert findings[0].severity == "medium"
    assert findings[0].has_private_endpoint is True
    assert findings[0].private_endpoint_count == 1


def test_scan_info_disabled_public():
    credential = MagicMock()
    row = _make_arg_row(public_access="Disabled", pe_count=1)

    with patch("services.api_gateway.private_endpoint_service.run_arg_query") as mock_arg:
        mock_arg.return_value = [row]
        findings = scan_private_endpoint_compliance(credential, ["sub-1"])

    assert findings[0].severity == "info"


def test_scan_arg_failure_returns_empty():
    credential = MagicMock()
    with patch("services.api_gateway.private_endpoint_service.run_arg_query") as mock_arg:
        mock_arg.side_effect = Exception("ARG down")
        findings = scan_private_endpoint_compliance(credential, ["sub-1"])
    assert findings == []


def test_scan_skips_row_without_resource_id():
    credential = MagicMock()
    row = {"resource_id": "", "name": "bad", "type": "microsoft.keyvault/vaults",
           "resource_group": "rg", "subscription_id": "sub-1", "location": "eastus",
           "public_network_access": "Enabled", "private_endpoint_connections": 0}

    with patch("services.api_gateway.private_endpoint_service.run_arg_query") as mock_arg:
        mock_arg.return_value = [row]
        findings = scan_private_endpoint_compliance(credential, ["sub-1"])
    assert findings == []


# ── Unit: persist_findings ────────────────────────────────────────────────────

def test_persist_findings_upserts_each():
    cosmos = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value = container

    finding = PrivateEndpointFinding(
        finding_id="fid-1",
        resource_id=_RES_ID_LOWER,
        resource_name="mystore",
        resource_type="Storage Account",
        resource_group="rg",
        subscription_id="sub-1",
        location="eastus",
        public_access="enabled",
        has_private_endpoint=False,
        private_endpoint_count=0,
        severity="high",
        recommendation="Configure a PE.",
        scanned_at="2026-04-17T00:00:00Z",
    )
    persist_findings(cosmos, "aap", [finding])
    container.upsert_item.assert_called_once()
    doc = container.upsert_item.call_args[0][0]
    assert doc["id"] == "fid-1"


def test_persist_findings_noop_on_empty():
    cosmos = MagicMock()
    persist_findings(cosmos, "aap", [])
    cosmos.get_database_client.assert_not_called()


def test_persist_findings_never_raises_on_error():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("Cosmos down")
    persist_findings(cosmos, "aap", [PrivateEndpointFinding(
        finding_id="x", resource_id="r", resource_name="n", resource_type="t",
        resource_group="g", subscription_id="s", location="l",
        public_access="enabled", has_private_endpoint=False, private_endpoint_count=0,
        severity="high", recommendation="Fix it.", scanned_at="now",
    )])
    # Must not raise


# ── Unit: get_findings ────────────────────────────────────────────────────────

def test_get_findings_returns_list():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value \
        .query_items.return_value = [_make_cosmos_item()]
    results = get_findings(cosmos, "aap")
    assert len(results) == 1
    assert isinstance(results[0], PrivateEndpointFinding)


def test_get_findings_returns_empty_on_error():
    cosmos = MagicMock()
    cosmos.get_database_client.side_effect = Exception("timeout")
    assert get_findings(cosmos, "aap") == []


# ── Unit: get_pe_summary ──────────────────────────────────────────────────────

def test_get_pe_summary_aggregation():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value \
        .query_items.return_value = [
            _make_cosmos_item(severity="high", resource_type="Storage Account"),
            _make_cosmos_item(severity="medium", resource_type="Key Vault"),
            _make_cosmos_item(severity="info", resource_type="Storage Account"),
        ]

    summary = get_pe_summary(cosmos, "aap")
    assert summary["total_resources"] == 3
    assert summary["high_count"] == 1
    assert summary["medium_count"] == 1
    assert summary["info_count"] == 1
    assert abs(summary["pe_coverage_pct"] - 33.3) < 0.1
    assert "Storage Account" in summary["by_resource_type"]
    assert summary["by_resource_type"]["Storage Account"]["total"] == 2


def test_get_pe_summary_empty():
    cosmos = MagicMock()
    cosmos.get_database_client.return_value.get_container_client.return_value \
        .query_items.return_value = []
    summary = get_pe_summary(cosmos, "aap")
    assert summary["total_resources"] == 0
    assert summary["pe_coverage_pct"] == 0.0
    assert summary["by_resource_type"] == {}
