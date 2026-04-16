"""Tests for CVEService — mocks MSRC API and Azure SDK."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.cve_service import (
    CVERecord,
    CVEService,
    _extract_kbs_from_patches,
    _normalise_kb,
    _severity_from_cvss,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_CREDENTIAL = MagicMock()

INSTALLED_PATCHES_WITH_KB = [
    {"SoftwareName": "Update for KB5034441", "SoftwareType": "Update", "CurrentVersion": "1.0"},
]

PENDING_PATCHES_WITH_KB = [
    {"patchName": "Security Update KB5035853", "kbid": "5035853"},
]

UNPATCHED_CVE_ONLY = [
    # no installed or pending patches → unpatched
]

# MSRC returns: KB5034441 → CVE-2024-1111, KB5035853 → CVE-2024-2222
MSRC_MAP_INSTALLED = {"KB5034441": ["CVE-2024-1111"]}
MSRC_MAP_PENDING = {"KB5035853": ["CVE-2024-2222"]}
MSRC_MAP_BOTH = {**MSRC_MAP_INSTALLED, **MSRC_MAP_PENDING}


def make_service() -> CVEService:
    return CVEService(MOCK_CREDENTIAL)


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_normalise_kb_with_prefix(self):
        assert _normalise_kb("KB5034441") == "5034441"

    def test_normalise_kb_digits_only(self):
        assert _normalise_kb("5034441") == "5034441"

    def test_severity_from_cvss_critical(self):
        assert _severity_from_cvss(9.5) == "CRITICAL"

    def test_severity_from_cvss_high(self):
        assert _severity_from_cvss(7.5) == "HIGH"

    def test_severity_from_cvss_medium(self):
        assert _severity_from_cvss(5.0) == "MEDIUM"

    def test_severity_from_cvss_low(self):
        assert _severity_from_cvss(2.0) == "LOW"

    def test_severity_from_cvss_none_defaults_medium(self):
        assert _severity_from_cvss(None) == "MEDIUM"

    def test_extract_kbs_from_patches_kbid_field(self):
        patches = [{"patchName": "Some Update", "kbid": "5034441"}]
        result = _extract_kbs_from_patches(patches)
        assert "5034441" in result

    def test_extract_kbs_from_patches_name_field(self):
        patches = [{"SoftwareName": "Update KB5034441", "SoftwareType": "Update"}]
        result = _extract_kbs_from_patches(patches)
        assert "5034441" in result


class TestCVEStatusCorrelation:
    """Tests for PATCHED / PENDING_PATCH / UNPATCHED logic.

    New architecture (OS-version-based):
      Step 1: _fetch_vm_os_version(credential, vm_name, subscription_id) → "Windows Server 2016"
      Step 2: get_cves_for_product(os_version) → list of dicts with cve_id, kb_ids, ...
      Step 3: fetch installed + pending KBs (best-effort)
      Step 4: cross-reference KB digits → PATCHED / PENDING_PATCH / UNPATCHED
    """

    # Shared MSRC product CVE records for tests
    MSRC_PRODUCT_RECORDS_INSTALLED = [
        {
            "cve_id": "CVE-2024-1111",
            "cvss_score": 7.5,
            "severity": "High",
            "description": "Remote code execution",
            "kb_ids": ["5034441"],
            "published_date": "2024-01-09",
            "affected_product": "Windows Server 2016",
            "affected_versions": "Windows Server 2016",
            "vector_string": "CVSS:3.1/AV:N",
            "impact": "Remote Code Execution",
        }
    ]

    MSRC_PRODUCT_RECORDS_PENDING = [
        {
            "cve_id": "CVE-2024-2222",
            "cvss_score": 8.0,
            "severity": "High",
            "description": "Elevation of privilege",
            "kb_ids": ["5035853"],
            "published_date": "2024-02-13",
            "affected_product": "Windows Server 2016",
            "affected_versions": "Windows Server 2016",
            "vector_string": "",
            "impact": "Elevation of Privilege",
        }
    ]

    @pytest.mark.asyncio
    async def test_cve_status_patched_when_kb_installed(self):
        """CVE is PATCHED when its KB is in installed patches."""
        svc = make_service()
        with (
            patch("services.api_gateway.cve_service._fetch_vm_os_version", return_value="Windows Server 2016"),
            patch("services.api_gateway.msrc_client.get_cves_for_product", new=AsyncMock(return_value=self.MSRC_PRODUCT_RECORDS_INSTALLED)),
            patch("services.api_gateway.cve_service._fetch_pending_patches_arg", return_value=[]),
            patch.object(svc, "_fetch_installed_patches", new=AsyncMock(return_value=INSTALLED_PATCHES_WITH_KB)),
        ):
            records = await svc._fetch_and_correlate(
                "vm1", "sub-1", "rg-1",
                "/subscriptions/sub-1/resourcegroups/rg-1/vm/vm1"
            )
        assert any(r.cve_id == "CVE-2024-1111" and r.status == "PATCHED" for r in records)

    @pytest.mark.asyncio
    async def test_cve_status_pending_when_kb_in_pending_patches(self):
        """CVE is PENDING_PATCH when its KB is only in pending patches (not installed)."""
        svc = make_service()
        with (
            patch("services.api_gateway.cve_service._fetch_vm_os_version", return_value="Windows Server 2016"),
            patch("services.api_gateway.msrc_client.get_cves_for_product", new=AsyncMock(return_value=self.MSRC_PRODUCT_RECORDS_PENDING)),
            patch("services.api_gateway.cve_service._fetch_pending_patches_arg", return_value=PENDING_PATCHES_WITH_KB),
            patch.object(svc, "_fetch_installed_patches", new=AsyncMock(return_value=[])),
        ):
            records = await svc._fetch_and_correlate(
                "vm1", "sub-1", "rg-1",
                "/subscriptions/sub-1/resourcegroups/rg-1/vm/vm1"
            )
        assert any(r.cve_id == "CVE-2024-2222" and r.status == "PENDING_PATCH" for r in records)

    @pytest.mark.asyncio
    async def test_cve_status_unpatched_when_no_kb_match(self):
        """CVE is UNPATCHED when KB is known but not in installed or pending patches."""
        svc = make_service()
        msrc_records = [
            {
                "cve_id": "CVE-2024-9999",
                "cvss_score": 6.0,
                "severity": "Medium",
                "description": "Spoofing",
                "kb_ids": ["9999999"],
                "published_date": "2024-03-12",
                "affected_product": "Windows Server 2016",
                "affected_versions": "Windows Server 2016",
                "vector_string": "",
                "impact": "Spoofing",
            }
        ]
        with (
            patch("services.api_gateway.cve_service._fetch_vm_os_version", return_value="Windows Server 2016"),
            patch("services.api_gateway.msrc_client.get_cves_for_product", new=AsyncMock(return_value=msrc_records)),
            patch("services.api_gateway.cve_service._fetch_pending_patches_arg", return_value=[]),
            patch.object(svc, "_fetch_installed_patches", new=AsyncMock(return_value=[])),
        ):
            records = await svc._fetch_and_correlate(
                "vm1", "sub-1", "rg-1",
                "/subscriptions/sub-1/resourcegroups/rg-1/vm/vm1"
            )
        assert any(r.cve_id == "CVE-2024-9999" and r.status == "UNPATCHED" for r in records)

    @pytest.mark.asyncio
    async def test_cve_stats_counts_correctly(self):
        """get_cve_stats returns correct bucketed counts."""
        svc = make_service()
        records = [
            CVERecord("CVE-A", "desc", "CRITICAL", 9.5, "Win", "all", None, ["KB1"], True, False, "PATCHED"),
            CVERecord("CVE-B", "desc", "HIGH",     7.0, "Win", "all", None, ["KB2"], False, True, "PENDING_PATCH"),
            CVERecord("CVE-C", "desc", "MEDIUM",   5.0, "Win", "all", None, [],     False, False, "UNPATCHED"),
            CVERecord("CVE-D", "desc", "LOW",      2.0, "Win", "all", None, [],     False, False, "UNPATCHED"),
        ]
        with patch.object(svc, "get_cves_for_vm", new=AsyncMock(return_value=records)):
            stats = await svc.get_cve_stats("vm1", "sub-1", "rg-1")

        assert stats["total"] == 4
        assert stats["critical"] == 1
        assert stats["high"] == 1
        assert stats["medium"] == 1
        assert stats["low"] == 1
        assert stats["patched_count"] == 1
        assert stats["pending_count"] == 1
        assert stats["unpatched_count"] == 2

    @pytest.mark.asyncio
    async def test_cve_cache_returns_cached_data(self):
        """get_cves_for_vm returns cached data without hitting MSRC."""
        svc = make_service()
        cached_records = [
            asdict(CVERecord("CVE-CACHED", "d", "HIGH", 7.0, "Win", "all", None, ["KB1"], True, False, "PATCHED"))
        ]
        with patch("services.api_gateway.cve_service._load_from_cache", new=AsyncMock(return_value=cached_records)):
            with patch.object(svc, "_fetch_and_correlate", new=AsyncMock()) as mock_fetch:
                result = await svc.get_cves_for_vm("vm1", "sub-1", "rg-1")

        # _fetch_and_correlate should NOT have been called
        mock_fetch.assert_not_called()
        assert len(result) == 1
        assert result[0].cve_id == "CVE-CACHED"

    @pytest.mark.asyncio
    async def test_cve_severity_ordering(self):
        """CVEs returned by _fetch_and_correlate are sorted UNPATCHED first."""
        svc = make_service()
        # MSRC returns two CVEs: one whose KB is pending, one whose KB is installed
        msrc_records = [
            {
                "cve_id": "CVE-PEND",
                "cvss_score": 7.0,
                "severity": "High",
                "description": "desc",
                "kb_ids": ["1111"],
                "published_date": "2024-01-09",
                "affected_product": "Windows Server 2016",
                "affected_versions": "Windows Server 2016",
                "vector_string": "",
                "impact": "Elevation of Privilege",
            },
            {
                "cve_id": "CVE-PATCHED",
                "cvss_score": 6.0,
                "severity": "Medium",
                "description": "desc",
                "kb_ids": ["2222"],
                "published_date": "2024-01-09",
                "affected_product": "Windows Server 2016",
                "affected_versions": "Windows Server 2016",
                "vector_string": "",
                "impact": "Information Disclosure",
            },
        ]
        pending = [{"patchName": "Update KB1111", "kbid": "1111"}]
        installed = [{"SoftwareName": "Update KB2222", "SoftwareType": "Update"}]

        with (
            patch("services.api_gateway.cve_service._fetch_vm_os_version", return_value="Windows Server 2016"),
            patch("services.api_gateway.msrc_client.get_cves_for_product", new=AsyncMock(return_value=msrc_records)),
            patch("services.api_gateway.cve_service._fetch_pending_patches_arg", return_value=pending),
            patch.object(svc, "_fetch_installed_patches", new=AsyncMock(return_value=installed)),
        ):
            records = await svc._fetch_and_correlate(
                "vm1", "sub-1", "rg-1",
                "/subscriptions/sub-1/resourcegroups/rg-1/vm/vm1"
            )

        # PATCHED (from installed KB2222) comes last; PENDING_PATCH comes before PATCHED
        patched_idx = next(i for i, r in enumerate(records) if r.cve_id == "CVE-PATCHED")
        pending_idx = next(i for i, r in enumerate(records) if r.cve_id == "CVE-PEND")
        assert pending_idx < patched_idx, "PENDING_PATCH should appear before PATCHED"


class TestCVEEndpoints:
    """Basic endpoint smoke tests via FastAPI TestClient."""

    @pytest.mark.asyncio
    async def test_cves_endpoint_returns_list(self):
        """GET /api/v1/vms/{vm_name}/cves returns cves list."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from services.api_gateway.cve_endpoints import router
        from services.api_gateway.auth import verify_token
        from services.api_gateway.dependencies import get_credential

        app = FastAPI()
        app.include_router(router)

        records = [
            CVERecord("CVE-2024-1111", "desc", "HIGH", 7.5, "Win", "all", None, ["KB1"], True, False, "PATCHED")
        ]

        app.dependency_overrides[verify_token] = lambda: {}
        app.dependency_overrides[get_credential] = lambda: MOCK_CREDENTIAL

        with patch("services.api_gateway.cve_service.CVEService.get_cves_for_vm", new=AsyncMock(return_value=records)):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/vms/vm1/cves",
                params={"subscription_id": "sub-1", "resource_group": "rg-1"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "cves" in body
        assert body["total_count"] == 1
        assert body["vm_name"] == "vm1"
