---
title: "Failed Deployment Rollback"
domain: sre
version: "1.0"
tags: ["sre", "deployment", "rollback", "container-app", "aca", "revision"]
---

## Symptoms

A new deployment to Azure Container Apps or another Azure service introduced a regression. Error rates spiked after the deployment. Health probes started failing. Users report application errors or degraded performance. Azure Monitor shows a correlation between the deployment time and the error rate increase. The team must roll back to the previous known-good version as quickly as possible.

## Root Causes

1. Application code bug introduced in the new version causing unhandled exceptions.
2. Dependency version mismatch — new version requires a library version not available in the deployed container image.
3. Database schema migration incompatibility — new code expects a schema change not yet applied to the database.
4. Configuration environment variable missing from the new revision's deployment spec.

## Diagnostic Steps

1. Identify the deployment time and correlate with error spike:
   ```bash
   az containerapp revision list \
     --resource-group {rg} --name {app_name} \
     --query "[].{name:name,active:active,replicas:replicas,created:createdTime,traffic:trafficWeight}" \
     --output table
   ```
2. Check the current active revision's error rate:
   ```bash
   az monitor metrics list \
     --resource {containerapp_resource_id} \
     --metric "Requests" \
     --filter "StatusCodeClass eq '5xx'" \
     --interval PT1M --start-time $(date -u -d '-1 hour' +%FT%TZ)
   ```
3. Compare application logs between revisions:
   ```kql
   ContainerAppConsoleLogs
   | where ContainerAppName == "{app_name}"
   | where TimeGenerated > ago(2h)
   | where Level == "Error" or Log contains "Exception"
   | project TimeGenerated, RevisionName, Log
   | order by TimeGenerated desc | take 50
   ```
4. Check health probe status for the current revision:
   ```bash
   az containerapp revision show \
     --resource-group {rg} --app-name {app_name} \
     --name {current_revision} \
     --query "{health:properties.healthState,replicas:properties.replicas,traffic:properties.trafficWeight}"
   ```
5. Get previous revision name for rollback:
   ```bash
   az containerapp revision list \
     --resource-group {rg} --name {app_name} \
     --query "sort_by([],&createdTime)[-2:].{name:name,created:createdTime,active:active}" \
     --output table
   ```

## Remediation Commands

```bash
# Option 1: Activate the previous revision and shift all traffic to it
az containerapp ingress traffic set \
  --resource-group {rg} --name {app_name} \
  --revision-weight {previous_revision}=100

# Option 2: Update the container image to the previous tag
az containerapp update \
  --resource-group {rg} --name {app_name} \
  --image {acr_name}.azurecr.io/{image_name}:{previous_tag}

# Option 3: Use traffic splitting during rollback (10% to new, 90% to old)
az containerapp ingress traffic set \
  --resource-group {rg} --name {app_name} \
  --revision-weight {previous_revision}=90 {current_revision}=10

# Deactivate the bad revision after traffic is shifted
az containerapp revision deactivate \
  --resource-group {rg} --app-name {app_name} \
  --name {bad_revision}
```

## Rollback Procedure

Azure Container Apps revision-based rollback is instantaneous — traffic is shifted within seconds. Monitor error rates for 5 minutes after the rollback to confirm the 5xx rate returns to baseline. Once confirmed, deactivate the bad revision. Conduct a post-mortem to identify the root cause before re-attempting the deployment. Add the fix to the CI pipeline to prevent the same regression from being deployed again.
