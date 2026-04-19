---
phase: 104
plan: 1
status: complete
files_created:
  - services/api-gateway/firewall_service.py
  - services/api-gateway/firewall_endpoints.py
  - services/web-ui/components/FirewallTab.tsx
  - services/web-ui/app/api/proxy/firewall/rules/route.ts
  - services/web-ui/app/api/proxy/firewall/audit/route.ts
  - services/api-gateway/tests/test_firewall_service.py
  - services/api-gateway/tests/test_firewall_endpoints.py
files_modified:
  - services/api-gateway/main.py
  - services/web-ui/components/ResourcesHubTab.tsx
tests_added: 22
---
# Phase 104-1 Summary

Built the Azure Firewall tab under the Resources Hub, backed by live ARG queries with a 900-second TTL cache.

## What was built

**Backend (`firewall_service.py`)**
- `FirewallRule` and `FirewallAuditFinding` dataclasses
- `get_firewall_rules()` — joins `microsoft.network/azurefirewalls` with `microsoft.network/firewallpolicies` rule collections via two ARG KQL queries
- `get_firewall_audit()` — classifies rules into findings:
  - `too_wide_source`: wildcard/0.0.0.0/0 source → critical (Allow) or high (Deny)
  - `too_wide_destination`: wildcard destination address + wildcard ports → high
  - `too_wide_ports`: wildcard or 0-65535 ports on Allow rules → high
  - `overlap_shadowed`: same source+dest+port fingerprint at different collection priorities → medium
- Both functions never raise; return structured empty results on failure

**Endpoints (`firewall_endpoints.py`)**
- `GET /api/v1/firewall/rules` — firewalls + rules list (900s TTL cache)
- `GET /api/v1/firewall/audit` — classified findings with summary counts; optional `severity` filter with 422 validation
- Registered in `main.py`

**Proxy routes**
- `app/api/proxy/firewall/rules/route.ts`
- `app/api/proxy/firewall/audit/route.ts`
- Both follow standard pattern: `getApiGatewayUrl()` + `buildUpstreamHeaders()` + `AbortSignal.timeout(15000)`

**Frontend (`FirewallTab.tsx`)**
- Dual-view toggle: Rules | Audit
- Rules view: table with Firewall, Policy, Collection, Rule Name, Type, Source, Destination, Ports, Action columns
- Audit view: table with Severity badge, Firewall, Rule, Issue type + detail, Remediation (tooltip on hover)
- `useEffect` fetches both views on mount; `setInterval` polls every 10 minutes
- Severity badges use CSS tokens (`color-mix(in srgb, var(--accent-*) 15%, transparent)`) — no hardcoded Tailwind colors
- Empty state: "No Azure Firewalls found across monitored subscriptions" — no scan button
- Wired into `ResourcesHubTab.tsx` as `{ id: 'firewall', label: 'Firewall', icon: Flame }`

**Tests: 22 passing**
- 16 service tests: classification scenarios (too_wide_source critical/high, too_wide_ports, clean rule, too_wide_destination, deny rule), overlap detection, empty/failure paths
- 6 endpoint tests: rules 200, audit 200, severity filter cache key verification, invalid severity 422, empty result
