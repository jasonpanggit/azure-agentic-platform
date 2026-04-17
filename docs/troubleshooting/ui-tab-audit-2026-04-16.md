# UI Tab Audit — 2026-04-16

Automated audit of all 24 tabs on the production web UI:
`https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io`

---

## Summary

All 24 tabs are affected by the same 5 root causes. No tab is fully clean.

| Priority | Root Cause | Affected Tabs | Status |
|----------|-----------|--------------|--------|
| 🔴 P1 | `No VMs found in selected subscriptions` — Azure VMs not loading | All 24 | Open |
| 🔴 P1 | `/api/proxy/admin/remediation-policies` → **502** — backend crashing | All 24 | Open |
| 🔴 P1 | `/api/proxy/aks` → **502** — AKS backend crashing | All 24 | Open |
| 🔴 P2 | `/api/proxy/ops/patterns` → **404** — proxy route missing | Ops, Audit, FinOps, Patch, Deployments, Quality | Open |
| 🔴 P2 | `/api/proxy/quality/feedback` → **404** — proxy route missing | Quality | Open |
| 🟡 P3 | `No SLA definitions found` — not seeded via admin API | All 24 | Config needed |
| 🟡 P3 | `NaN` values in Runbooks, Admin, Remediation Policies, Policy Suggestions | 4 tabs | Open |

---

## Root Cause Details

### RC-1 — `No VMs found in selected subscriptions` (All 24 tabs)

Every tab shows this empty state for the Azure VM table. Arc VMs load correctly (8-row
`Machine/Type/OS/Compliance` table from Arc agent). The Azure VM proxy endpoint
(`/api/proxy/vms`) either returns empty or is failing silently, which collapses all
VM-derived metrics to 0 across the board (~70 zero-valued fields per tab).

**Evidence:**
```
Empty state: "No VMs found in selected subscriptions"
~70 numeric fields showing 0 on every tab
```

**Suspect:** `GET /api/proxy/vms` — check API gateway routing to compute agent and
whether the subscription filter is being applied before the upstream call returns data.

---

### RC-2 — `/api/proxy/admin/remediation-policies` → 502 (All 24 tabs)

The "Remediation Policies (0)" widget is rendered in the global sidebar/header and
appears on every tab. The underlying API call returns `502 Bad Gateway`, meaning the
upstream Container App (`ca-api-gateway-prod` or the admin service) is crashing or
unreachable.

**Evidence:**
```
502 https://.../api/proxy/admin/remediation-policies
Section heading "Remediation Policies (0)" visible on all 24 tabs
```

**Suspect:** Check `ca-api-gateway-prod` logs for the `/admin/remediation-policies`
handler. Likely an unhandled exception or missing route in the FastAPI gateway.

---

### RC-3 — `/api/proxy/aks` → 502 (All 24 tabs)

The AKS data feed returns `502 Bad Gateway`.

**Evidence:**
```
502 https://.../api/proxy/aks?subscriptions=4c727b88-12f4-4c91-9c2b-372aab3bbae9
"No AKS clusters found in selected subscriptions" (Ops tab)
```

**Suspect:** Check `ca-api-gateway-prod` logs for the `/aks` handler. The AKS agent
or the gateway route for AKS may be failing.

---

### RC-4 — `/api/proxy/ops/patterns` → 404 (6 tabs)

The frontend calls this route on: Ops, Audit, FinOps, Patch, Deployments, Quality tabs.
The route does not exist in the Next.js proxy layer — no `app/api/proxy/ops/patterns/`
route file was found.

**Evidence:**
```
404 https://.../api/proxy/ops/patterns  (repeated 5×)
```

**Suspect:** A frontend component was written to call `/api/proxy/ops/patterns` but
the corresponding Next.js route handler was never implemented. Need to either:
- Create `app/api/proxy/ops/patterns/route.ts`, or
- Remove the frontend call if the feature was deferred.

---

### RC-5 — `/api/proxy/quality/feedback` → 404 (Quality tab)

Same class of issue as RC-4 — the proxy route file is missing.

**Evidence:**
```
404 https://.../api/proxy/quality/feedback
```

**Suspect:** Quality tab's feedback section calls an unimplemented proxy route. Need
`app/api/proxy/quality/feedback/route.ts` or remove the call.

---

### RC-6 — SLA definitions not seeded (All 24 tabs)

Not a backend failure — the SLA engine is working but no definitions have been
created. Requires manual seeding.

**Evidence:**
```
"No SLA definitions found. Create one via the admin API."
```

**Action:** Follow `docs/ops/detection-plane-activation.md` or call
`POST /api/v1/sla-definitions` to seed default SLA targets.

---

### RC-7 — `NaN` values (Runbooks, Admin, Remediation Policies, Policy Suggestions)

4 tabs show `NaN` in 2–6 metric fields. Caused by arithmetic on undefined/null values
returned from a failing upstream (likely RC-2). Will likely self-resolve once RC-2 is
fixed. If not, guard the calculation with `|| 0` or `isNaN()` check.

**Evidence:**
```
Runbooks:             NaN × 2
Admin:                NaN × 6
Remediation Policies: NaN × 6
Policy Suggestions:   NaN × 6
```

---

## Per-Tab Status

| Tab | VMs Empty | Remediation 502 | AKS 502 | ops/patterns 404 | quality/feedback 404 | NaN |
|-----|:---------:|:---------------:|:-------:|:----------------:|:--------------------:|:---:|
| Ops | ✗ | ✗ | ✗ | ✗ | | |
| Alerts | ✗ | ✗ | ✗ | | | |
| Audit | ✗ | ✗ | ✗ | ✗ | | |
| Topology | ✗ | ✗ | ✗ | | | |
| Resources | ✗ | ✗ | ✗ | | | |
| VMs | ✗ | ✗ | ✗ | | | |
| VMSS | ✗ | ✗ | ✗ | | | |
| AKS | ✗ | ✗ | ✗ | | | |
| FinOps | ✗ | ✗ | ✗ | ✗ | | |
| Observability | ✗ | ✗ | ✗ | | | |
| SLA | ✗ | ✗ | ✗ | | | |
| Capacity | ✗ | ✗ | ✗ | | | |
| Quotas | ✗ | ✗ | ✗ | | | |
| Patch | ✗ | ✗ | ✗ | ✗ | | |
| Compliance | ✗ | ✗ | ✗ | | | |
| Security Score | ✗ | ✗ | ✗ | | | |
| Runbooks | ✗ | ✗ | ✗ | | | ✗ |
| IaC Drift | ✗ | ✗ | ✗ | | | |
| Deployments | ✗ | ✗ | ✗ | ✗ | | |
| Quality | ✗ | ✗ | ✗ | ✗ | ✗ | |
| Settings | ✗ | ✗ | ✗ | | | |
| Admin | ✗ | ✗ | ✗ | | | ✗ |
| Remediation Policies | ✗ | ✗ | ✗ | | | ✗ |
| Policy Suggestions | ✗ | ✗ | ✗ | | | ✗ |

---

## What Is Working

- Arc VM table loads correctly (8 machines with OS, Compliance, patch data)
- Resources table loads (492 resources)
- VMSS table loads (2 scale sets)
- Quota table loads (50 quota entries with Used/Limit values)
- IP Address Space / Capacity table loads (37 VNet/Subnet rows)
- IaC Drift table loads (1 row: "No drift detected")
- Deployments table loads (1 row: "No deployments recorded")
- Patch table loads (8 Arc machines with patch compliance columns)

---

## Recommended Fix Order

1. **Fix RC-2 + RC-3** (502s) — investigate `ca-api-gateway-prod` logs for
   `/admin/remediation-policies` and `/aks` handlers
2. **Fix RC-1** (VMs empty) — check `/api/proxy/vms` gateway route and compute agent
3. **Fix RC-4 + RC-5** (404s) — implement or remove missing proxy routes
4. **Fix RC-7** (NaN) — guard arithmetic in the affected components
5. **Seed RC-6** (SLA) — run SLA seeding script per ops runbook
