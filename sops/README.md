# sops

Standard Operating Procedures (SOPs) for each agent domain. These are the authoritative runbook sources that domain agents use when reasoning about incidents — they are uploaded to the runbook library and embedded for RAG retrieval.

## Contents

- `_schema/` — JSON Schema definition that all SOP files must validate against
- `compute/` — VM diagnostics, restart procedures, disk and memory runbooks
- `network/` — NSG troubleshooting, VNet peering, ExpressRoute, connectivity checks
- `storage/` — throttling resolution, replication, access control runbooks
- `security/` — Defender alert response, RBAC audit, Key Vault incident runbooks
- `arc/` — Arc-enabled server and Kubernetes troubleshooting procedures
- `sre/` — SLO breach response, availability runbooks, cross-domain correlation
- `patch/` — Patch assessment, Update Manager runbooks, patching workflows
- `eol/` — End-of-life resource identification and remediation procedures
- `aks/` — AKS cluster health, node pool, and workload runbooks
- `vmss/` — Virtual Machine Scale Set scaling and health runbooks
