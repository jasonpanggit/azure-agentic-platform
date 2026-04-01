# Viewing Logs in Azure Container Apps

## Live Log Stream

```bash
# API Gateway
az containerapp logs show \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# Compute Agent
az containerapp logs show \
  --name ca-compute-agent-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# Network Agent
az containerapp logs show \
  --name ca-network-agent-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# Storage Agent
az containerapp logs show \
  --name ca-storage-agent-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# Security Agent
az containerapp logs show \
  --name ca-security-agent-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# Arc Agent
az containerapp logs show \
  --name ca-arc-agent-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# SRE Agent
az containerapp logs show \
  --name ca-sre-agent-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow

# Orchestrator Agent
az containerapp logs show \
  --name ca-orchestrator-agent-prod \
  --resource-group rg-aap-prod \
  --type system \
  --follow
```

## Filter by Log Level

```bash
az containerapp logs show --name ca-api-gateway-prod --resource-group rg-aap-prod --type system | grep "ERROR"
```

## Filter by Incident ID

```bash
az containerapp logs show --name ca-api-gateway-prod --resource-group rg-aap-prod --type system | grep "incident_id=abc123"
```

## Key Log Patterns

### Incident Ingestion

```
INFO  services.api_gateway.main incident: ingested | incident_id=abc123 severity=Sev1 domain=compute
INFO  services.api_gateway.main pipeline: queued | incident_id=abc123 resource=/subscriptions/...
```

### HTTP Request Log

```
INFO  services.api_gateway.main http: POST /api/v1/incidents | status=202 correlation_id=uuid duration_ms=42
INFO  services.api_gateway.main http: GET /api/v1/incidents | status=200 correlation_id=uuid duration_ms=18
```

### API Gateway Startup

```
INFO  services.api_gateway.main startup: api-gateway starting | version=1.0.0
INFO  services.api_gateway.main startup: COSMOS_ENDPOINT=set
INFO  services.api_gateway.main startup: APPLICATIONINSIGHTS_CONNECTION_STRING=set
INFO  services.api_gateway.main startup: DIAGNOSTIC_LA_WORKSPACE_ID=not_set (log_analytics step will be skipped)
INFO  services.api_gateway.main startup: LOG_LEVEL=INFO
INFO  services.api_gateway.main startup: CORS_ALLOWED_ORIGINS=*
```

### Diagnostic Pipeline

```
INFO  services.api_gateway.diagnostic_pipeline pipeline: starting | incident_id=abc123 resource_id=...
INFO  services.api_gateway.diagnostic_pipeline pipeline: activity_log complete | entries=3 duration_ms=245
INFO  services.api_gateway.diagnostic_pipeline pipeline: resource_health complete | state=Available duration_ms=180
INFO  services.api_gateway.diagnostic_pipeline pipeline: metrics complete | metrics_count=6 duration_ms=320
INFO  services.api_gateway.diagnostic_pipeline pipeline: log_analytics skipped | reason=workspace_id_not_configured
INFO  services.api_gateway.diagnostic_pipeline pipeline: evidence written | incident_id=abc123 status=partial duration_ms=890
```

### Agent Tool Calls

```
INFO  aiops.compute query_activity_log: called | resources=1 timespan_hours=2
INFO  aiops.compute query_activity_log: complete | entries=5 duration_ms=312
INFO  aiops.compute query_os_version: called | resources=2 subscriptions=1
INFO  aiops.compute query_os_version: complete | machines=2 duration_ms=180
```

### Azure SDK Call Duration (log_azure_call context manager)

```
DEBUG aiops.compute azure_call: starting | operation=activity_log.list resource=/subscriptions/...
INFO  aiops.compute azure_call: complete | operation=activity_log.list resource=/subscriptions/... duration_ms=245
ERROR aiops.compute azure_call: failed | operation=metrics.list resource=/subscriptions/... error=AuthorizationFailed duration_ms=1205
```

### Agent Startup (verify config)

```
INFO  aiops.compute startup: AZURE_PROJECT_ENDPOINT=set
INFO  aiops.compute startup: AZURE_CLIENT_ID=set
INFO  aiops.compute startup: COSMOS_ENDPOINT=not_set
INFO  aiops.compute aiops.compute: logging configured | level=INFO
INFO  aiops.compute create_compute_agent: initialising Foundry client
INFO  aiops.compute create_compute_agent: ChatAgent created successfully
```

### Cosmos DB Operations (approvals)

```
INFO  services.api_gateway.approvals cosmos: reading approval | approval_id=abc123 thread_id=thread-xyz
INFO  services.api_gateway.approvals cosmos: approval read | approval_id=abc123 status=pending
INFO  services.api_gateway.approvals cosmos: approval fetched for decision | approval_id=abc123 status=pending decision=approved
INFO  services.api_gateway.approvals cosmos: approval updated | approval_id=abc123 status=approved decided_by=operator@contoso.com
```

### Audit Trail (OneLake)

```
INFO  services.api_gateway.audit_trail audit: writing record to OneLake | approval_id=abc123
INFO  services.api_gateway.audit_trail onelake: writing audit record | approval_id=abc123 path=approvals/2026/04/01/abc123.json
INFO  services.api_gateway.audit_trail Audit record abc123 written to OneLake at approvals/2026/04/01/abc123.json
```

## Increasing Log Verbosity

Set `LOG_LEVEL=DEBUG` on the container app:

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars LOG_LEVEL=DEBUG
```

Set back to INFO when done:

```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars LOG_LEVEL=INFO
```

## Common Issues

### "startup: COSMOS_ENDPOINT=not_set"

The `COSMOS_ENDPOINT` env var is not configured on the container app.
Evidence store is disabled. Diagnostic pipeline will log a summary but not persist evidence.

**Fix:**
```bash
az containerapp update \
  --name ca-api-gateway-prod \
  --resource-group rg-aap-prod \
  --set-env-vars COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
```

### "startup: DIAGNOSTIC_LA_WORKSPACE_ID=not_set (log_analytics step will be skipped)"

The `DIAGNOSTIC_LA_WORKSPACE_ID` env var is not set. The diagnostic pipeline will skip
the Log Analytics evidence step and collect partial evidence only (activity log + resource health + metrics).

**Fix:** Set the Log Analytics workspace resource ID on the api-gateway container app.

### "pipeline: activity_log failed | error=AuthorizationFailed"

The container app managed identity lacks `Monitoring Reader` role on the subscription.

**Fix:**
```bash
az role assignment create \
  --role "Monitoring Reader" \
  --assignee <managed-identity-id> \
  --scope /subscriptions/<subscription-id>
```

### "pipeline: resource_health failed | error=SubscriptionNotFound"

The `resource_id` subscription does not match the agent's accessible subscriptions.
Verify `AZURE_SUBSCRIPTION_IDS` env var on the compute agent.

### "create_compute_agent: initialising Foundry client" — but no "ChatAgent created successfully"

Agent startup failed after getting the Foundry client. Check for:
- Missing `AZURE_PROJECT_ENDPOINT` env var
- Invalid `ORCHESTRATOR_AGENT_ID`
- Network connectivity from the container to Foundry endpoint

### "azure_call: failed | error=AuthorizationFailed"

The managed identity does not have the required RBAC role for the operation.

Common fixes:
- Activity Log: `Monitoring Reader` on subscription
- Resource Health: `Reader` on subscription
- Log Analytics: `Log Analytics Reader` on workspace
- Metrics: `Monitoring Reader` on subscription
