---
title: "Arc K8s Pod CrashLoopBackOff"
domain: arc
version: "1.0"
tags: ["arc", "kubernetes", "pod", "crashloop", "k8s", "debugging"]
---

## Symptoms

One or more pods in an Azure Arc-enabled Kubernetes cluster are in `CrashLoopBackOff` state. Kubernetes repeatedly restarts the failing pod with exponentially increasing back-off delays (10s, 20s, 40s, up to 5 minutes). The application served by the pod is unavailable or degraded. Azure Monitor Container Insights shows pod restart count alerts firing. The `kubectl get pods` output shows `RESTARTS` count increasing.

## Root Causes

1. Application crash on startup — unhandled exception, missing required environment variable, or misconfigured startup command.
2. Missing or inaccessible ConfigMap or Secret — the pod requires a Kubernetes secret that does not exist or the Arc GitOps-managed config has an error.
3. Out of memory (OOM) kill — the container exceeds its memory limit and is killed by the Kubernetes OOM killer.
4. Image pull failure followed by crash — the container image was pulled but contains a broken entrypoint or missing dependencies.

## Diagnostic Steps

1. Check pod status and restart history:
   ```bash
   kubectl get pod {pod_name} -n {namespace} -o wide
   kubectl describe pod {pod_name} -n {namespace} | grep -A30 "Events:"
   ```
2. Get the logs from the last crash:
   ```bash
   # Logs from previous (crashed) container instance
   kubectl logs {pod_name} -n {namespace} --previous --tail=100
   # Current container logs (if restarted and briefly running)
   kubectl logs {pod_name} -n {namespace} --tail=100
   ```
3. Check resource limits vs actual consumption:
   ```bash
   kubectl describe pod {pod_name} -n {namespace} | grep -A5 "Limits:\|Requests:\|Last State:"
   kubectl top pod {pod_name} -n {namespace}
   ```
4. Verify required secrets and configmaps exist:
   ```bash
   kubectl describe pod {pod_name} -n {namespace} | grep -A5 "Environment:\|Volumes:"
   kubectl get secret {required_secret} -n {namespace} 2>/dev/null || echo "SECRET MISSING"
   kubectl get configmap {required_cm} -n {namespace} 2>/dev/null || echo "CONFIGMAP MISSING"
   ```
5. Query Container Insights for OOM kills:
   ```kql
   KubePodInventory
   | where ClusterName == "{arc_cluster_name}" and Name == "{pod_name}"
   | where TimeGenerated > ago(2h)
   | project TimeGenerated, Name, Namespace, ContainerLastStatus, ContainerStatusReason
   | order by TimeGenerated desc
   ```

## Remediation Commands

```bash
# Delete and recreate the pod (if managed by a Deployment, it auto-restarts)
kubectl delete pod {pod_name} -n {namespace}

# Increase memory limits on the deployment
kubectl patch deployment {deployment_name} -n {namespace} \
  --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"512Mi"}]'

# Create a missing secret that the pod requires
kubectl create secret generic {secret_name} -n {namespace} \
  --from-literal=key={value}

# Debug by running the container interactively
kubectl run debug-{pod_name} --image={image} -n {namespace} \
  --rm -it --restart=Never -- /bin/sh
```

## Rollback Procedure

If a recent deployment caused the CrashLoopBackOff, roll back to the previous Deployment revision: `kubectl rollout undo deployment/{deployment_name} -n {namespace}`. Check the rollout history first: `kubectl rollout history deployment/{deployment_name} -n {namespace}`. After rolling back, investigate the root cause of the crash in the previous image version using staging environment debugging before redeploying. Update the Pod resource requests/limits based on observed memory usage patterns.
