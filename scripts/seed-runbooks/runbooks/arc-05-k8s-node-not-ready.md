---
title: "Arc K8s Node Not Ready"
domain: arc
version: "1.0"
tags: ["arc", "kubernetes", "node", "not-ready", "k8s", "cluster"]
---

## Symptoms

One or more nodes in an Azure Arc-enabled Kubernetes cluster report `NotReady` status. Pods scheduled on the affected nodes are evicted or stuck in `Pending` state. The Azure Monitor Container Insights shows node health degraded alerts. Azure Policy GitOps compliance may also be affected if Flux is running on the unavailable node. Applications deployed on the cluster experience disruption.

## Root Causes

1. Kubelet service stopped on the node — the kubelet process crashed due to resource exhaustion or a configuration error.
2. Node disk pressure — the node's root filesystem or container storage exceeded the eviction threshold.
3. Node memory pressure — available memory on the node fell below the kubelet memory eviction hard limit.
4. Network partition — the node lost connectivity to the API server, causing it to appear `NotReady` from the control plane perspective.

## Diagnostic Steps

1. Check the node status from the cluster:
   ```bash
   kubectl get nodes -o wide
   kubectl describe node {node_name} | grep -A20 "Conditions:"
   ```
2. Check node resource usage:
   ```bash
   kubectl top nodes
   kubectl describe node {node_name} | grep -A10 "Allocated resources:"
   ```
3. Check system events on the node:
   ```bash
   kubectl get events --field-selector involvedObject.name={node_name} \
     --sort-by='.lastTimestamp' | tail -20
   ```
4. Query Container Insights for node metrics:
   ```kql
   KubeNodeInventory
   | where ClusterName == "{arc_cluster_name}"
   | where Computer == "{node_name}"
   | where TimeGenerated > ago(2h)
   | project TimeGenerated, Status, Reason, Message
   | order by TimeGenerated desc
   ```
5. Check Azure Arc connected cluster status:
   ```bash
   az connectedk8s show \
     --resource-group {rg} --name {arc_cluster_name} \
     --query "{connectivity:connectivityStatus,agentVersion:agentVersion,distribution:distribution}"
   ```

## Remediation Commands

```bash
# Drain and cordon the node to move workloads
kubectl cordon {node_name}
kubectl drain {node_name} --ignore-daemonsets --delete-emptydir-data --timeout=300s

# SSH to the node and restart kubelet
ssh {node_user}@{node_ip} 'sudo systemctl restart kubelet'

# Check disk usage and clean up on the node
ssh {node_user}@{node_ip} 'df -h && docker system prune -f && sudo journalctl --vacuum-size=500M'

# Uncordon the node after it recovers
kubectl uncordon {node_name}

# Force an Arc Kubernetes configuration reconciliation
az connectedk8s update --resource-group {rg} --name {arc_cluster_name}
```

## Rollback Procedure

If draining the node caused pod disruptions that are not auto-recovering, check that the Pod Disruption Budgets (PDBs) allow the drain: `kubectl get pdb --all-namespaces`. After the node is healthy and uncordoned, the scheduler will gradually re-schedule workloads back. If the node remains `NotReady` after kubelet restart, investigate the machine-level issue (disk, memory, network) before re-adding it to the pool. Use `kubectl cordon` to keep it unschedulable until fully confirmed healthy.
