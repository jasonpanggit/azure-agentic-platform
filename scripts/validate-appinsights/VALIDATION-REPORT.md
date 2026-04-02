# App Insights Telemetry Validation Report

**Date:** ____
**App Insights Resource:** ____
**Resource Group:** rg-aap-prod
**Operator:** ____

## How to Use This Template

1. Open the Azure Portal > Application Insights > `appi-aap-prod` > Logs blade
2. Run each query from `kql-queries.md` (in the same directory as this file)
3. Alternatively, run `./validate.sh` from this directory for an automated pass/fail report
4. Fill in the Results table below with actual findings

---

## Results

| # | Container App | cloud_RoleName | Receiving Telemetry | Last Seen | Signal Types | Notes |
|---|---------------|----------------|:-------------------:|-----------|--------------|-------|
| 1 | ca-orchestrator-prod | aiops-orchestrator-agent | | | | |
| 2 | ca-compute-prod | aiops-compute-agent | | | | |
| 3 | ca-network-prod | aiops-network-agent | | | | |
| 4 | ca-storage-prod | aiops-storage-agent | | | | |
| 5 | ca-security-prod | aiops-security-agent | | | | |
| 6 | ca-arc-prod | aiops-arc-agent | | | | |
| 7 | ca-sre-prod | aiops-sre-agent | | | | |
| 8 | ca-patch-prod | aiops-patch-agent | | | | |
| 9 | ca-eol-prod | aiops-eol-agent | | | | |
| 10 | ca-api-gateway-prod | api-gateway | | | | |
| 11 | ca-teams-bot-prod | teams-bot | | | | |
| 12 | ca-arc-mcp-server-prod | arc-mcp-server | | | | |

### Key

- **Receiving Telemetry:** YES / NO / PARTIAL (has some signal types but not all expected)
- **Signal Types:** traces, requests, dependencies, exceptions (from KQL Query 2)
- **Notes:** Any anomalies, unexpected cloud_RoleName values, zero-scale containers, etc.

---

## Summary

- **Sending:** __/12
- **Silent:** __/12
- **Errors detected:** __ (from KQL Query 4)
- **Unexpected cloud_RoleName values:** __ (list any roles not in the expected 12)

---

## Remediation Actions

Fill in for any silent or partially-reporting containers:

| Container | Root Cause | Action | Owner | Done |
|-----------|------------|--------|-------|:----:|
| | | | | |
| | | | | |
| | | | | |

### Common Remediation Steps

1. **Missing env var:** Set `APPLICATIONINSIGHTS_CONNECTION_STRING` on the Container App
   ```bash
   az containerapp update -n <ca-name> -g rg-aap-prod \
     --set-env-vars "APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-connection-string"
   ```

2. **Image missing OTel SDK:** Rebuild and push the container image
   ```bash
   docker build -t <acr>.azurecr.io/<agent>:latest -f <Dockerfile> .
   docker push <acr>.azurecr.io/<agent>:latest
   az containerapp update -n <ca-name> -g rg-aap-prod --image <acr>.azurecr.io/<agent>:latest
   ```

3. **Container scaled to 0:** Send traffic or set min_replicas=1 in Terraform
   ```bash
   az containerapp update -n <ca-name> -g rg-aap-prod --min-replicas 1
   ```

4. **Container crash-looping:** Check logs for startup errors
   ```bash
   az containerapp logs show -n <ca-name> -g rg-aap-prod --type console --tail 100
   ```

---

## OTel Init Log Check

Paste the output of KQL Query 5 here:

```
(paste query 5 results here)
```

---

## CLI Script Output

Paste the output of `./validate.sh` here:

```
(paste validate.sh output here)
```

---

## Sign-Off

- [ ] All 12 containers confirmed sending telemetry
- [ ] No unexpected errors in Query 4
- [ ] OTel init messages confirmed in Query 5
- [ ] Remediation actions completed for any silent containers

**Validated by:** ____
**Date:** ____
