---
title: "Arc K8s Flux Reconciliation Failure"
domain: arc
version: "1.0"
tags: ["arc", "kubernetes", "flux", "gitops", "reconciliation", "k8s"]
---

## Symptoms

An Arc-enabled Kubernetes cluster shows GitOps reconciliation failures in the Azure portal. The Flux operator is unable to pull the latest configuration from the Git repository or apply manifests to the cluster. Azure Monitor shows the `fluxConfigurations` resource as non-compliant. Deployed workloads may be running stale configurations. Azure Policy GitOps compliance alerts fire.

## Root Causes

1. Git repository authentication failure — the SSH key or personal access token used by Flux to pull the repo has expired or been revoked.
2. Repository URL changed — the GitOps configuration references an old repository URL after a repo migration.
3. Kustomization error — invalid YAML or Kubernetes manifest syntax in the repository causes the apply step to fail.
4. Flux controller pod crashed or is in a CrashLoopBackOff state on the cluster.

## Diagnostic Steps

1. Check the Flux configuration status in Azure:
   ```bash
   az k8s-configuration flux show \
     --resource-group {rg} \
     --cluster-name {arc_cluster_name} \
     --cluster-type connectedClusters \
     --name {flux_config_name} \
     --query "{status:complianceState,message:statusConditions[-1].message,kustomizations:kustomizations}"
   ```
2. Check GitRepository source status in the cluster:
   ```bash
   kubectl get gitrepository -n flux-system -o wide
   kubectl describe gitrepository {source_name} -n flux-system | tail -30
   ```
3. Check Flux kustomization status:
   ```bash
   kubectl get kustomization -n flux-system
   kubectl describe kustomization {kustomization_name} -n flux-system | grep -A20 "Status:"
   ```
4. Check Flux controller logs for errors:
   ```bash
   kubectl logs -n flux-system deploy/source-controller --since=1h | grep -i "error\|fail" | tail -30
   kubectl logs -n flux-system deploy/kustomize-controller --since=1h | grep -i "error\|fail" | tail -30
   ```
5. Verify Git repo credentials secret exists and is valid:
   ```bash
   kubectl get secret -n flux-system | grep flux
   kubectl describe secret {flux_git_secret} -n flux-system | grep -v data
   ```

## Remediation Commands

```bash
# Force a Flux reconciliation to pick up latest changes
az k8s-configuration flux update \
  --resource-group {rg} \
  --cluster-name {arc_cluster_name} \
  --cluster-type connectedClusters \
  --name {flux_config_name} \
  --force-update

# Update the Git credentials if SSH key expired
az k8s-configuration flux update \
  --resource-group {rg} \
  --cluster-name {arc_cluster_name} \
  --cluster-type connectedClusters \
  --name {flux_config_name} \
  --ssh-private-key-file ~/.ssh/new_flux_key \
  --https-user {git_user} --https-key {new_pat}

# Restart Flux controllers (on the cluster)
kubectl rollout restart deploy/source-controller -n flux-system
kubectl rollout restart deploy/kustomize-controller -n flux-system

# Suspend and resume a failing kustomization
kubectl patch kustomization {kustomization_name} -n flux-system \
  --type=merge -p '{"spec":{"suspend":true}}'
sleep 10
kubectl patch kustomization {kustomization_name} -n flux-system \
  --type=merge -p '{"spec":{"suspend":false}}'
```

## Rollback Procedure

If a bad commit to the Git repository caused the reconciliation failure, revert the commit in the repository: `git revert HEAD && git push`. Flux will automatically detect the reverted commit and re-reconcile on the next poll interval (default 1 minute). If the cluster state is deeply inconsistent, delete and recreate the Flux configuration with the correct repository reference using the Arc GitOps extension. Ensure all Kustomization files are validated with `kustomize build` before committing.
