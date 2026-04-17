# scripts/ops

Phase-tagged operational scripts executed during platform delivery phases. Each script name is prefixed with the phase number it belongs to for traceability.

## Contents

| Script | Purpose |
|--------|---------|
| `19-1-azure-mcp-security.sh` | Configure Azure MCP Server security settings |
| `19-3-register-mcp-connections.sh` | Register MCP servers as Foundry connections |
| `19-4-seed-runbooks.sh` | Initial runbook library seed |
| `19-5-package-manifest.sh` | Validate agent container package manifests |
| `19-5-test-teams-alerting.sh` | Smoke-test Teams alert delivery |
| `21-2-activate-detection-plane.sh` | Enable Fabric Activator rules and webhook wiring |
| `21-3-detection-health-check.sh` | Verify end-to-end detection pipeline health |
| `22-4-topology-load-test.sh` | Load test the topology dashboard API |
| `24-3-noise-reduction-test.sh` | Validate alert deduplication and noise reduction |
| `26-4-forecast-accuracy-test.sh` | Test capacity forecasting accuracy |
| `inject-approval.py` | Inject a synthetic HITL approval into Cosmos DB |
| `provision-finops-agent.sh` | Provision the FinOps specialist agent |
| `seed-via-vm.sh` | Run seed scripts through the jumphost VM |
| `simulate-real-incident.sh` | Fire a realistic multi-domain incident scenario |
| `terraform-local-apply.sh` | Apply Terraform locally against a target environment |
