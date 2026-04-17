from __future__ import annotations
"""Tests for DriftDetector — Phase 58 IaC Drift Detection."""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from services.api_gateway.drift_detector import (
    DriftDetector,
    DriftFinding,
    TerraformResource,
    _extract_subscription_id,
    _flatten_dict,
    classify_drift_severity,
    compare_attributes,
    parse_tfstate_resources,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TFSTATE = {
    "version": 4,
    "terraform_version": "1.7.0",
    "resources": [
        {
            "mode": "managed",
            "type": "azurerm_resource_group",
            "name": "main",
            "instances": [
                {
                    "attributes": {
                        "id": "/subscriptions/sub-123/resourceGroups/rg-aap-prod",
                        "name": "rg-aap-prod",
                        "location": "eastus",
                        "tags": {"env": "prod"},
                    }
                }
            ],
        },
        {
            "mode": "managed",
            "type": "azurerm_container_app",
            "name": "orchestrator",
            "instances": [
                {
                    "attributes": {
                        "id": "/subscriptions/sub-123/resourceGroups/rg-aap-prod/providers/Microsoft.App/containerApps/ca-orchestrator",
                        "name": "ca-orchestrator",
                        "location": "eastus",
                        "revision_mode": "Single",
                    }
                }
            ],
        },
        {
            "mode": "data",
            "type": "azurerm_subscription",
            "name": "current",
            "instances": [
                {
                    "attributes": {
                        "id": "/subscriptions/sub-123",
                    }
                }
            ],
        },
    ],
}


@pytest.fixture
def mock_cosmos():
    cosmos = MagicMock()
    db = MagicMock()
    container = MagicMock()
    cosmos.get_database_client.return_value = db
    db.get_container_client.return_value = container
    container.query_items.return_value = []
    container.upsert_item.return_value = None
    return cosmos, container


# ---------------------------------------------------------------------------
# Test: parse_tfstate_resources
# ---------------------------------------------------------------------------


def test_parse_tfstate_resources_extracts_managed_only():
    resources = parse_tfstate_resources(SAMPLE_TFSTATE)
    # data source should be excluded
    assert len(resources) == 2
    types = {r.terraform_type for r in resources}
    assert "azurerm_resource_group" in types
    assert "azurerm_container_app" in types
    assert "azurerm_subscription" not in types


def test_parse_tfstate_resources_captures_attributes():
    resources = parse_tfstate_resources(SAMPLE_TFSTATE)
    rg = next(r for r in resources if r.terraform_type == "azurerm_resource_group")
    assert rg.attributes["location"] == "eastus"
    assert rg.resource_id == "/subscriptions/sub-123/resourceGroups/rg-aap-prod"


def test_parse_tfstate_resources_empty_state():
    resources = parse_tfstate_resources({})
    assert resources == []


def test_parse_tfstate_resources_skips_missing_id():
    state = {
        "resources": [
            {
                "mode": "managed",
                "type": "azurerm_resource_group",
                "name": "orphan",
                "instances": [{"attributes": {"name": "no-id-here"}}],
            }
        ]
    }
    resources = parse_tfstate_resources(state)
    assert resources == []


# ---------------------------------------------------------------------------
# Test: classify_drift_severity
# ---------------------------------------------------------------------------


def test_drift_finding_severity_critical_for_deleted_resource():
    sev = classify_drift_severity("*", "<exists>", "<deleted>", resource_deleted=True)
    assert sev == "CRITICAL"


def test_drift_finding_severity_low_for_tags():
    sev = classify_drift_severity("tags.environment", "prod", "staging")
    assert sev == "LOW"


def test_drift_finding_severity_high_for_sku():
    sev = classify_drift_severity("sku.name", "Standard", "Basic")
    assert sev == "HIGH"


def test_drift_finding_severity_high_for_location():
    sev = classify_drift_severity("location", "eastus", "westus")
    assert sev == "HIGH"


def test_drift_finding_severity_medium_for_numeric():
    sev = classify_drift_severity("replica_count", 2, 3)
    assert sev == "MEDIUM"


# ---------------------------------------------------------------------------
# Test: no drift when state matches
# ---------------------------------------------------------------------------


def test_no_drift_when_state_matches():
    tf_attrs = {"location": "eastus", "name": "rg-prod", "tags.env": "prod"}
    live_attrs = {"location": "eastus", "name": "rg-prod", "tags.env": "prod"}
    findings = compare_attributes(
        resource_id="/subscriptions/sub-123/resourceGroups/rg-prod",
        resource_type="azurerm_resource_group",
        resource_name="main",
        terraform_attrs=tf_attrs,
        live_attrs=live_attrs,
    )
    assert findings == []


def test_drift_detected_when_location_differs():
    tf_attrs = {"location": "eastus", "name": "rg-prod"}
    live_attrs = {"location": "westus", "name": "rg-prod"}
    findings = compare_attributes(
        resource_id="/subscriptions/sub-123/resourceGroups/rg-prod",
        resource_type="azurerm_resource_group",
        resource_name="main",
        terraform_attrs=tf_attrs,
        live_attrs=live_attrs,
    )
    assert len(findings) == 1
    assert findings[0].attribute_path == "location"
    assert findings[0].drift_severity == "HIGH"


# ---------------------------------------------------------------------------
# Test: findings API returns list
# ---------------------------------------------------------------------------


def test_findings_api_returns_list(mock_cosmos):
    cosmos, container = mock_cosmos
    stored = [
        {
            "id": "drift-abc123",
            "finding_id": "drift-abc123",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg",
            "resource_type": "azurerm_resource_group",
            "resource_name": "main",
            "attribute_path": "location",
            "terraform_value": "eastus",
            "live_value": "westus",
            "drift_severity": "HIGH",
            "detected_at": "2026-04-16T00:00:00Z",
        }
    ]
    container.query_items.return_value = stored

    detector = DriftDetector(credential=MagicMock(), cosmos_client=cosmos)
    result = detector.list_findings(severity="HIGH", limit=10)

    assert "findings" in result
    assert result["total"] == 1
    assert result["findings"][0]["drift_severity"] == "HIGH"


def test_findings_api_returns_empty_when_no_cosmos():
    detector = DriftDetector(credential=MagicMock(), cosmos_client=None)
    result = detector.list_findings()
    assert result["findings"] == []
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# Test: run_scan returns scan metadata
# ---------------------------------------------------------------------------


def test_run_scan_returns_metadata_when_tfstate_unavailable():
    """When tfstate can't be loaded, scan returns zero findings with a warning."""
    detector = DriftDetector(
        credential=MagicMock(),
        cosmos_client=None,
        storage_account_url="",  # Empty → load will fail gracefully
    )
    result = detector.run_scan(save_to_cosmos=False)
    assert "findings" in result
    assert result["total_findings"] == 0
    assert "scanned_at" in result
    assert "duration_ms" in result


# ---------------------------------------------------------------------------
# Test: propose_terraform_fix
# ---------------------------------------------------------------------------


def test_propose_terraform_fix_deleted_resource():
    detector = DriftDetector(credential=MagicMock(), cosmos_client=None)
    finding = {
        "finding_id": "drift-del-1",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg",
        "resource_type": "azurerm_resource_group",
        "resource_name": "main",
        "attribute_path": "*",
        "terraform_value": "<exists>",
        "live_value": "<deleted>",
        "drift_severity": "CRITICAL",
    }
    diff = detector.propose_terraform_fix(finding)
    assert "terraform import" in diff or "state rm" in diff
    assert "CRITICAL" in diff


def test_propose_terraform_fix_attribute_drift():
    detector = DriftDetector(credential=MagicMock(), cosmos_client=None)
    finding = {
        "finding_id": "drift-loc-1",
        "resource_id": "/subscriptions/sub-1/resourceGroups/rg",
        "resource_type": "azurerm_resource_group",
        "resource_name": "main",
        "attribute_path": "location",
        "terraform_value": "eastus",
        "live_value": "westus",
        "drift_severity": "HIGH",
    }
    diff = detector.propose_terraform_fix(finding)
    assert "eastus" in diff
    assert "westus" in diff


# ---------------------------------------------------------------------------
# Test: helper utilities
# ---------------------------------------------------------------------------


def test_extract_subscription_id():
    rid = "/subscriptions/abc-123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
    assert _extract_subscription_id(rid) == "abc-123"


def test_extract_subscription_id_invalid():
    assert _extract_subscription_id("not-a-resource-id") == ""


def test_flatten_dict_nested():
    obj = {"a": {"b": {"c": 1}}, "d": [1, 2]}
    flat = _flatten_dict(obj)
    assert flat["a.b.c"] == 1
    assert flat["d[0]"] == 1
    assert flat["d[1]"] == 2
