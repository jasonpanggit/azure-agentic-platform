-- Migration 003: GitOps cluster configuration for Arc K8s remediation (REMEDI-008)
CREATE TABLE IF NOT EXISTS gitops_cluster_config (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_resource_id TEXT NOT NULL UNIQUE,
    gitops_repo_url     TEXT NOT NULL,
    target_branch       TEXT NOT NULL DEFAULT 'main',
    github_token_kv_ref TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE gitops_cluster_config IS 'GitOps repo configuration per Arc K8s cluster — REMEDI-008. Maps clusters to their GitOps repo for PR-based remediation.';
