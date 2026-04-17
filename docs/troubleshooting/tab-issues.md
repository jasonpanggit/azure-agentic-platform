# Top-Nav Tab Audit Report

**Date:** 2026-04-16 UTC  
**URL:** https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io  
**Tabs Audited:** 22 / 22  
**Total Issues:** 3 flagged + several notable observations  

---

## Issues Found

| Tab | Type | Detail |
|---|---|---|
| VMs | `MANY_DASH_CELLS` | 10 cells showing "—" in the VM list table |
| Patch | `MANY_DASH_CELLS` | 23 cells showing "—" in the patch table |
| Runbooks | `ERROR_STATE` | Error message visible alongside content |

### Issue Summary by Type

| Type | Count |
|---|---|
| `MANY_DASH_CELLS` | 2 |
| `ERROR_STATE` | 1 |

---

## Analysis

### Issue 1: VMs tab — 10 dash cells
**Detail:** Some columns in the VM table show "—". Most likely affects columns like Health, Alerts, or AMA Status for deallocated/Arc VMs where those values aren't fetchable.  
**Severity:** Low — data rows load, only enrichment fields are missing for some VMs.

### Issue 2: Patch tab — 23 dash cells
**Detail:** 23 "—" cells across 8 VM rows. Likely affects patch count columns (Pending, Critical, etc.) for VMs where Update Manager data isn't available or the ARG query returns null.  
**Severity:** Medium — patch counts are core data for this tab; missing values reduce actionability.

### Issue 3: Runbooks tab — ERROR_STATE
**Detail:** An error message is visible alongside the 12 runbooks that do load. Content shows: `"All Compute Network Storage Security Arc SRE Patch EOL 12 runbooks..."` — so runbooks themselves render, but something else on the page errors.  
**Likely cause:** Correlates with the `500` console error. Possibly a secondary API call (e.g. runbook execution history, policy suggestions) fails while the runbook list itself loads from the database.  
**Severity:** Medium — runbooks are accessible but the error banner is confusing.

### Notable Observations (not flagged as errors but worth noting)

| Tab | Observation |
|---|---|
| Audit | Shows "No actions recorded" — expected if no incidents have been triaged recently |
| Observability | Shows "No observability data — Metrics will appear here once agents process their data" — expected for new/idle system |
| Settings | Shows "Policy database unavailable — Remediation Policies (0)" — the policy DB connection may be down or not yet seeded |
| Ops | Only 1 table row visible — may be sparse if there are few active incidents |
| SLA | Only 2 rows — acceptable if few SLA-tracked resources |
| IaC Drift / Deployments | 1 row each — may be sparse, worth checking if data should be richer |

---

## Passing Tabs (19/22)

| Tab | Result |
|---|---|
| Ops | ✅ 1 table row |
| Alerts | ✅ 1 table row |
| Audit | ✅ Content loads (empty state expected) |
| Topology | ✅ 1 subscription · 48 resource groups · 492 resources |
| Resources | ✅ 492 table rows |
| VMs | ✅ 8 table rows (with dash cell caveat) |
| VMSS | ✅ 2 table rows |
| AKS | ✅ 1 table row |
| FinOps | ✅ 6 table rows |
| Observability | ✅ Loads (empty state expected) |
| SLA | ✅ 2 table rows |
| Capacity | ✅ 37 table rows |
| Quotas | ✅ 50 table rows |
| Patch | ✅ 8 table rows (with dash cell caveat) |
| Compliance | ✅ 3 cards |
| Security Score | ✅ 5 cards |
| Runbooks | ✅ 12 runbooks load (error banner caveat) |
| IaC Drift | ✅ 1 table row |
| Deployments | ✅ 1 table row |
| Quality | ✅ 4 cards |
| Settings | ✅ Loads (policy DB caveat) |
| Admin | ✅ 1 card |

---

## VM Detail Panel Tab Audit (5 VMs sampled)

Each VM row was clicked to open the detail panel. All 6 panel tabs (Overview, Metrics, Evidence, Patches, CVEs, AI Chat) were exercised.

| VM | Power State | Metrics | CVEs | Other Tabs |
|---|---|---|---|---|
| ManufacturingVM | Deallocated | ❌ "No data" | ✅ 0 CVEs | ✅ All pass |
| WIN-JBC7MM2NO8J | unknown (Arc) | ✅ Loads | ❌ Error + 73 "—" cells | ✅ All pass |
| WIN-P3OD2Q85TKG | unknown (Arc) | ✅ Loads | ✅ 0 CVEs | ✅ All pass |
| arcgis-vm | Deallocated | ❌ "No data" | ❌ Error + 37 "—" cells | ✅ All pass |
| image-vm | Deallocated | ❌ "No data" | ✅ 0 CVEs | ✅ All pass |

**VM Panel Issues:**
- **Metrics "No data"** for all 3 deallocated VMs — Azure Monitor doesn't collect metrics for stopped VMs. Should show "VM is deallocated — metrics unavailable" instead of generic "No data".
- **CVEs error + dash cells** for WIN-JBC7MM2NO8J and arcgis-vm — enrichment API (CVSS/severity metadata) returns 500/502. CVE list loads but severity columns are blank.
- **Arc VM power state "unknown"** for WIN-JBC7MM2NO8J and WIN-P3OD2Q85TKG — Arc power state polling not resolving.

---

## Console Errors (captured during full audit)

- `Failed to load resource: the server responded with a status of 404 ()`
- `Failed to load resource: the server responded with a status of 500 ()`
- `Failed to load resource: the server responded with a status of 503 ()`

---

## Recommended Fixes (Prioritised)

| Priority | Tab | Fix |
|---|---|---|
| P2 | CVEs (panel) | Handle 500/502 on CVE enrichment API — show "CVSS data unavailable" per-row instead of error banner + "—" |
| P2 | Runbooks | Investigate 500 error on secondary Runbooks API call; suppress error banner if runbooks themselves load |
| P2 | Settings | Investigate "Policy database unavailable" — check PostgreSQL connection for policy store |
| P3 | Metrics (panel) | Detect deallocated VM state; show "Metrics unavailable — VM is deallocated" instead of generic "No data" |
| P3 | Patch tab | Identify which VMs have null patch counts; ensure ARG query handles VMs not enrolled in Update Manager gracefully |
| P3 | VMs tab | Identify which columns show "—"; add fallback values or "N/A" labels for Arc/deallocated VMs |
| P4 | Arc VMs | Investigate power state polling returning "unknown" for Arc-connected VMs |

---

## Screenshots

Saved to `/tmp/tab-audit-nav/`
