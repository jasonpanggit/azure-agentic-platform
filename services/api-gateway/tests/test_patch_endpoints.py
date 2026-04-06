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

    def test_returns_422_when_no_subscriptions_param(self, client):
        """No subscriptions query param at all returns 422 (FastAPI validation)."""
        resp = client.get("/api/v1/patch/assessment")
        assert resp.status_code == 422

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

    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    def test_returns_installed_patches(self, mock_detail, client):
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

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "ws-123"}, clear=False):
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

    @patch("services.api_gateway.patch_endpoints._query_law_installed_detail", new_callable=AsyncMock)
    def test_installed_cve_enrichment_graceful_degradation(self, mock_detail, client):
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

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "ws-123"}, clear=False):
            with patch("services.api_gateway.msrc_client.get_cves_for_kbs", new_callable=AsyncMock) as mock_cves:
                mock_cves.side_effect = Exception("MSRC API down")
                resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        # CVE enrichment failed but patch data is still returned
        assert body["patches"][0]["cves"] == []

    def test_installed_days_validation(self, client):
        """Days parameter must be between 1 and 365."""
        resource_id = "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-prod-01"

        with patch.dict(os.environ, {"LOG_ANALYTICS_WORKSPACE_ID": "ws-123"}, clear=False):
            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}&days=0")
            assert resp.status_code == 422

            resp = client.get(f"/api/v1/patch/installed?resource_id={resource_id}&days=400")
            assert resp.status_code == 422


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
