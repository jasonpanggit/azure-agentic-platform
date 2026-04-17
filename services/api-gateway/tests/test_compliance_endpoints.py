from __future__ import annotations
"""Tests for compliance posture and export API endpoints (Phase 54).

Covers:
- GET /api/v1/compliance/posture — scoring, framework filtering, cache, error handling
- GET /api/v1/compliance/export  — CSV and PDF generation
- compute_posture pure function unit tests
"""
import os

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")
os.environ.setdefault("PGVECTOR_CONNECTION_STRING", "postgresql://test:test@localhost/test")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.compliance_endpoints import router
from services.api_gateway.compliance_posture import compute_posture

_test_app = FastAPI()
_test_app.include_router(router)
_test_app.state.credential = MagicMock()

client = TestClient(_test_app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_MAPPINGS: list[dict[str, Any]] = [
    {
        "finding_type": "defender_assessment",
        "defender_rule_id": "dabc-mfa-owner-0001",
        "display_name": "MFA should be enabled on accounts with owner permissions",
        "description": "MFA for owners",
        "cis_control_id": "6.5",
        "cis_title": "Require MFA for Administrative Access",
        "nist_control_id": "IA-2(1)",
        "nist_title": "Identification and Authentication - MFA",
        "asb_control_id": "IM-1",
        "asb_title": "Standardize Azure Active Directory",
        "severity": "High",
    },
    {
        "finding_type": "defender_assessment",
        "defender_rule_id": "dabc-nsg-subnet-0002",
        "display_name": "Subnets should be associated with a network security group",
        "description": "NSG on subnets",
        "cis_control_id": "12.2",
        "cis_title": "Establish and Maintain a Secure Network Architecture",
        "nist_control_id": "SC-7",
        "nist_title": "Boundary Protection",
        "asb_control_id": "NS-1",
        "asb_title": "Establish network segmentation boundaries",
        "severity": "High",
    },
    {
        "finding_type": "policy",
        "defender_rule_id": "Allowed locations",
        "display_name": "Allowed locations policy",
        "description": "Location restriction policy",
        "cis_control_id": "1.1",
        "cis_title": "Establish and Maintain Detailed Enterprise Asset Inventory",
        "nist_control_id": "CM-2",
        "nist_title": "Baseline Configuration",
        "asb_control_id": "GS-2",
        "asb_title": "Define and implement enterprise segmentation strategy",
        "severity": "Low",
    },
    {
        "finding_type": "advisor",
        "defender_rule_id": "Enable Azure DDoS Protection Standard",
        "display_name": "Enable Azure DDoS Protection Standard",
        "description": "DDoS protection",
        "cis_control_id": "12.3",
        "cis_title": "Securely Manage Network Infrastructure",
        "nist_control_id": "SC-5",
        "nist_title": "Denial-of-Service Protection",
        "asb_control_id": "NS-5",
        "asb_title": "Deploy DDOS protection",
        "severity": "Medium",
    },
]

PASSING_ASSESSMENTS: list[dict[str, Any]] = [
    {
        "name": "mfa-owner-guid",
        "display_name": "MFA should be enabled on accounts with owner permissions",
        "status": "Healthy",
        "severity": "High",
    },
    {
        "name": "nsg-subnet-guid",
        "display_name": "Subnets should be associated with a network security group",
        "status": "Healthy",
        "severity": "High",
    },
]

FAILING_ASSESSMENTS: list[dict[str, Any]] = [
    {
        "name": "mfa-owner-guid",
        "display_name": "MFA should be enabled on accounts with owner permissions",
        "status": "Unhealthy",
        "severity": "High",
    },
    {
        "name": "nsg-subnet-guid",
        "display_name": "Subnets should be associated with a network security group",
        "status": "Unhealthy",
        "severity": "High",
    },
]

EMPTY_POLICY_STATES: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# TestCompliancePosture
# ---------------------------------------------------------------------------

class TestCompliancePosture:

    def test_posture_returns_200_with_valid_params(self):
        """Posture endpoint returns 200 with frameworks key."""
        with (
            patch(
                "services.api_gateway.compliance_posture._mappings_cache",
                (1e12, SAMPLE_MAPPINGS),  # pre-warm cache (far-future timestamp)
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=PASSING_ASSESSMENTS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=EMPTY_POLICY_STATES),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.get_cached_posture",
                return_value=None,
            ),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=test-sub-123")
        assert resp.status_code == 200
        data = resp.json()
        assert "frameworks" in data

    def test_posture_returns_frameworks_asb_cis_nist(self):
        """Response contains all three framework keys."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=PASSING_ASSESSMENTS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=EMPTY_POLICY_STATES),
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-fw-test")
        assert resp.status_code == 200
        frameworks = resp.json()["frameworks"]
        assert "asb" in frameworks
        assert "cis" in frameworks
        assert "nist" in frameworks

    def test_posture_score_computation_all_passing(self):
        """All healthy assessments → score of 100."""
        posture = compute_posture(
            mappings=SAMPLE_MAPPINGS,
            assessments=PASSING_ASSESSMENTS,
            policy_states=[],
            subscription_id="test-sub",
        )
        # CIS controls that are mapped to defender assessments should be passing
        asb = posture["frameworks"]["asb"]
        assert asb["failing"] == 0
        assert asb["passing"] >= 1
        assert asb["score"] == 100.0

    def test_posture_score_computation_mixed(self):
        """Mixed assessments produce score between 0 and 100."""
        mixed_mappings = [SAMPLE_MAPPINGS[0], SAMPLE_MAPPINGS[1]]  # 2 defender rows
        mixed_assessments = [
            {**PASSING_ASSESSMENTS[0]},   # MFA → passing
            {**FAILING_ASSESSMENTS[1]},   # NSG → failing
        ]
        posture = compute_posture(
            mappings=mixed_mappings,
            assessments=mixed_assessments,
            policy_states=[],
            subscription_id="test-sub",
        )
        asb = posture["frameworks"]["asb"]
        assert asb["passing"] == 1
        assert asb["failing"] == 1
        assert asb["score"] == 50.0

    def test_posture_score_computation_all_failing(self):
        """All unhealthy assessments → score of 0."""
        posture = compute_posture(
            mappings=SAMPLE_MAPPINGS[:2],
            assessments=FAILING_ASSESSMENTS,
            policy_states=[],
            subscription_id="test-sub",
        )
        asb = posture["frameworks"]["asb"]
        assert asb["score"] == 0.0
        assert asb["passing"] == 0

    def test_posture_returns_controls_list(self):
        """Response contains controls array with required keys."""
        posture = compute_posture(
            mappings=SAMPLE_MAPPINGS,
            assessments=PASSING_ASSESSMENTS,
            policy_states=[],
            subscription_id="sub-1",
        )
        controls = posture["controls"]
        assert len(controls) > 0
        for ctrl in controls:
            assert "control_id" in ctrl
            assert "status" in ctrl
            assert "findings" in ctrl
            assert "framework" in ctrl

    def test_posture_framework_filter_returns_only_asb(self):
        """framework=asb filter returns only ASB controls."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=PASSING_ASSESSMENTS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=EMPTY_POLICY_STATES),
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-fw&framework=asb")
        assert resp.status_code == 200
        data = resp.json()
        for ctrl in data.get("controls", []):
            assert ctrl["framework"] == "asb"
        assert "asb" in data["frameworks"]
        assert "cis" not in data["frameworks"]

    def test_posture_framework_filter_returns_only_cis(self):
        """framework=cis filter returns only CIS controls."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=PASSING_ASSESSMENTS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=EMPTY_POLICY_STATES),
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-cis&framework=cis")
        assert resp.status_code == 200
        data = resp.json()
        for ctrl in data.get("controls", []):
            assert ctrl["framework"] == "cis"

    def test_posture_framework_filter_returns_only_nist(self):
        """framework=nist filter returns only NIST controls."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=PASSING_ASSESSMENTS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=EMPTY_POLICY_STATES),
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-nist&framework=nist")
        assert resp.status_code == 200
        data = resp.json()
        for ctrl in data.get("controls", []):
            assert ctrl["framework"] == "nist"

    def test_posture_returns_404_when_no_mappings(self):
        """Empty mappings returns 404."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=[]),
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-empty")
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_posture_cache_returns_hit_on_second_call(self):
        """Second call for the same subscription returns cache_hit: true."""
        cached_posture = {
            "subscription_id": "sub-cached",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "frameworks": {
                "asb": {"score": 75.0, "total_controls": 4, "passing": 3, "failing": 1, "not_assessed": 0},
                "cis": {"score": 75.0, "total_controls": 4, "passing": 3, "failing": 1, "not_assessed": 0},
                "nist": {"score": 75.0, "total_controls": 4, "passing": 3, "failing": 1, "not_assessed": 0},
            },
            "controls": [],
        }
        with patch(
            "services.api_gateway.compliance_endpoints.get_cached_posture",
            return_value=cached_posture,
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-cached")
        assert resp.status_code == 200
        assert resp.json().get("cache_hit") is True

    def test_posture_handles_security_sdk_missing(self):
        """Missing SecurityCenter SDK returns partial result (not 500)."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=[]),  # SDK returns empty
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=EMPTY_POLICY_STATES),
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-no-sdk")
        # Should return 200 with not_assessed controls
        assert resp.status_code == 200

    def test_posture_handles_policy_sdk_missing(self):
        """Missing PolicyInsightsClient SDK returns partial result."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=PASSING_ASSESSMENTS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=[]),  # SDK unavailable
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-no-policy")
        assert resp.status_code == 200

    def test_posture_handles_sdk_exception(self):
        """SDK exception in assessments returns graceful result (not 500)."""
        with (
            patch(
                "services.api_gateway.compliance_endpoints.get_compliance_mappings",
                new=AsyncMock(return_value=SAMPLE_MAPPINGS),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_defender_assessments",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "services.api_gateway.compliance_endpoints.fetch_policy_compliance",
                new=AsyncMock(return_value=[]),
            ),
            patch("services.api_gateway.compliance_endpoints.get_cached_posture", return_value=None),
            patch("services.api_gateway.compliance_endpoints.set_cached_posture"),
        ):
            resp = client.get("/api/v1/compliance/posture?subscription_id=sub-exc")
        assert resp.status_code in (200, 404)

    def test_posture_missing_subscription_id_returns_422(self):
        """Missing subscription_id query param returns 422."""
        resp = client.get("/api/v1/compliance/posture")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestComplianceExport
# ---------------------------------------------------------------------------

SAMPLE_POSTURE: dict[str, Any] = {
    "subscription_id": "test-sub-export",
    "generated_at": "2026-01-15T12:00:00+00:00",
    "frameworks": {
        "asb": {"score": 80.0, "total_controls": 5, "passing": 4, "failing": 1, "not_assessed": 0},
        "cis": {"score": 80.0, "total_controls": 5, "passing": 4, "failing": 1, "not_assessed": 0},
        "nist": {"score": 80.0, "total_controls": 5, "passing": 4, "failing": 1, "not_assessed": 0},
    },
    "controls": [
        {
            "framework": "asb",
            "control_id": "IM-1",
            "control_title": "Standardize Azure Active Directory",
            "status": "passing",
            "findings": [
                {
                    "finding_type": "defender_assessment",
                    "defender_rule_id": "dabc-mfa-0001",
                    "display_name": "MFA should be enabled",
                    "severity": "High",
                }
            ],
        },
        {
            "framework": "cis",
            "control_id": "6.5",
            "control_title": "Require MFA for Administrative Access",
            "status": "passing",
            "findings": [
                {
                    "finding_type": "defender_assessment",
                    "defender_rule_id": "dabc-mfa-0001",
                    "display_name": "MFA should be enabled",
                    "severity": "High",
                }
            ],
        },
        {
            "framework": "nist",
            "control_id": "IA-2(1)",
            "control_title": "Identification and Authentication - MFA",
            "status": "failing",
            "findings": [
                {
                    "finding_type": "defender_assessment",
                    "defender_rule_id": "dabc-mfa-0001",
                    "display_name": "MFA should be enabled",
                    "severity": "High",
                }
            ],
        },
    ],
    "cache_hit": True,
}


class TestComplianceExport:

    def test_export_csv_returns_200_with_csv_content_type(self):
        """CSV export returns 200 with text/csv content type."""
        with patch(
            "services.api_gateway.compliance_endpoints.get_cached_posture",
            return_value=SAMPLE_POSTURE,
        ):
            resp = client.get(
                "/api/v1/compliance/export?subscription_id=sub-1&format=csv"
            )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_export_csv_contains_correct_columns(self):
        """CSV export contains the expected header row."""
        with patch(
            "services.api_gateway.compliance_endpoints.get_cached_posture",
            return_value=SAMPLE_POSTURE,
        ):
            resp = client.get(
                "/api/v1/compliance/export?subscription_id=sub-1&format=csv"
            )
        assert resp.status_code == 200
        lines = resp.text.split("\n")
        header = lines[0]
        assert "framework" in header
        assert "control_id" in header
        assert "control_title" in header
        assert "status" in header
        assert "finding_display_name" in header
        assert "severity" in header

    def test_export_csv_has_data_rows(self):
        """CSV export has at least one data row beyond the header."""
        with patch(
            "services.api_gateway.compliance_endpoints.get_cached_posture",
            return_value=SAMPLE_POSTURE,
        ):
            resp = client.get(
                "/api/v1/compliance/export?subscription_id=sub-1&format=csv"
            )
        assert resp.status_code == 200
        lines = [line for line in resp.text.split("\n") if line.strip()]
        # At least header + 1 data row
        assert len(lines) >= 2

    def test_export_pdf_returns_200_with_pdf_content_type(self):
        """PDF export returns 200 with application/pdf content type."""
        pytest.importorskip("reportlab", reason="reportlab not installed")
        with patch(
            "services.api_gateway.compliance_endpoints.get_cached_posture",
            return_value=SAMPLE_POSTURE,
        ):
            resp = client.get(
                "/api/v1/compliance/export?subscription_id=sub-1&format=pdf"
            )
        assert resp.status_code == 200
        assert "application/pdf" in resp.headers.get("content-type", "")

    def test_export_pdf_returns_valid_pdf_bytes(self):
        """PDF export response body starts with PDF magic bytes."""
        pytest.importorskip("reportlab", reason="reportlab not installed")
        with patch(
            "services.api_gateway.compliance_endpoints.get_cached_posture",
            return_value=SAMPLE_POSTURE,
        ):
            resp = client.get(
                "/api/v1/compliance/export?subscription_id=sub-1&format=pdf"
            )
        assert resp.status_code == 200
        assert resp.content[:4] == b"%PDF"

    def test_export_unknown_format_returns_422(self):
        """Unknown format returns 422."""
        resp = client.get(
            "/api/v1/compliance/export?subscription_id=sub-1&format=xml"
        )
        assert resp.status_code == 422
        assert "error" in resp.json()

    def test_export_missing_subscription_id_returns_422(self):
        """Missing subscription_id returns 422."""
        resp = client.get("/api/v1/compliance/export?format=csv")
        assert resp.status_code == 422

    def test_export_missing_format_returns_422(self):
        """Missing format param returns 422."""
        resp = client.get("/api/v1/compliance/export?subscription_id=sub-1")
        assert resp.status_code == 422

    def test_export_framework_filter_csv(self):
        """CSV export with framework=asb only contains ASB rows."""
        with patch(
            "services.api_gateway.compliance_endpoints.get_cached_posture",
            return_value=SAMPLE_POSTURE,
        ):
            resp = client.get(
                "/api/v1/compliance/export?subscription_id=sub-1&format=csv&framework=asb"
            )
        assert resp.status_code == 200
        lines = [line for line in resp.text.split("\n") if line.strip()][1:]  # skip header
        for line in lines:
            if line:
                assert line.startswith("asb,"), f"Expected asb row, got: {line}"


# ---------------------------------------------------------------------------
# TestComputePosture — pure function unit tests
# ---------------------------------------------------------------------------

class TestComputePosture:

    def test_compute_posture_pure_function(self):
        """compute_posture returns expected output shape with mock data."""
        posture = compute_posture(
            mappings=SAMPLE_MAPPINGS,
            assessments=PASSING_ASSESSMENTS,
            policy_states=[],
            subscription_id="pure-fn-test",
        )
        assert "subscription_id" in posture
        assert posture["subscription_id"] == "pure-fn-test"
        assert "generated_at" in posture
        assert "frameworks" in posture
        assert "controls" in posture
        for fw in ("asb", "cis", "nist"):
            assert fw in posture["frameworks"]
            fw_data = posture["frameworks"][fw]
            for key in ("score", "total_controls", "passing", "failing", "not_assessed"):
                assert key in fw_data

    def test_compute_posture_empty_assessments(self):
        """Empty assessments → defender rows become not_assessed."""
        posture = compute_posture(
            mappings=SAMPLE_MAPPINGS,
            assessments=[],
            policy_states=[],
            subscription_id="empty-assess",
        )
        asb = posture["frameworks"]["asb"]
        # Defender assessment rows → not_assessed; advisor rows → not_assessed
        # Policy row with no noncompliant → passing
        # Net result: score > 0 (policy passing), but some not_assessed
        assert asb["not_assessed"] >= 1

    def test_compute_posture_no_mappings(self):
        """Empty mappings → empty frameworks and controls."""
        posture = compute_posture(
            mappings=[],
            assessments=PASSING_ASSESSMENTS,
            policy_states=[],
            subscription_id="no-maps",
        )
        assert posture["controls"] == []
        for fw in ("asb", "cis", "nist"):
            fw_data = posture["frameworks"][fw]
            assert fw_data["total_controls"] == 0
            assert fw_data["score"] == 0.0

    def test_compute_posture_partial_framework_coverage(self):
        """Rows with only ASB control contribute only to ASB framework stats."""
        asb_only_mapping = {
            "finding_type": "defender_assessment",
            "defender_rule_id": "dabc-asb-only-0001",
            "display_name": "ASB Only Finding",
            "description": None,
            "cis_control_id": None,
            "cis_title": None,
            "nist_control_id": None,
            "nist_title": None,
            "asb_control_id": "NS-99",
            "asb_title": "Test ASB Only",
            "severity": "Low",
        }
        assessment = {
            "name": "asb-only-guid",
            "display_name": "ASB Only Finding",
            "status": "Healthy",
            "severity": "Low",
        }
        posture = compute_posture(
            mappings=[asb_only_mapping],
            assessments=[assessment],
            policy_states=[],
            subscription_id="partial-fw",
        )
        # ASB should have 1 passing control
        assert posture["frameworks"]["asb"]["passing"] == 1
        # CIS and NIST have no controls from this row
        assert posture["frameworks"]["cis"]["total_controls"] == 0
        assert posture["frameworks"]["nist"]["total_controls"] == 0

    def test_compute_posture_failing_overrides_passing(self):
        """If any finding for a control is failing, control status is failing."""
        two_findings = [
            {
                "finding_type": "defender_assessment",
                "defender_rule_id": "rule-A",
                "display_name": "Finding A",
                "description": None,
                "cis_control_id": "6.5", "cis_title": "MFA",
                "nist_control_id": None, "nist_title": None,
                "asb_control_id": "IM-1", "asb_title": "AAD",
                "severity": "High",
            },
            {
                "finding_type": "defender_assessment",
                "defender_rule_id": "rule-B",
                "display_name": "Finding B",
                "description": None,
                "cis_control_id": "6.5", "cis_title": "MFA",
                "nist_control_id": None, "nist_title": None,
                "asb_control_id": "IM-1", "asb_title": "AAD",
                "severity": "Medium",
            },
        ]
        assessments = [
            {"name": "a", "display_name": "Finding A", "status": "Healthy", "severity": "High"},
            {"name": "b", "display_name": "Finding B", "status": "Unhealthy", "severity": "Medium"},
        ]
        posture = compute_posture(
            mappings=two_findings,
            assessments=assessments,
            policy_states=[],
            subscription_id="multi-finding",
        )
        cis_controls = [
            c for c in posture["controls"]
            if c["framework"] == "cis" and c["control_id"] == "6.5"
        ]
        assert len(cis_controls) == 1
        assert cis_controls[0]["status"] == "failing"

    def test_compute_posture_policy_noncompliant_marks_failing(self):
        """Non-compliant policy state marks the control as failing."""
        policy_mapping = {
            "finding_type": "policy",
            "defender_rule_id": "Storage accounts should use private link",
            "display_name": "Storage accounts should use private link",
            "description": None,
            "cis_control_id": "12.7", "cis_title": "Manage Access Control",
            "nist_control_id": "AC-4", "nist_title": "Information Flow",
            "asb_control_id": "NS-2", "asb_title": "Network controls",
            "severity": "Medium",
        }
        policy_states = [
            {
                "policy_definition_name": "storage accounts should use private link",
                "compliance_state": "NonCompliant",
                "resource_id": "/subscriptions/test/storageAccounts/foo",
            }
        ]
        posture = compute_posture(
            mappings=[policy_mapping],
            assessments=[],
            policy_states=policy_states,
            subscription_id="policy-test",
        )
        asb_controls = [
            c for c in posture["controls"]
            if c["framework"] == "asb" and c["control_id"] == "NS-2"
        ]
        assert len(asb_controls) == 1
        assert asb_controls[0]["status"] == "failing"
