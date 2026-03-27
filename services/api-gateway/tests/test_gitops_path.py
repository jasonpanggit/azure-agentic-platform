"""Stub: GitOps vs direct-apply remediation path tests (REMEDI-003)."""
import pytest


class TestGitOpsPath:
    """Tests for the conditional GitOps (PR-based) vs direct-apply remediation path."""

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_flux_detected_returns_gitops_managed_true(self, mock_arm_client):
        """Non-empty Flux configuration on cluster returns gitops_managed=True."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_no_flux_returns_gitops_managed_false(self, mock_arm_client):
        """Empty Flux configuration returns gitops_managed=False."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_gitops_path_creates_pr(self, client, mock_arm_client):
        """GitOps-managed cluster triggers GitHub API POST /repos/.../pulls call."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_direct_apply_no_pr(self, client, mock_arm_client):
        """Non-GitOps cluster calls kubectl_apply; github_create_pr is NOT called."""
        pass

    @pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05-04")
    def test_pr_branch_name_format(self, client, mock_arm_client):
        """PR branch name matches pattern aiops/fix-{incident_id}-*."""
        pass
