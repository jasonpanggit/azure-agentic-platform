"""GitOps remediation path for Arc K8s clusters (REMEDI-008).

For clusters with Flux/ArgoCD detected, creates a PR against the
GitOps repo instead of applying directly. For non-GitOps clusters,
signals that direct-apply should be used.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def is_gitops_managed(flux_configs: list) -> bool:
    """Determine if a cluster is GitOps-managed based on Flux configuration.

    Args:
        flux_configs: List of Flux configuration objects from arc_k8s_gitops_status().
            Empty list means no GitOps controller detected.

    Returns:
        True if Flux or ArgoCD is detected (non-empty config list).
    """
    return len(flux_configs) > 0


async def create_gitops_pr(
    repo_url: str,
    target_branch: str,
    github_token: str,
    incident_id: str,
    description: str,
    manifest_content: str,
    manifest_path: str,
) -> dict:
    """Create a PR against the GitOps repo for remediation.

    Args:
        repo_url: GitHub repo URL (e.g., https://github.com/org/repo).
        target_branch: Target branch (e.g., main).
        github_token: GitHub PAT from Key Vault.
        incident_id: Incident ID for branch naming.
        description: Human-readable change description.
        manifest_content: Updated YAML manifest content.
        manifest_path: Path in repo to the manifest file.

    Returns:
        Dict with pr_url, pr_number, branch_name keys.
    """
    # Parse owner/repo from URL
    parts = repo_url.rstrip("/").split("/")
    owner = parts[-2]
    repo = parts[-1].replace(".git", "")

    branch_name = f"aiops/fix-{incident_id}-remediation"
    api_base = "https://api.github.com"

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Get the SHA of the target branch
        ref_resp = await client.get(
            f"{api_base}/repos/{owner}/{repo}/git/refs/heads/{target_branch}",
            headers=headers,
        )
        ref_resp.raise_for_status()
        base_sha = ref_resp.json()["object"]["sha"]

        # 2. Create a new branch
        await client.post(
            f"{api_base}/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )

        # 3. Create/update the manifest file
        content_b64 = base64.b64encode(manifest_content.encode()).decode()
        await client.put(
            f"{api_base}/repos/{owner}/{repo}/contents/{manifest_path}",
            headers=headers,
            json={
                "message": f"[AAP] {description}",
                "content": content_b64,
                "branch": branch_name,
            },
        )

        # 4. Create the PR
        pr_body = (
            f"## AAP Automated Remediation\n\n"
            f"**Incident:** {incident_id}\n\n"
            f"**Change:** {description}\n\n"
            f"**Rollback:** Revert this PR to undo the change.\n"
        )
        pr_resp = await client.post(
            f"{api_base}/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={
                "title": f"[AAP] {description}",
                "body": pr_body,
                "head": branch_name,
                "base": target_branch,
            },
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()

        return {
            "pr_url": pr_data["html_url"],
            "pr_number": pr_data["number"],
            "branch_name": branch_name,
        }
