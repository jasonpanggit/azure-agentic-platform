import os
"""Unit tests for the Patch Management API gateway endpoints.

Tests GET /api/v1/patch/assessment, GET /api/v1/patch/installations,
and GET /api/v1/patch/installed with mocked Azure Resource Graph client
and Log Analytics workspace. Follows existing api-gateway test patterns
(conftest.py client fixture, mock credentials).

Task: 13-01-02
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ASSESSMENT_DATA = [
    {
        "id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01",
        "machineName": "vm-prod-01",
        "resourceGroup": "rg-1",
        "subscriptionId": "sub-1",
        "osType": "Windows",
        "osVersion": "Windows Server 2022 Datacenter",
        "hasAssessmentData": True,
        "rebootPending": True,
        "lastAssessment": "2026-03-31T10:00:00Z",
        "criticalCount": 2,
        "securityCount": 5,
        "updateRollupCount": 1,
        "featurePackCount": 0,
        "servicePackCount": 0,
        "definitionCount": 3,
        "toolsCount": 0,
        "updatesCount": 1,
    },
    {
        "id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.HybridCompute/machines/arc-srv-01",
        "machineName": "arc-srv-01",
        "resourceGroup": "rg-1",
        "subscriptionId": "sub-1",
        "osType": "Linux",
        "osVersion": "Ubuntu 22.04 LTS",
        "hasAssessmentData": True,
        "rebootPending": False,
        "lastAssessment": "2026-03-31T09:30:00Z",
        "criticalCount": 0,
        "securityCount": 0,
        "updateRollupCount": 0,
        "featurePackCount": 0,
        "servicePackCount": 0,
        "definitionCount": 0,
        "toolsCount": 0,
        "updatesCount": 0,
    },
    {
        "id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-dev-01",
        "machineName": "vm-dev-01",
        "resourceGroup": "rg-1",
        "subscriptionId": "sub-1",
        "osType": "Linux",
        "osVersion": "Ubuntu 24.04 LTS",
        "hasAssessmentData": False,
        "rebootPending": False,
        "lastAssessment": None,
        "criticalCount": 0,
        "securityCount": 0,
        "updateRollupCount": 0,
        "featurePackCount": 0,
        "servicePackCount": 0,
        "definitionCount": 0,
        "toolsCount": 0,
        "updatesCount": 0,
    },
]

SAMPLE_INSTALLATION_DATA = [
    {
        "id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01/patchInstallationResults/run-001",
        "resourceGroup": "rg-1",
        "subscriptionId": "sub-1",
        "startTime": "2026-03-30T02:00:00Z",
        "status": "Succeeded",
        "rebootStatus": "NotNeeded",
        "installedCount": 12,
        "failedCount": 0,
        "pendingCount": 0,
        "startedBy": "Platform",
    },
    {
        "id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01/patchInstallationResults/run-002",
        "resourceGroup": "rg-1",
        "subscriptionId": "sub-1",
        "startTime": "2026-03-28T02:00:00Z",
        "status": "Failed",
        "rebootStatus": "Required",
        "installedCount": 5,
        "failedCount": 3,
        "pendingCount": 1,
        "startedBy": "User",
    },
]


def _mock_arg_response(data, skip_token=None):
    """Create a mock ARG response object."""
    resp = MagicMock()
    resp.data = data
    resp.skip_token = skip_token
    return resp


# ---------------------------------------------------------------------------
# Assessment endpoint tests
# ---------------------------------------------------------------------------


class TestGetPatchAssessment:
    """Tests for GET /api/v1/patch/assessment."""

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_503_when_sdk_not_installed(self, mock_query, mock_law, client):
        """If azure-mgmt-resourcegraph is not importable, return 503."""
        mock_query.side_effect = ImportError("No module named 'azure.mgmt.resourcegraph'")

        resp = client.get("/api/v1/patch/assessment?subscriptions=sub-1")
        assert resp.status_code == 503
        assert "not available" in resp.json()["detail"].lower()

    def test_returns_400_when_subscriptions_missing(self, client):
        """Missing subscriptions param returns 400."""
        resp = client.get("/api/v1/patch/assessment?subscriptions=")
        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()

    def test_returns_400_when_no_subscriptions_param_and_no_registry(self, client):
        """No subscriptions param and no registry configured returns 400.

        Previously this returned 422 (FastAPI required param validation).
        After federation: subscriptions is Optional — endpoint returns 400
        when param is absent AND registry has no subscriptions.
        """
        resp = client.get("/api/v1/patch/assessment")
        # 400 because registry is empty (no SUBSCRIPTION_IDS in test env)
        # 422 would mean the param is still required (regression)
        assert resp.status_code in (400, 422)

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_assessment_data(self, mock_query, mock_law, client):
        """Successful response returns machines array and total_count."""
        mock_query.return_value = [dict(m) for m in SAMPLE_ASSESSMENT_DATA]

        resp = client.get("/api/v1/patch/assessment?subscriptions=sub-1")
        assert resp.status_code == 200

        body = resp.json()
        assert body["query_status"] == "success"
        assert body["total_count"] == 3
        assert len(body["machines"]) == 3

        # Verify first machine fields (assessed Azure VM)
        m0 = body["machines"][0]
        assert m0["machineName"] == "vm-prod-01"
        assert m0["osType"] == "Windows"
        assert m0["osVersion"] == "Windows Server 2022 Datacenter"
        assert m0["hasAssessmentData"] is True
        assert m0["rebootPending"] is True
        assert m0["criticalCount"] == 2
        assert m0["securityCount"] == 5

        # Verify second machine (Arc) fields
        m1 = body["machines"][1]
        assert m1["machineName"] == "arc-srv-01"
        assert m1["osType"] == "Linux"
        assert m1["osVersion"] == "Ubuntu 22.04 LTS"
        assert m1["hasAssessmentData"] is True

        # Verify third machine (unassessed VM)
        m2 = body["machines"][2]
        assert m2["machineName"] == "vm-dev-01"
        assert m2["hasAssessmentData"] is False
        assert m2["rebootPending"] is False
        assert m2["lastAssessment"] is None
        assert m2["criticalCount"] == 0
        assert m2["securityCount"] == 0

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_empty_when_no_machines(self, mock_query, mock_law, client):
        """Empty result returns zero-count response."""
        mock_query.return_value = []

        resp = client.get("/api/v1/patch/assessment?subscriptions=sub-1")
        assert resp.status_code == 200

        body = resp.json()
        assert body["total_count"] == 0
        assert body["machines"] == []

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_unassessed_machines_have_zeroed_patch_counts(self, mock_query, mock_law, client):
        """Machines with no AUM assessment data have all counts zeroed and null lastAssessment."""
        unassessed_only = [
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-new-01",
                "machineName": "vm-new-01",
                "resourceGroup": "rg-1",
                "subscriptionId": "sub-1",
                "osType": "Windows",
                "osVersion": "Windows Server 2025",
                "hasAssessmentData": False,
                "rebootPending": False,
                "lastAssessment": None,
                "criticalCount": 0,
                "securityCount": 0,
                "updateRollupCount": 0,
                "featurePackCount": 0,
                "servicePackCount": 0,
                "definitionCount": 0,
                "toolsCount": 0,
                "updatesCount": 0,
            },
        ]
        mock_query.return_value = unassessed_only

        resp = client.get("/api/v1/patch/assessment?subscriptions=sub-1")
        assert resp.status_code == 200

        body = resp.json()
        assert body["total_count"] == 1
        m = body["machines"][0]
        assert m["machineName"] == "vm-new-01"
        assert m["hasAssessmentData"] is False
        assert m["rebootPending"] is False
        assert m["lastAssessment"] is None
        assert m["criticalCount"] == 0
        assert m["securityCount"] == 0
        assert m["updateRollupCount"] == 0

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_splits_comma_subscriptions(self, mock_query, mock_law, client):
        """Comma-separated subscriptions are passed as a list."""
        mock_query.return_value = []

        client.get("/api/v1/patch/assessment?subscriptions=sub-1,sub-2,sub-3")

        call_args = mock_query.call_args
        sub_ids = call_args[0][1]  # second positional arg
        assert sub_ids == ["sub-1", "sub-2", "sub-3"]

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_kql_starts_from_resources_table(self, mock_query, mock_law, client):
        """KQL query uses resources as source of truth, not patchassessmentresources."""
        mock_query.return_value = []

        client.get("/api/v1/patch/assessment?subscriptions=sub-1")

        call_args = mock_query.call_args
        kql = call_args[0][2]  # third positional arg (KQL string)
        # Query must start from resources table
        assert kql.startswith("resources\n"), "KQL must start from resources table"
        # Must left-join patchassessmentresources
        assert "join kind=leftouter" in kql
        assert "patchassessmentresources" in kql
        # Must project hasAssessmentData
        assert "hasAssessmentData" in kql

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_kql_uses_case_insensitive_split_for_arc_vm_join(self, mock_query, mock_law, client):
        """KQL split() must lower id before splitting so Arc VM lowercase ids join correctly.

        Arc VMs return ids with lowercase '/patchassessmentresults/' while Azure VMs use
        camelCase '/patchAssessmentResults/'. The fix is to tolower(id) before split so
        both variants match 'machineIdLower' on the resources side of the left join.

        Regression test for: split(id, '/patchAssessmentResults/') → case-sensitive miss on Arc VMs
        Correct form:        split(tolower(id), '/patchassessmentresults/')
        """
        mock_query.return_value = []

        client.get("/api/v1/patch/assessment?subscriptions=sub-1")

        call_args = mock_query.call_args
        kql = call_args[0][2]  # third positional arg (KQL string)

        # The patchMachineId derivation MUST lower the id before splitting to handle
        # Arc VMs that return lowercase segment names from ARG.
        assert "split(tolower(id), '/patchassessmentresults/')" in kql, (
            "KQL must use tolower(id) before split() with a lowercase delimiter "
            "to correctly join Arc VM patchassessmentresources rows. "
            "Using split(id, '/patchAssessmentResults/') silently misses Arc VMs "
            "because KQL split() is case-sensitive."
        )

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock, return_value={})
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_502_on_arg_failure(self, mock_query, mock_law, client):
        """ARG query failure returns 502."""
        mock_query.side_effect = Exception("ARG timeout")

        resp = client.get("/api/v1/patch/assessment?subscriptions=sub-1")
        assert resp.status_code == 502
        assert "ARG query failed" in resp.json()["detail"]

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock)
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_assessment_includes_law_enrichment(self, mock_query, mock_law, client):
        """Assessment response includes installedCount and lastInstalled from LAW."""
        mock_query.return_value = [dict(m) for m in SAMPLE_ASSESSMENT_DATA]
        mock_law.return_value = {
            "/subscriptions/sub-1/resourcegroups/rg-1/providers/microsoft.compute/virtualmachines/vm-prod-01": {
                "installedCount": 42,
                "lastInstalled": "2026-03-30T12:00:00Z",
            },
        }

        resp = client.get("/api/v1/patch/assessment?subscriptions=sub-1")
        assert resp.status_code == 200

        body = resp.json()
        m0 = body["machines"][0]
        assert m0["installedCount"] == 42
        assert m0["lastInstalled"] == "2026-03-30T12:00:00Z"

        # Machine without LAW data gets defaults
        m1 = body["machines"][1]
        assert m1["installedCount"] == 0
        assert m1["lastInstalled"] is None

    @patch("services.api_gateway.patch_endpoints._query_law_installed_summary", new_callable=AsyncMock)
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_assessment_graceful_degradation_when_law_fails(self, mock_query, mock_law, client):
        """Assessment still returns data when LAW enrichment fails."""
        mock_query.return_value = [dict(m) for m in SAMPLE_ASSESSMENT_DATA]
        mock_law.return_value = {}  # LAW failure returns empty dict

        resp = client.get("/api/v1/patch/assessment?subscriptions=sub-1")
        assert resp.status_code == 200

        body = resp.json()
        assert body["total_count"] == 3
        # All machines get default LAW values
        for m in body["machines"]:
            assert m["installedCount"] == 0
            assert m["lastInstalled"] is None


# ---------------------------------------------------------------------------
# Installation endpoint tests
# ---------------------------------------------------------------------------


class TestGetPatchInstallations:
    """Tests for GET /api/v1/patch/installations."""

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_503_when_sdk_not_installed(self, mock_query, client):
        """If azure-mgmt-resourcegraph is not importable, return 503."""
        mock_query.side_effect = ImportError("No module named 'azure.mgmt.resourcegraph'")

        resp = client.get("/api/v1/patch/installations?subscriptions=sub-1")
        assert resp.status_code == 503

    def test_returns_400_when_subscriptions_empty(self, client):
        """Empty subscriptions param returns 400."""
        resp = client.get("/api/v1/patch/installations?subscriptions=")
        assert resp.status_code == 400

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_installation_data(self, mock_query, client):
        """Successful response returns installations array, total_count, days."""
        mock_query.return_value = SAMPLE_INSTALLATION_DATA

        resp = client.get("/api/v1/patch/installations?subscriptions=sub-1")
        assert resp.status_code == 200

        body = resp.json()
        assert body["query_status"] == "success"
        assert body["total_count"] == 2
        assert body["days"] == 7
        assert len(body["installations"]) == 2

        # Verify first installation fields
        i0 = body["installations"][0]
        assert i0["status"] == "Succeeded"
        assert i0["installedCount"] == 12
        assert i0["failedCount"] == 0

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_custom_days_parameter(self, mock_query, client):
        """Custom days parameter is reflected in response."""
        mock_query.return_value = []

        resp = client.get("/api/v1/patch/installations?subscriptions=sub-1&days=14")
        assert resp.status_code == 200
        assert resp.json()["days"] == 14

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_502_on_arg_failure(self, mock_query, client):
        """ARG query failure returns 502."""
        mock_query.side_effect = Exception("Connection timeout")

        resp = client.get("/api/v1/patch/installations?subscriptions=sub-1")
        assert resp.status_code == 502
        assert "ARG query failed" in resp.json()["detail"]

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_empty_when_no_installations(self, mock_query, client):
        """Empty result returns zero-count response."""
        mock_query.return_value = []

        resp = client.get("/api/v1/patch/installations?subscriptions=sub-1")
        assert resp.status_code == 200

        body = resp.json()
        assert body["total_count"] == 0
        assert body["installations"] == []


# ---------------------------------------------------------------------------
# Installed patches endpoint tests
# ---------------------------------------------------------------------------


class TestGetInstalledPatches:
    """Tests for GET /api/v1/patch/installed."""

    def test_returns_empty_patches_when_workspace_not_configured(self, client):
        """Gracefully degrades with empty patches when LOG_ANALYTICS_WORKSPACE_ID is not set.

        Matches the assessment endpoint's graceful degradation pattern —
        missing LAW config should never block the UI from opening.
        """
        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"
        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": ""}, clear=False):
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["patches"] == []
            assert body["total_count"] == 0
            assert body["resource_id"] == resource_id
            assert body["query_status"] == "degraded"

    def test_returns_422_when_resource_id_missing(self, client):
        """Missing resource_id returns 422."""
        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "ws-123"}, clear=False):
            resp = client.get("/api/v1/patch/installed")
            assert resp.status_code == 422

    @patch("services.api_gateway.patch_endpoints._discover_change_tracking_workspace", return_value="ws-123")
    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    def test_returns_installed_patches(self, mock_detail, mock_discover, client):
        """Successful response returns patches array and metadata."""
        mock_detail.return_value = [
            {
                "SoftwareName": "KB5034441 - Security Update",
                "SoftwareType": "Hotfix",
                "CurrentVersion": "1.0.0",
                "Publisher": "Microsoft",
                "Category": "Security",
                "InstalledDate": "2026-03-30T02:00:00Z",
            },
            {
                "SoftwareName": "nginx",
                "SoftwareType": "Package",
                "CurrentVersion": "1.24.0",
                "Publisher": "Ubuntu",
                "Category": None,
                "InstalledDate": "2026-03-29T12:00:00Z",
            },
        ]

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.return_value = {"KB5034441": ["CVE-2024-21302"]}
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}&days=30")

        assert resp.status_code == 200

        body = resp.json()
        assert body["total_count"] == 2
        assert body["resource_id"] == resource_id
        assert body["days"] == 30

        # First patch (Hotfix) should have CVEs enriched
        p0 = body["patches"][0]
        assert p0["SoftwareName"] == "KB5034441 - Security Update"
        assert p0["cves"] == ["CVE-2024-21302"]

        # Second patch (Package) should have empty CVEs
        p1 = body["patches"][1]
        assert p1["cves"] == []

    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    def test_installed_empty_when_no_patches(self, mock_detail, client):
        """Returns empty list when LAW has no patch data."""
        mock_detail.return_value = []

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "ws-123"}, clear=False):
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 0
        assert body["patches"] == []
        assert body["days"] == 90  # default

    @patch("services.api_gateway.patch_endpoints._discover_change_tracking_workspace", return_value="ws-123")
    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    def test_installed_cve_enrichment_graceful_degradation(self, mock_detail, mock_discover, client):
        """CVE enrichment failure still returns patches with empty cves."""
        mock_detail.return_value = [
            {
                "SoftwareName": "KB5034441 - Security Update",
                "SoftwareType": "Hotfix",
                "CurrentVersion": "1.0.0",
                "Publisher": "Microsoft",
                "Category": "Security",
                "InstalledDate": "2026-03-30T02:00:00Z",
            },
        ]

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.side_effect = Exception("MSRC API down")
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        # CVE enrichment failed but patch data is still returned
        assert body["patches"][0]["cves"] == []

    @patch("services.api_gateway.patch_endpoints._discover_change_tracking_workspace", return_value="ws-123")
    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    def test_installed_cve_enrichment_for_patch_type(self, mock_detail, mock_discover, client):
        """SoftwareType=='Patch' patches are now enriched with CVEs (not just Hotfix).

        Regression test: previously only SoftwareType=='Hotfix' triggered MSRC lookup.
        Arc VMs and Azure Update Manager use SoftwareType=='Patch' or 'Update', so
        those patches always showed empty CVEs.
        """
        mock_detail.return_value = [
            {
                "SoftwareName": "Security Update KB5034441",
                "SoftwareType": "Patch",
                "CurrentVersion": "1.0.0",
                "Publisher": "Microsoft",
                "Category": "Patch",
                "InstalledDate": "2026-03-30T02:00:00Z",
            },
            {
                "SoftwareName": "Windows Update KB5035853",
                "SoftwareType": "Update",
                "CurrentVersion": "1.0.0",
                "Publisher": "Microsoft",
                "Category": "Update",
                "InstalledDate": "2026-03-29T02:00:00Z",
            },
            {
                "SoftwareName": "nginx",
                "SoftwareType": "Package",
                "CurrentVersion": "1.24.0",
                "Publisher": "Ubuntu",
                "Category": "Package",
                "InstalledDate": "2026-03-28T12:00:00Z",
            },
        ]

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.return_value = {
                "KB5034441": ["CVE-2024-21302"],
                "KB5035853": ["CVE-2024-26234", "CVE-2024-26218"],
            }
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 3

        # SoftwareType=='Patch' must be enriched
        p0 = body["patches"][0]
        assert p0["SoftwareType"] == "Patch"
        assert p0["cves"] == ["CVE-2024-21302"]

        # SoftwareType=='Update' must be enriched
        p1 = body["patches"][1]
        assert p1["SoftwareType"] == "Update"
        assert p1["cves"] == ["CVE-2024-26234", "CVE-2024-26218"]

        # SoftwareType=='Package' must NOT be enriched
        p2 = body["patches"][2]
        assert p2["SoftwareType"] == "Package"
        assert p2["cves"] == []

    @patch("services.api_gateway.patch_endpoints._discover_change_tracking_workspace", return_value="ws-123")
    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    def test_installed_cve_uses_kbid_field_directly(self, mock_detail, mock_discover, client):
        """KB ID is extracted from the kbid field when present, not just from SoftwareName.

        Regression test: previously only searched SoftwareName for KB\\d+ pattern,
        missing patches that have kbid as a separate field.
        """
        mock_detail.return_value = [
            {
                "SoftwareName": "2026-03 Cumulative Update for Windows",
                "SoftwareType": "Update",
                "kbid": "5034441",  # numeric kbid field, no KB prefix
                "CurrentVersion": "1.0.0",
                "Publisher": "Microsoft",
                "Category": "Update",
                "InstalledDate": "2026-03-30T02:00:00Z",
            },
        ]

        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.return_value = {"KB5034441": ["CVE-2024-21302"]}
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["patches"][0]["cves"] == ["CVE-2024-21302"]


        """Days parameter must be between 1 and 365."""
        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "ws-123"}, clear=False):
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}&days=0")
            assert resp.status_code == 422

            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}&days=400")
            assert resp.status_code == 422


class TestDiscoverChangeTrackingWorkspace:
    """Tests for _discover_change_tracking_workspace workspace discovery helper."""

    ARC_RESOURCE_ID = (
        "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9"
        "/resourceGroups/agentic-aiops-demo-rg"
        "/providers/Microsoft.HybridCompute/machines/WIN-JBC7MM2NO8J"
    )
    # Realistic: ARM path ends with workspace NAME, not a GUID.
    # This matches real Azure environments (e.g. ChangeTracking(workspace-agentic-aiops-demo)).
    WORKSPACE_ARM_ID = (
        "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9"
        "/resourceGroups/ct-rg"
        "/providers/Microsoft.OperationalInsights/workspaces"
        "/my-change-tracking-workspace"
    )
    WORKSPACE_GUID = "aabbccdd-1122-3344-5566-778899aabbcc"

    def setup_method(self):
        """Clear the module-level workspace cache before each test."""
        from services.api_gateway import patch_endpoints
        patch_endpoints._workspace_cache.clear()

    @patch("services.api_gateway.patch_endpoints._get_workspace_customer_id")
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_discovered_workspace_guid(self, mock_arg, mock_customer_id):
        """Returns the customerId GUID from the ChangeTracking solution's workspace.

        The ARM resource path ends with a workspace NAME, not a GUID. The helper
        must resolve the customerId via _get_workspace_customer_id.
        """
        mock_arg.return_value = [{"workspaceResourceId": self.WORKSPACE_ARM_ID}]
        mock_customer_id.return_value = self.WORKSPACE_GUID
        credential = MagicMock()

        from services.api_gateway.patch_endpoints import _discover_change_tracking_workspace
        result = _discover_change_tracking_workspace(credential, self.ARC_RESOURCE_ID)

        assert result == self.WORKSPACE_GUID
        mock_arg.assert_called_once()
        mock_customer_id.assert_called_once_with(credential, self.WORKSPACE_ARM_ID)
        # Verify the ARG query scopes to the correct subscription
        call_kql = mock_arg.call_args[0][2]
        assert "ChangeTracking(" in call_kql
        assert "4c727b88-12f4-4c91-9c2b-372aab3bbae9" in call_kql

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_falls_back_to_env_var_when_no_solution_found(self, mock_arg):
        """Falls back to LOG_ANALYTICS_WORKSPACE_ID when no ChangeTracking solution exists."""
        mock_arg.return_value = []
        credential = MagicMock()

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "fallback-ws-guid"}):
            from services.api_gateway.patch_endpoints import _discover_change_tracking_workspace
            result = _discover_change_tracking_workspace(credential, self.ARC_RESOURCE_ID)

        assert result == "fallback-ws-guid"

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_falls_back_to_env_var_on_arg_error(self, mock_arg):
        """Falls back gracefully when ARG raises an exception — never raises itself."""
        mock_arg.side_effect = Exception("ARG service unavailable")
        credential = MagicMock()

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "fallback-ws-guid"}):
            from services.api_gateway.patch_endpoints import _discover_change_tracking_workspace
            result = _discover_change_tracking_workspace(credential, self.ARC_RESOURCE_ID)

        assert result == "fallback-ws-guid"

    @patch("services.api_gateway.patch_endpoints._get_workspace_customer_id")
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_falls_back_to_env_var_when_customer_id_lookup_fails(self, mock_arg, mock_customer_id):
        """Falls back to env var when _get_workspace_customer_id returns empty string."""
        mock_arg.return_value = [{"workspaceResourceId": self.WORKSPACE_ARM_ID}]
        mock_customer_id.return_value = ""  # lookup failed
        credential = MagicMock()

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "fallback-ws-guid"}):
            from services.api_gateway.patch_endpoints import _discover_change_tracking_workspace
            result = _discover_change_tracking_workspace(credential, self.ARC_RESOURCE_ID)

        assert result == "fallback-ws-guid"

    @patch("services.api_gateway.patch_endpoints._get_workspace_customer_id")
    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_caches_result_and_avoids_repeat_arg_call(self, mock_arg, mock_customer_id):
        """Second call for the same subscription hits the cache, not ARG."""
        mock_arg.return_value = [{"workspaceResourceId": self.WORKSPACE_ARM_ID}]
        mock_customer_id.return_value = self.WORKSPACE_GUID
        credential = MagicMock()

        from services.api_gateway.patch_endpoints import _discover_change_tracking_workspace

        # First call — hits ARG + customer_id lookup
        result1 = _discover_change_tracking_workspace(credential, self.ARC_RESOURCE_ID)
        # Second call — same subscription, should use cache
        result2 = _discover_change_tracking_workspace(credential, self.ARC_RESOURCE_ID)

        assert result1 == self.WORKSPACE_GUID
        assert result2 == self.WORKSPACE_GUID
        assert mock_arg.call_count == 1      # ARG called only once
        assert mock_customer_id.call_count == 1  # customer_id lookup only once

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_fallback_for_invalid_resource_id(self, mock_arg):
        """Returns env var fallback without calling ARG when resource_id is malformed."""
        credential = MagicMock()

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "fallback-ws-guid"}):
            from services.api_gateway.patch_endpoints import _discover_change_tracking_workspace
            result = _discover_change_tracking_workspace(credential, "not-a-valid-resource-id")

        assert result == "fallback-ws-guid"
        mock_arg.assert_not_called()

    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    @patch("services.api_gateway.patch_endpoints._discover_change_tracking_workspace")
    def test_get_installed_uses_discovered_workspace(self, mock_discover, mock_detail, client):
        """get_installed_patches uses the discovered workspace, not raw env var."""
        mock_discover.return_value = "discovered-ct-workspace-guid"
        mock_detail.return_value = []

        resource_id = self.ARC_RESOURCE_ID
        resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")

        assert resp.status_code == 200
        # Verify the detail query was called with the discovered workspace, not the env var
        mock_detail.assert_called_once()
        call_workspace = mock_detail.call_args[0][1]  # second positional arg is workspace_id
        assert call_workspace == "discovered-ct-workspace-guid"

    @patch("services.api_gateway.patch_endpoints._discover_change_tracking_workspace")
    def test_get_installed_degrades_when_no_workspace_at_all(self, mock_discover, client):
        """Returns degraded response when both discovery and env var return empty string."""
        mock_discover.return_value = ""

        resource_id = self.ARC_RESOURCE_ID
        resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["patches"] == []
        assert body["total_count"] == 0
        assert body["query_status"] == "degraded"


class TestGetWorkspaceCustomerId:
    """Tests for _get_workspace_customer_id helper."""

    WORKSPACE_ARM_ID = (
        "/subscriptions/4c727b88-12f4-4c91-9c2b-372aab3bbae9"
        "/resourceGroups/agentic-aiops-demo-rg"
        "/providers/Microsoft.OperationalInsights/workspaces"
        "/workspace-agentic-aiops-demo"
    )
    EXPECTED_GUID = "d6e88b39-4f54-4f95-96f1-8acfedf0129c"

    @patch("services.api_gateway.patch_endpoints.LogAnalyticsManagementClient")
    def test_returns_customer_id_from_management_api(self, mock_law_cls):
        """Returns the customerId GUID from the workspace management API response."""
        mock_workspace = MagicMock()
        mock_workspace.customer_id = self.EXPECTED_GUID
        mock_client = MagicMock()
        mock_client.workspaces.get.return_value = mock_workspace
        mock_law_cls.return_value = mock_client

        credential = MagicMock()
        from services.api_gateway.patch_endpoints import _get_workspace_customer_id
        result = _get_workspace_customer_id(credential, self.WORKSPACE_ARM_ID)

        assert result == self.EXPECTED_GUID
        mock_law_cls.assert_called_once_with(
            credential, "4c727b88-12f4-4c91-9c2b-372aab3bbae9"
        )
        mock_client.workspaces.get.assert_called_once_with(
            "agentic-aiops-demo-rg", "workspace-agentic-aiops-demo"
        )

    @patch("services.api_gateway.patch_endpoints.LogAnalyticsManagementClient")
    def test_returns_empty_string_on_exception(self, mock_law_cls):
        """Returns empty string when the management API call fails (never raises)."""
        mock_client = MagicMock()
        mock_client.workspaces.get.side_effect = Exception("API error")
        mock_law_cls.return_value = mock_client

        credential = MagicMock()
        from services.api_gateway.patch_endpoints import _get_workspace_customer_id
        result = _get_workspace_customer_id(credential, self.WORKSPACE_ARM_ID)

        assert result == ""

    def test_returns_empty_string_for_malformed_arm_id(self):
        """Returns empty string without calling SDK when ARM resource ID is malformed."""
        credential = MagicMock()

        from services.api_gateway.patch_endpoints import _get_workspace_customer_id
        result = _get_workspace_customer_id(credential, "not-an-arm-id")

        assert result == ""


class TestKqlSoftwareTypeFilter:
    """Regression tests: KQL SoftwareType filter must include 'Update' for Azure Update Manager patches."""

    def test_installed_detail_kql_includes_update_type(self):
        """The detail query KQL must include SoftwareType 'Update' to capture AUM-installed patches.

        Azure Update Manager records installed patches with SoftwareType == "Update" in the
        ConfigurationData table.  Without this filter, installed patches from AUM are silently
        excluded, causing the Installed Patches tab to appear empty for Arc VMs.

        Regression test for: installed-patches-empty bug (2026-04-07).
        """
        from services.api_gateway.patch_endpoints import _query_law_installed_detail_sync

        import inspect
        source = inspect.getsource(_query_law_installed_detail_sync)

        assert '"Update"' in source, (
            "KQL SoftwareType filter in _query_law_installed_detail_sync must include "
            '"Update" to capture Azure Update Manager installed patches. '
            "Without it, the Installed Patches tab shows empty for Arc VMs."
        )
        assert '"Patch"' in source, (
            "KQL SoftwareType filter in _query_law_installed_detail_sync must include "
            '"Patch" to capture Arc VM Change Tracking installed patches. '
            "Arc VMs report SoftwareType='Patch', not 'Hotfix' or 'Update'."
        )
        assert "SoftwareClassification" not in source, (
            "KQL in _query_law_installed_detail_sync must not reference SoftwareClassification — "
            "this column does not exist in Arc VM Change Tracking ConfigurationData. "
            "Use SoftwareType for Category instead."
        )

    def test_installed_summary_kql_includes_update_type(self):
        """The summary query KQL must include SoftwareType 'Update' and 'Patch'.

        Regression test for: installed-patches-empty bug (2026-04-07).
        Arc VMs use SoftwareType='Patch'; Azure VMs use 'Update'.
        """
        from services.api_gateway.patch_endpoints import _query_law_installed_summary_sync

        import inspect
        source = inspect.getsource(_query_law_installed_summary_sync)

        assert '"Update"' in source, (
            "KQL SoftwareType filter in _query_law_installed_summary_sync must include "
            '"Update" to capture Azure Update Manager installed patches.'
        )
        assert '"Patch"' in source, (
            "KQL SoftwareType filter in _query_law_installed_summary_sync must include "
            '"Patch" to capture Arc VM Change Tracking installed patches.'
        )


# ---------------------------------------------------------------------------
# _query_law_installed_detail_sync column parsing tests
# ---------------------------------------------------------------------------


class TestQueryLawInstalledDetailSyncColumns:
    """Regression tests: azure-monitor-query v2.x returns columns as plain strings,
    not LogsTableColumn objects.  _query_law_installed_detail_sync must handle both.

    Bug: 'str' object has no attribute 'name' — caused total_count: 0 in production.
    Root cause: azure-monitor-query 2.0.0 changed LogsTable.columns from list[LogsTableColumn]
    to list[str].  Fixed 2026-04-07.
    """

    def _build_mock_monitor_query_module(self, columns, rows):
        """Build a sys.modules-injectable mock for azure.monitor.query."""
        # LogsQueryStatus sentinel
        mock_status = MagicMock()
        mock_status.SUCCESS = "SUCCESS"

        # Table mock
        table = MagicMock()
        table.columns = columns
        table.rows = rows

        # Response mock — .status == LogsQueryStatus.SUCCESS, .tables = [table]
        mock_response = MagicMock()
        mock_response.status = mock_status.SUCCESS
        mock_response.tables = [table]

        # Client mock
        mock_client_instance = MagicMock()
        mock_client_instance.query_workspace.return_value = mock_response

        mock_client_cls = MagicMock(return_value=mock_client_instance)

        # Module mock
        mock_module = MagicMock()
        mock_module.LogsQueryClient = mock_client_cls
        mock_module.LogsQueryStatus = mock_status

        return mock_module, mock_client_instance

    def _run_detail_sync(self, mock_module):
        """Inject mock module and call _query_law_installed_detail_sync."""
        with patch.dict(sys.modules, {
            "azure.monitor.query": mock_module,
        }):
            # Force reimport of function to pick up mocked module
            import importlib
            import services.api_gateway.patch_endpoints as pe
            importlib.reload(pe)
            result = pe._query_law_installed_detail_sync(
                credential=MagicMock(),
                workspace_id="d6e88b39-4f54-4f95-96f1-8acfedf0129c",
                resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/vm",
                days=90,
            )
        return result

    def test_handles_v2_columns_as_strings(self):
        """v2.x: columns list contains plain strings — must not raise AttributeError."""
        columns_v2 = ["SoftwareName", "SoftwareType", "CurrentVersion", "Publisher", "Category", "InstalledDate"]
        rows = [
            ["Security Update KB5001234", "Patch", "Installed", "Microsoft Corporation", "Patch", "2026-04-06 03:17:06"],
        ]
        mock_module, _ = self._build_mock_monitor_query_module(columns_v2, rows)
        result = self._run_detail_sync(mock_module)

        assert len(result) == 1
        assert result[0]["SoftwareName"] == "Security Update KB5001234"
        assert result[0]["SoftwareType"] == "Patch"
        assert result[0]["Category"] == "Patch"

    def test_handles_v1_columns_as_objects(self):
        """v1.x compat: columns list contains objects with .name attribute — must still work."""
        def make_col(name):
            col = MagicMock()
            col.name = name
            return col

        columns_v1 = [make_col(n) for n in ["SoftwareName", "SoftwareType", "CurrentVersion", "Publisher", "Category", "InstalledDate"]]
        rows = [
            ["nginx", "Package", "1.24.0", "Ubuntu", "Package", "2026-04-01 00:00:00"],
        ]
        mock_module, _ = self._build_mock_monitor_query_module(columns_v1, rows)
        result = self._run_detail_sync(mock_module)

        assert len(result) == 1
        assert result[0]["SoftwareName"] == "nginx"
        assert result[0]["SoftwareType"] == "Package"


# ---------------------------------------------------------------------------
# _run_arg_query pagination tests
# ---------------------------------------------------------------------------


class TestRunArgQuery:
    """Tests for the _run_arg_query helper with ARG pagination."""

    def test_handles_pagination(self):
        """Follows skip_token pagination until exhausted."""
        # Set up mock ARG SDK modules
        mock_resourcegraph = MagicMock()
        mock_models = MagicMock()

        mock_client_instance = MagicMock()
        page1 = _mock_arg_response([{"id": "m1"}], skip_token="token-2")
        page2 = _mock_arg_response([{"id": "m2"}], skip_token=None)
        mock_client_instance.resources.side_effect = [page1, page2]

        mock_resourcegraph.ResourceGraphClient.return_value = mock_client_instance
        mock_resourcegraph.models.QueryRequest = MagicMock()
        mock_resourcegraph.models.QueryRequestOptions = MagicMock()

        with patch.dict(sys.modules, {
            "azure.mgmt.resourcegraph": mock_resourcegraph,
            "azure.mgmt.resourcegraph.models": mock_resourcegraph.models,
        }):
            # Re-import to pick up mocked modules
            from importlib import reload
            import services.api_gateway.patch_endpoints as pe
            reload(pe)

            credential = MagicMock()
            result = pe._run_arg_query(credential, ["sub-1"], "test query")

            assert len(result) == 2
            assert result[0]["id"] == "m1"
            assert result[1]["id"] == "m2"
            assert mock_client_instance.resources.call_count == 2

    def test_single_page_no_token(self):
        """Single page result (no skip_token) returns all data."""
        mock_resourcegraph = MagicMock()

        mock_client_instance = MagicMock()
        page = _mock_arg_response([{"id": "m1"}, {"id": "m2"}], skip_token=None)
        mock_client_instance.resources.return_value = page

        mock_resourcegraph.ResourceGraphClient.return_value = mock_client_instance
        mock_resourcegraph.models.QueryRequest = MagicMock()
        mock_resourcegraph.models.QueryRequestOptions = MagicMock()

        with patch.dict(sys.modules, {
            "azure.mgmt.resourcegraph": mock_resourcegraph,
            "azure.mgmt.resourcegraph.models": mock_resourcegraph.models,
        }):
            from importlib import reload
            import services.api_gateway.patch_endpoints as pe
            reload(pe)

            credential = MagicMock()
            result = pe._run_arg_query(credential, ["sub-1", "sub-2"], "test query")

            assert len(result) == 2
            assert mock_client_instance.resources.call_count == 1


# ---------------------------------------------------------------------------
# Pending patches endpoint tests
# ---------------------------------------------------------------------------


class TestGetPendingPatches:
    """Tests for GET /api/v1/patch/pending."""

    RESOURCE_ID = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

    SAMPLE_ROWS = [
        {
            "patchName": "2026-03 Cumulative Update for Windows Server 2022",
            "classifications": ["Security", "Critical"],
            "rebootRequired": True,
            "kbid": "5034441",
            "version": "10.0.20348.2340",
            "publishedDateTime": "2026-03-11T00:00:00Z",
        },
        {
            "patchName": "2026-03 Servicing Stack Update for Windows Server 2022",
            "classifications": ["Security"],
            "rebootRequired": False,
            "kbid": "KB5035853",
            "version": "10.0.20348.2300",
            "publishedDateTime": "2026-03-11T00:00:00Z",
        },
        {
            "patchName": "Definition Update for Windows Defender",
            "classifications": ["Definition"],
            "rebootRequired": False,
            "kbid": "",
            "version": "1.409.100.0",
            "publishedDateTime": None,
        },
    ]

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_returns_pending_patches(self, mock_query, client):
        """Successful response includes patches array with cves field."""
        mock_query.return_value = self.SAMPLE_ROWS

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.return_value = {
                "KB5034441": ["CVE-2024-21302"],
                "KB5035853": ["CVE-2024-26234"],
            }
            resp = client.get(f"/api/v1/patch/pending?resource_id={self.RESOURCE_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 3
        assert body["resource_id"] == self.RESOURCE_ID

        # All patches must have a cves field
        for p in body["patches"]:
            assert "cves" in p, f"patch {p['patchName']!r} missing 'cves' field"

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_pending_cve_enrichment_numeric_kbid(self, mock_query, client):
        """Numeric kbid (no 'KB' prefix) is normalised to 'KB{id}' for MSRC lookup.

        Regression test: ARG returns kbid as a bare number (e.g. '5034441').
        The enrichment must prepend 'KB' before calling get_cves_for_kbs.
        """
        mock_query.return_value = [
            {
                "patchName": "2026-03 Cumulative Update",
                "classifications": ["Security"],
                "rebootRequired": True,
                "kbid": "5034441",
                "version": "10.0.20348.2340",
                "publishedDateTime": "2026-03-11T00:00:00Z",
            },
        ]

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.return_value = {"KB5034441": ["CVE-2024-21302"]}
            resp = client.get(f"/api/v1/patch/pending?resource_id={self.RESOURCE_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["patches"][0]["cves"] == ["CVE-2024-21302"]

        # Verify MSRC was called with the KB-prefixed form
        called_with = mock_cves.call_args[0][0]
        assert "KB5034441" in called_with

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_pending_cve_enrichment_graceful_degradation(self, mock_query, client):
        """CVE enrichment failure still returns patches with empty cves list."""
        mock_query.return_value = [
            {
                "patchName": "2026-03 Cumulative Update",
                "classifications": ["Security"],
                "rebootRequired": True,
                "kbid": "5034441",
                "version": "10.0.20348.2340",
                "publishedDateTime": "2026-03-11T00:00:00Z",
            },
        ]

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.side_effect = Exception("MSRC API unavailable")
            resp = client.get(f"/api/v1/patch/pending?resource_id={self.RESOURCE_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["patches"][0]["cves"] == []

    @patch("services.api_gateway.patch_endpoints._run_arg_query")
    def test_pending_no_kbid_no_cves(self, mock_query, client):
        """Patches with no kbid and no KB pattern in name get empty cves."""
        mock_query.return_value = [
            {
                "patchName": "Definition Update for Windows Defender",
                "classifications": ["Definition"],
                "rebootRequired": False,
                "kbid": "",
                "version": "1.409.100.0",
                "publishedDateTime": None,
            },
        ]

        with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
            mock_cves.return_value = {}
            resp = client.get(f"/api/v1/patch/pending?resource_id={self.RESOURCE_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["patches"][0]["cves"] == []

    def test_pending_returns_400_for_invalid_resource_id(self, client):
        """Malformed resource_id (no subscription) returns 400."""
        resp = client.get("/api/v1/patch/pending?resource_id=not-a-valid-id")
        assert resp.status_code == 400

    def test_pending_returns_422_when_resource_id_missing(self, client):
        """Missing resource_id query param returns 422."""
        resp = client.get("/api/v1/patch/pending")
        assert resp.status_code == 422
