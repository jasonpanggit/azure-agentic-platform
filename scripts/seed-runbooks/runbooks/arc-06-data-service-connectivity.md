---
title: "Arc Data Service Connectivity Loss"
domain: arc
version: "1.0"
tags: ["arc", "data-services", "sql-managed-instance", "postgresql", "connectivity"]
---

## Symptoms

An Azure Arc-enabled data service (SQL Managed Instance or PostgreSQL Hyperscale) deployed on an Arc Kubernetes cluster loses connectivity to the Azure management plane. The data service resource in Azure shows as "Disconnected" or "Unknown" state. Arc data controller metrics and logs stop flowing to Azure Monitor. The data service itself may remain operational for local workloads but loses Azure management capabilities (backup, monitoring, policy).

## Root Causes

1. Arc data controller pod not running — the `controldb` or `logsdb` pod in the Arc data controller namespace has crashed.
2. Kubernetes connectivity to Arc endpoints disrupted — the cluster's outbound HTTPS connectivity to Arc data service endpoints is blocked.
3. Arc data controller identity credentials expired — the service principal or managed identity used by the data controller has expired credentials.
4. Insufficient storage for data controller persistent volumes — PVCs for metrics and logs storage are full.

## Diagnostic Steps

1. Check Arc data controller status:
   ```bash
   az arcdata dc status show --resource-group {rg} --name {dc_name} \
     --query "{state:properties.k8sRaw.status.state,readyReplicas:properties.k8sRaw.status.readyReplicas}"
   ```
2. Check data controller pods health:
   ```bash
   kubectl get pods -n {arc_dc_namespace} -o wide
   kubectl describe pods -n {arc_dc_namespace} | grep -A10 "Events:"
   ```
3. Check data controller logs:
   ```bash
   kubectl logs -n {arc_dc_namespace} -l app=controldb --since=2h | grep -i "error\|fail\|connect" | tail -30
   ```
4. Check persistent volume claim usage:
   ```bash
   kubectl get pvc -n {arc_dc_namespace} -o wide
   kubectl exec -n {arc_dc_namespace} {controldb_pod} -- df -h /var/opt/mssql
   ```
5. Verify Arc data service endpoints are reachable from the cluster:
   ```bash
   kubectl run connectivity-test --image=curlimages/curl:latest --rm -it --restart=Never \
     -n {arc_dc_namespace} -- curl -sv https://eastus.dp.kubernetesconfiguration.azure.com/
   ```

## Remediation Commands

```bash
# Restart the data controller deployment
kubectl rollout restart deploy/controldb -n {arc_dc_namespace}
kubectl rollout restart deploy/logsdb -n {arc_dc_namespace}

# Expand PVC storage if full (requires StorageClass that supports expansion)
kubectl patch pvc {pvc_name} -n {arc_dc_namespace} \
  --type=merge -p '{"spec":{"resources":{"requests":{"storage":"50Gi"}}}}'

# Update Arc data controller credentials
az arcdata dc update --resource-group {rg} --name {dc_name} \
  --use-k8s \
  --k8s-namespace {arc_dc_namespace}

# Re-register the Arc data controller with Azure
az arcdata dc export --type logs --path /tmp/dc-logs.json
az arcdata dc upload --path /tmp/dc-logs.json
```

## Rollback Procedure

Data controller pod restarts are non-destructive — the underlying SQL or PostgreSQL instances continue running and serving local workloads during the restart. If PVC expansion caused issues, monitor the pod startup logs after expansion. If the data controller is irrecoverably broken, the Arc data services can be deleted and redeployed on the Kubernetes cluster while preserving the underlying database data via the persistent volumes, provided the PVs are retained on deletion.
