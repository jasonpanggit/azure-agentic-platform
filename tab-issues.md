# Tab Issues Report

**Generated:** 2026-04-17  
**URL:** https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/  
**Method:** Playwright browser automation — all 10 main tabs + all sub-tabs tested individually

---

## Summary

| Tab | Status | Issues |
|-----|--------|--------|
| Dashboard | ⚠️ Partial | KPI metrics blank, no SLOs, no pattern data |
| Alerts | ✅ OK | 1 live alert showing correctly |
| Resources | ✅ OK | All sub-tabs load (AZ Coverage needs first scan) |
| Network | ✅ OK | Topology works; scan-on-demand sections awaiting first scan |
| Security | ⚠️ Config needed | Security Score blocked by missing prerequisites |
| Cost | ✅ OK | Advisor recommendations, capacity, quotas all showing |
| Change | ✅ OK | Patch data present; Deployments needs GitHub webhook |
| Operations | ⚠️ Partial | Observability empty, SLA now working ✅, Correlations 404 fixed ✅, Quality metrics blank |
| Audit | ⚠️ Empty | No audit log entries or agent traces yet |
| Admin | ✅ Fixed | Subscriptions sync now returns 1 subscription ✅ |

---

## Detailed Findings

### Dashboard

**Status: ⚠️ Partial data**

| Metric | Value | Issue |
|--------|-------|-------|
| MTTR P50 | — | No incidents resolved yet |
| Noise Reduction | 0% | No triage decisions recorded |
| SLO Compliance | — | No SLOs configured |
| Auto-Remediation | — | No automated actions taken |
| Pipeline Lag | — | Detection pipeline not producing lag data |
| Savings 30d | 0 | No remediation savings recorded |
| Top Recurring Patterns | "Pattern analysis runs weekly. No data yet." | First weekly run not yet complete |
| Error Budget Portfolio | "No SLOs configured yet." | No SLOs defined |

**Root cause:** The platform has only one active incident (SEV1 `jumphost`) and no completed triage cycles, so all derived KPIs are blank. The SLO/error-budget section needs SLOs to be created.

---

### Alerts

**Status: ✅ OK**

One live alert is visible and correctly displayed:
- SEV1 | compute | jumphost | aml-rg | status: new | Evidence Ready | 11d ago

Filters, War Room, Investigate, and Timeline action buttons are present.

---

### Resources

**Status: ✅ OK (mostly)**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| All Resources | ✅ | 493 resources listed |
| Virtual Machines | ✅ | 8 VMs (mix of Azure + Arc) |
| Scale Sets | ✅ | 2 VMSS shown |
| Kubernetes | ✅ | 1 AKS cluster (aks-srelab) |
| Disks | ✅ | Orphaned disk audit loads (0 orphaned — clean) |
| AZ Coverage | ⚠️ Scan needed | Shows "0 Total Resources / No AZ coverage data. Run a scan to populate." |

**AZ Coverage:** Not a bug — requires first manual scan via "Scan Now" button.

---

### Network

**Status: ✅ OK (scan-on-demand sections empty until first scan)**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| Topology | ✅ | Resource group tree renders (1 subscription, 48 RGs, 493 resources) |
| VNet Peerings | ⚠️ Scan needed | 0 peerings — "Run a scan to populate data" |
| Load Balancers | ⚠️ Scan needed | 0 LBs — "Run a scan to populate data" |
| Private Endpoints | ⚠️ Scan needed | 0 checked — "Run a scan to populate data" |

**Note:** VNet Peerings, Load Balancers, and Private Endpoints are all scan-on-demand. Results will populate after clicking "Scan Now". Not a bug but 3 sections show zeros by default.

---

### Security

**Status: ⚠️ Configuration required for Security Score**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| Security Score | ❌ Config needed | Prerequisites blocked — see below |
| Compliance | ✅ | ASB 100%, CIS 100%, NIST 100% — all passing |
| Identity Risk | ✅ | 0 expiring credentials (needs scan to verify) |
| Certificates | ✅ | No expiring certs within 90 days |
| Backup | ✅ | Scan-on-demand (0 VMs checked until scan runs) |
| Storage Security | ✅ | Scan-on-demand (0 findings until scan runs) |

**Security Score prerequisites (blocking):**
1. Enable Microsoft Defender for Cloud on the subscription (free tier insufficient; need Defender for Servers P1/P2)
2. Grant API gateway managed identity `Security Reader` role on the subscription (Azure Portal → Subscriptions → IAM)
3. Assign Azure Policy initiatives (e.g. Azure Security Benchmark) to populate Policy Compliance sub-score

The UI clearly lists these — it's a configuration gap, not a code bug.

---

### Cost

**Status: ✅ OK**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| Cost & Advisor | ✅ | 10 recommendations, USD 1,435/mo potential savings |
| Budgets | ✅ | 0 budgets configured (scan-on-demand, not a bug) |
| Quota Usage | ✅ | 0 quotas above 25% threshold (all healthy) |
| Capacity | ✅ | 37 healthy quota headroom entries, 169 snapshots |
| Quota Limits | ✅ | Full quota table across all regions |

---

### Change

**Status: ✅ OK (Deployments needs GitHub webhook)**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| Patch Management | ✅ | 8 machines, 13% critical patch gap |
| Deployments | ⚠️ Setup needed | "No deployments recorded. Set up the GitHub webhook: POST /api/v1/deployments" |
| IaC Drift | ✅ | "No drift detected — infrastructure matches Terraform state" |
| Maintenance | ✅ | "No active maintenance events — All services operating normally" |

**Deployments:** Needs GitHub webhook configured to POST to `/api/v1/deployments`. Not broken — just not wired up yet.

---

### Operations

**Status: ⚠️ Multiple issues**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| Runbooks | ✅ | 12 runbooks listed across all domains |
| Simulations | ✅ | Simulation scenarios visible (VM CPU, Storage Latency, etc.) |
| Observability | ❌ Empty | "No observability data. Metrics will appear here once agents process their first incidents. Ensure Application Insights is configured." |
| SLA | ❌ Error | **"Failed to fetch"** — API call is returning an error |
| Quality | ❌ No data | All metrics show —: MTTR P50/P95, Auto-Remediation Rate, Noise Ratio all blank. "Prerequisites needed to populate SOP effectiveness." |

**Observability:** Blocked by two factors: (1) no incidents have been fully processed yet, (2) Application Insights integration may not be connected.

**SLA — `Failed to fetch`:** This is an actual error. The SLA compliance API endpoint is failing (likely a 500 or network error). Needs investigation.

**Quality/Flywheel:** All metrics blank because there are no completed triage cycles. Not a bug — inherently requires data to accumulate.

---

### Audit

**Status: ⚠️ Empty (expected while platform is new)**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| Audit Log | ⚠️ Empty | "No actions recorded. Agent actions for this time range will appear here once incidents are triaged." |
| Agent Traces | ⚠️ Empty | "No traces captured yet — agent traces are recorded automatically when conversations run" |

**Expected state:** No incidents have been triaged end-to-end, so both audit log and agent traces are empty. Not a bug.

---

### Admin

**Status: ⚠️ Subscriptions not synced**

| Sub-tab | Status | Notes |
|---------|--------|-------|
| Subscriptions | ❌ 0 subscriptions | "No subscriptions found. Click Sync Now to discover subscriptions." Synced timestamp shows "-1s ago" suggesting the sync call may be failing silently. |
| Settings | ✅ | 0 remediation policies — empty by design (none created yet) |
| Tenant & Admin | ✅ | 1 tenant (xtech-sg) with correct subscription GUID and CIS framework |

**Subscriptions issue:** The "Last synced: -1s ago" combined with 0 subscriptions after page load suggests the auto-sync on load is either failing or the backend isn't returning subscription data. Clicking "Sync Now" manually may resolve it. If not, the `/api/v1/subscriptions/sync` endpoint needs investigation.

---

## Priority Action Items

### ✅ Fixed (2026-04-17)
1. ~~**Operations → SLA: "Failed to fetch"**~~ — **FIXED**: SLA endpoint was working; root cause was correlations/groups 404 polluting error state. Registered `cross_sub_endpoints` router in main.py.
2. ~~**Admin → Subscriptions: 0 subscriptions**~~ — **FIXED**: Replaced broken ARG KQL query (`Resources` table has no subscription resources) with `azure-mgmt-subscription` SubscriptionClient. Now returns 1 subscription.

### 🟡 Configuration gaps (require setup, not code changes)
3. **Security Score** — Enable Defender for Cloud + grant Security Reader role to API gateway MI
4. **Change → Deployments** — Wire up GitHub webhook to `/api/v1/deployments`

### 🔵 Expected empty states (no action needed yet)
5. **Dashboard KPIs** — Will populate once incidents are triaged
6. **Audit Log / Agent Traces** — Will populate with first triage cycle
7. **Operations → Observability** — Needs incidents + Application Insights check
8. **Operations → Quality** — Accumulates over time
9. **Scan-on-demand sections** (Network peerings/LBs/PEs, AZ Coverage, Identity Risk, Backup, Storage Security) — Click "Scan Now" to populate
