"""Tests for the GitOps vs direct-apply remediation path (REMEDI-003)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGitOpsPath:
    """Tests for the conditional GitOps (PR-based) vs direct-apply remediation path."""

    def test_flux_detected_returns_gitops_managed_true(self, mock_arm_client):
        """Non-empty Flux configuration on cluster returns gitops_managed=True."""
        from agents.shared.gitops import is_gitops_managed

        result = is_gitops_managed([{"name": "flux-system"}])
        assert result is True

    def test_no_flux_returns_gitops_managed_false(self, mock_arm_client):
        """Empty Flux configuration returns gitops_managed=False."""
        from agents.shared.gitops import is_gitops_managed

        result = is_gitops_managed([])
        assert result is False

    @pytest.mark.asyncio
    async def test_gitops_path_creates_pr(self, client, mock_arm_client):
        """GitOps-managed cluster triggers GitHub API POST /repos/.../pulls call."""
        from agents.shared.gitops import create_gitops_pr

        pr_response = MagicMock()
        pr_response.json.return_value = {
            "html_url": "https://github.com/contoso/gitops/pull/42",
            "number": 42,
        }
        pr_response.raise_for_status = MagicMock()

        ref_response = MagicMock()
        ref_response.json.return_value = {"object": {"sha": "abc123"}}
        ref_response.raise_for_status = MagicMock()

        create_ref_response = MagicMock()
        create_ref_response.raise_for_status = MagicMock()

        put_file_response = MagicMock()
        put_file_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.get = AsyncMock(return_value=ref_response)
        mock_http_client.post = AsyncMock(side_effect=[create_ref_response, pr_response])
        mock_http_client.put = AsyncMock(return_value=put_file_response)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await create_gitops_pr(
                repo_url="https://github.com/contoso/gitops-repo",
                target_branch="main",
                github_token="ghp_test_token",
                incident_id="inc-001",
                description="Restart VM vm-prod-01",
                manifest_content="apiVersion: v1\nkind: Pod",
                manifest_path="clusters/prod/vm-patch.yaml",
            )

        # Assert POST to /repos/.../pulls was called
        post_calls = mock_http_client.post.call_args_list
        pulls_call = next(
            (c for c in post_calls if "/pulls" in str(c)),
            None,
        )
        assert pulls_call is not None, (
            f"Expected a POST to /pulls, got calls: {post_calls}"
        )
        assert result["pr_url"] == "https://github.com/contoso/gitops/pull/42"

    def test_direct_apply_no_pr(self, client, mock_arm_client):
        """Non-GitOps cluster: is_gitops_managed returns False, create_gitops_pr NOT called."""
        from agents.shared.gitops import is_gitops_managed

        flux_configs: list = []
        gitops_managed = is_gitops_managed(flux_configs)

        assert gitops_managed is False

        # Simulate the branching logic: create_gitops_pr is only called when gitops_managed=True
        mock_create_pr = MagicMock()
        if gitops_managed:
            mock_create_pr()  # this should NOT be called

        mock_create_pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_pr_branch_name_format(self, client, mock_arm_client):
        """PR branch name matches pattern aiops/fix-{incident_id}-remediation."""
        from agents.shared.gitops import create_gitops_pr

        pr_response = MagicMock()
        pr_response.json.return_value = {
            "html_url": "https://github.com/contoso/gitops/pull/5",
            "number": 5,
        }
        pr_response.raise_for_status = MagicMock()

        ref_response = MagicMock()
        ref_response.json.return_value = {"object": {"sha": "deadbeef"}}
        ref_response.raise_for_status = MagicMock()

        create_ref_response = MagicMock()
        create_ref_response.raise_for_status = MagicMock()

        put_file_response = MagicMock()
        put_file_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.get = AsyncMock(return_value=ref_response)
        mock_http_client.post = AsyncMock(side_effect=[create_ref_response, pr_response])
        mock_http_client.put = AsyncMock(return_value=put_file_response)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await create_gitops_pr(
                repo_url="https://github.com/contoso/gitops-repo",
                target_branch="main",
                github_token="ghp_test_token",
                incident_id="inc-001",
                description="Fix pod crash loop",
                manifest_content="apiVersion: v1",
                manifest_path="clusters/prod/patch.yaml",
            )

        branch_name = result["branch_name"]
        assert "aiops/fix-inc-001" in branch_name, (
            f"Branch name '{branch_name}' does not contain 'aiops/fix-inc-001'"
        )
        assert branch_name == "aiops/fix-inc-001-remediation", (
            f"Expected 'aiops/fix-inc-001-remediation', got '{branch_name}'"
        )
