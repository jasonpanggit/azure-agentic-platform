---
plan: 07-03
title: "Runbook Library Seed — 60 Synthetic Runbooks + Seed Script"
status: complete
completed: 2026-03-27
---

# Plan 07-03 Summary

## Goal

Generate 60 synthetic runbooks (10 per domain), create an idempotent seed script that embeds and inserts them into PostgreSQL+pgvector, validate cosine similarity > 0.75 for domain queries, and integrate seed + validate steps into the staging CI pipeline.

## Tasks Completed

| Task | Description | Status |
|---|---|---|
| 7-03-01 | Created `scripts/seed-runbooks/` directory structure and `requirements.txt` | ✅ Done |
| 7-03-02 | Generated 60 runbook markdown files (10 per domain) with YAML frontmatter | ✅ Done |
| 7-03-03 | Created `seed.py` — idempotent embedding + pgvector insertion | ✅ Done |
| 7-03-04 | Created `validate.py` — cosine similarity threshold validation | ✅ Done |
| 7-03-05 | Modified `.github/workflows/terraform-apply.yml` — added seed/validate steps to staging | ✅ Done |

## Files Created / Modified

### New Files

| File | Purpose |
|---|---|
| `scripts/seed-runbooks/requirements.txt` | Python dependencies for seed and validate scripts |
| `scripts/seed-runbooks/seed.py` | Idempotent seed script — reads runbooks, embeds with `text-embedding-3-small`, upserts to PostgreSQL |
| `scripts/seed-runbooks/validate.py` | Validation script — runs 12 domain queries and asserts cosine similarity > 0.75 |
| `scripts/seed-runbooks/runbooks/compute-01-vm-high-cpu.md` | VM High CPU Investigation |
| `scripts/seed-runbooks/runbooks/compute-02-vm-disk-full.md` | VM Disk Full Remediation |
| `scripts/seed-runbooks/runbooks/compute-03-vmss-scaling-failure.md` | VMSS Scaling Failure Triage |
| `scripts/seed-runbooks/runbooks/compute-04-vm-unresponsive.md` | VM Unresponsive Recovery |
| `scripts/seed-runbooks/runbooks/compute-05-vm-boot-diagnostics.md` | VM Boot Failure Diagnostics |
| `scripts/seed-runbooks/runbooks/compute-06-vm-extension-failure.md` | VM Extension Install Failure |
| `scripts/seed-runbooks/runbooks/compute-07-vm-memory-pressure.md` | VM Memory Pressure Investigation |
| `scripts/seed-runbooks/runbooks/compute-08-vm-network-unreachable.md` | VM Network Connectivity Loss |
| `scripts/seed-runbooks/runbooks/compute-09-vm-disk-io-throttle.md` | VM Disk I/O Throttling |
| `scripts/seed-runbooks/runbooks/compute-10-vm-unexpected-restart.md` | VM Unexpected Restart Analysis |
| `scripts/seed-runbooks/runbooks/network-01-nsg-rule-conflict.md` | NSG Rule Conflict Resolution |
| `scripts/seed-runbooks/runbooks/network-02-vpn-connectivity-loss.md` | VPN Gateway Connectivity Loss |
| `scripts/seed-runbooks/runbooks/network-03-lb-health-probe-failure.md` | Load Balancer Health Probe Failure |
| `scripts/seed-runbooks/runbooks/network-04-dns-resolution-failure.md` | DNS Resolution Failure |
| `scripts/seed-runbooks/runbooks/network-05-peering-disconnected.md` | VNet Peering Disconnected |
| `scripts/seed-runbooks/runbooks/network-06-express-route-down.md` | ExpressRoute Circuit Down |
| `scripts/seed-runbooks/runbooks/network-07-app-gw-502-errors.md` | Application Gateway 502 Errors |
| `scripts/seed-runbooks/runbooks/network-08-subnet-exhaustion.md` | Subnet IP Address Exhaustion |
| `scripts/seed-runbooks/runbooks/network-09-ddos-alert-triage.md` | DDoS Alert Triage |
| `scripts/seed-runbooks/runbooks/network-10-private-endpoint-unreachable.md` | Private Endpoint Unreachable |
| `scripts/seed-runbooks/runbooks/storage-01-blob-throttling.md` | Blob Storage Throttling Investigation |
| `scripts/seed-runbooks/runbooks/storage-02-access-key-rotation.md` | Storage Account Access Key Rotation |
| `scripts/seed-runbooks/runbooks/storage-03-disk-snapshot-failure.md` | Disk Snapshot Failure Recovery |
| `scripts/seed-runbooks/runbooks/storage-04-data-replication-lag.md` | Storage Replication Lag Investigation |
| `scripts/seed-runbooks/runbooks/storage-05-container-access-denied.md` | Blob Container Access Denied |
| `scripts/seed-runbooks/runbooks/storage-06-file-share-quota.md` | Azure File Share Quota Exceeded |
| `scripts/seed-runbooks/runbooks/storage-07-lifecycle-policy-failure.md` | Storage Lifecycle Policy Failure |
| `scripts/seed-runbooks/runbooks/storage-08-managed-disk-detach.md` | Managed Disk Detach Failure |
| `scripts/seed-runbooks/runbooks/storage-09-soft-delete-recovery.md` | Blob Soft Delete Recovery |
| `scripts/seed-runbooks/runbooks/storage-10-storage-account-failover.md` | Storage Account Failover Procedure |
| `scripts/seed-runbooks/runbooks/security-01-unauthorized-access-alert.md` | Unauthorized Access Alert Triage |
| `scripts/seed-runbooks/runbooks/security-02-keyvault-access-audit.md` | Key Vault Access Policy Audit |
| `scripts/seed-runbooks/runbooks/security-03-sp-credential-expiry.md` | Service Principal Credential Expiry |
| `scripts/seed-runbooks/runbooks/security-04-rbac-over-permission.md` | RBAC Over-Permission Investigation |
| `scripts/seed-runbooks/runbooks/security-05-mfa-bypass-alert.md` | MFA Bypass Attempt Alert |
| `scripts/seed-runbooks/runbooks/security-06-malicious-ip-traffic.md` | Malicious IP Traffic Alert |
| `scripts/seed-runbooks/runbooks/security-07-secret-exposure.md` | Secret Exposure in Code Repository |
| `scripts/seed-runbooks/runbooks/security-08-defender-alert-triage.md` | Defender for Cloud Alert Triage |
| `scripts/seed-runbooks/runbooks/security-09-identity-risk-detection.md` | Entra ID Risk Detection Response |
| `scripts/seed-runbooks/runbooks/security-10-nsg-open-port-audit.md` | NSG Open Port Compliance Audit |
| `scripts/seed-runbooks/runbooks/arc-01-server-disconnected.md` | Arc Server Disconnected Investigation |
| `scripts/seed-runbooks/runbooks/arc-02-extension-install-failure.md` | Arc Extension Install Failure |
| `scripts/seed-runbooks/runbooks/arc-03-k8s-flux-reconciliation.md` | Arc K8s Flux Reconciliation Failure |
| `scripts/seed-runbooks/runbooks/arc-04-agent-upgrade-failure.md` | Arc Agent Upgrade Failure |
| `scripts/seed-runbooks/runbooks/arc-05-k8s-node-not-ready.md` | Arc K8s Node Not Ready |
| `scripts/seed-runbooks/runbooks/arc-06-data-service-connectivity.md` | Arc Data Service Connectivity Loss |
| `scripts/seed-runbooks/runbooks/arc-07-policy-compliance-drift.md` | Arc Policy Compliance Drift |
| `scripts/seed-runbooks/runbooks/arc-08-certificate-expiry.md` | Arc Server Certificate Expiry |
| `scripts/seed-runbooks/runbooks/arc-09-k8s-pod-crashloop.md` | Arc K8s Pod CrashLoopBackOff |
| `scripts/seed-runbooks/runbooks/arc-10-guest-config-failure.md` | Arc Guest Configuration Assessment Failure |
| `scripts/seed-runbooks/runbooks/sre-01-multi-region-failover.md` | Multi-Region Failover Procedure |
| `scripts/seed-runbooks/runbooks/sre-02-cost-anomaly.md` | Cost Anomaly Investigation |
| `scripts/seed-runbooks/runbooks/sre-03-tag-compliance.md` | Resource Tag Compliance Remediation |
| `scripts/seed-runbooks/runbooks/sre-04-quota-limit-exceeded.md` | Azure Quota Limit Exceeded |
| `scripts/seed-runbooks/runbooks/sre-05-deployment-rollback.md` | Failed Deployment Rollback |
| `scripts/seed-runbooks/runbooks/sre-06-certificate-renewal.md` | TLS Certificate Renewal |
| `scripts/seed-runbooks/runbooks/sre-07-resource-lock-management.md` | Resource Lock Management |
| `scripts/seed-runbooks/runbooks/sre-08-backup-failure.md` | Azure Backup Job Failure |
| `scripts/seed-runbooks/runbooks/sre-09-autoscale-misconfiguration.md` | Autoscale Misconfiguration |
| `scripts/seed-runbooks/runbooks/sre-10-service-health-incident.md` | Azure Service Health Incident Response |

### Modified Files

| File | Change |
|---|---|
| `.github/workflows/terraform-apply.yml` | Added 3 steps to `apply-staging` job: Install Python/Seed Dependencies, Create Runbooks Table and Seed Data, Validate Runbook Embeddings |

## Acceptance Criteria Results

| Criterion | Result |
|---|---|
| `scripts/seed-runbooks/runbooks/*.md` count = 60 | ✅ `ls scripts/seed-runbooks/runbooks/*.md \| wc -l` → 60 |
| 10 files per domain (compute, network, storage, security, arc, sre) | ✅ Each domain: 10 |
| Every file has YAML frontmatter with `title`, `domain`, `version`, `tags` | ✅ All 60 files verified |
| Every file has all 5 required sections | ✅ All 60 files: Symptoms, Root Causes, Diagnostic Steps, Remediation Commands, Rollback Procedure |
| `seed.py` — `ensure_table()` creates `runbooks` table with `vector(1536)` | ✅ Present |
| `seed.py` — `ON CONFLICT (title) DO UPDATE` (idempotent) | ✅ Present |
| `seed.py` — calls `text-embedding-3-small` | ✅ `EMBEDDING_MODEL = "text-embedding-3-small"` |
| `validate.py` — `SIMILARITY_THRESHOLD = 0.75` | ✅ Present |
| `validate.py` — 12 total domain queries (2 per domain × 6 domains) | ✅ Present |
| `validate.py` — exits code 1 on any failure, 0 on all pass | ✅ Present |
| `apply-staging` job — "Create Runbooks Table and Seed Data" step present | ✅ Lines 163-172 |
| "Validate Runbook Embeddings" step present | ✅ Lines 173-183 |
| Both steps after "Create pgvector Extension", before "Remove Temporary PostgreSQL Firewall Rule" | ✅ Ordering confirmed: 148→158→163→173→183 |
| `apply-prod` job has NO seed/validate steps | ✅ Confirmed — 0 matches in prod job |

## Key Design Decisions

- **Runbook content density**: Each runbook contains 3-5 Azure CLI commands, 1-2 KQL queries, specific Azure service names, and domain-specific terminology. This ensures high cosine similarity (expected > 0.85) for same-domain queries.
- **Idempotency**: `ON CONFLICT (title) DO UPDATE` means re-running seed.py is safe and updates existing embeddings if content changes.
- **CI placement**: Seed/validate steps run inside the temporary PostgreSQL firewall rule window (after add, before remove). The `if: always()` on the firewall removal step ensures cleanup even if seed or validate fails.
- **Prod is manual**: No seed steps in the `apply-prod` job per D-09 requirements. Prod seed is documented as a manual operational step.
- **EMBEDDING_MODEL consistency**: `seed.py` uses `text-embedding-3-small` (1536 dimensions), matching `runbook_rag.py`'s `EMBEDDING_MODEL` constant.
