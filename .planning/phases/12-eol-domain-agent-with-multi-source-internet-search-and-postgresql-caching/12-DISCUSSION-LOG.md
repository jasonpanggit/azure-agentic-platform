# Phase 12: EOL Domain Agent - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-31
**Phase:** 12-eol-domain-agent-with-multi-source-internet-search-and-postgresql-caching
**Areas discussed:** EOL data sources, Software scope, Cache design, Remediation posture, Alerting behavior

---

## EOL Data Sources

| Option | Description | Selected |
|--------|-------------|----------|
| endoflife.date API only | Single well-maintained REST API covering 200+ products. Simple, consistent, free. | |
| endoflife.date + MS Lifecycle API | Two sources — MS API for authoritative Microsoft product data. | ✓ |
| All three (endoflife.date + MS + NVD) | Adds NVD cross-reference for CVE exposure on EOL products. | |

**User's choice:** endoflife.date + MS Lifecycle API

**Follow-up — source routing:**

| Option | Description | Selected |
|--------|-------------|----------|
| Silent fallback to endoflife.date | If MS API has no data, fall through silently. | |
| Always query both, merge results | Query both for all products, deduplicate by name+version. | |
| Source routing by product type | MS API for Microsoft products, endoflife.date for everything else. | ✓ |

**User's choice:** Source routing by product type (Recommended)

---

## Software Scope

| Option | Description | Selected |
|--------|-------------|----------|
| OS + runtimes + databases + K8s | OS, .NET/Python/Node.js, SQL Server/PostgreSQL/MySQL, K8s node pools. | ✓ |
| OS and Windows runtimes only | Narrowest — matches what Azure Update Manager surfaces. | |
| All of the above + container images | Adds container base image EOL tracking from Arc K8s workloads. | |

**User's choice:** OS + runtimes + databases + K8s (Recommended)

**Follow-up — inventory discovery:**

| Option | Description | Selected |
|--------|-------------|----------|
| ARG + ConfigurationData (same as patch agent) | Same pattern as patch agent — consistent, proven. | ✓ |
| ARG + Arc metadata only | Simpler but misses installed software inventory. | |
| Accept inventory from orchestrator input | External CMDB / ServiceNow input model. | |

**User's choice:** ARG + ConfigurationData (same pattern as patch agent)

---

## Cache Design

**TTL:**

| Option | Description | Selected |
|--------|-------------|----------|
| 24 hours | Fresh daily — good balance of freshness vs. upstream load. | ✓ |
| 7 days | Weekly refresh — very low API load. | |
| Configurable (default 24h) | Env var–controlled TTL. | |

**User's choice:** 24 hours (Recommended)

**Cache miss behavior:**

| Option | Description | Selected |
|--------|-------------|----------|
| Serve stale, refresh in background | Background refresh on TTL expiry — fast UX, complex. | |
| Synchronous refresh on cache miss | Query upstream before responding — simpler. | ✓ |
| Always serve cache, manual refresh only | Stale-on-demand model. | |

**User's choice:** Synchronous refresh on cache miss (Recommended)

**Cache schema:**

| Option | Description | Selected |
|--------|-------------|----------|
| Flat table: product + version + eol_date + source | Simple, queryable by product+version. | ✓ |
| Per-source tables | Cleaner separation, more complex joins. | |
| JSONB blob per product | Flexible but hard to query specific fields. | |

**User's choice:** Flat table: product + version + eol_date + source (Recommended)

---

## Remediation Posture

**Remediation type:**

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only triage only | Report EOL status + docs links. No proposals. | |
| Report + propose upgrade plan | EOL report + `plan_software_upgrade` action. Requires approval. | ✓ |
| Report + propose upgrade + emergency action | Adds emergency isolation for actively-exploited EOL. | |

**User's choice:** Report + propose upgrade plan (Recommended)

**Risk level:**

| Option | Description | Selected |
|--------|-------------|----------|
| All medium risk | Uniform risk level for upgrade proposals. | |
| Already EOL = high, within 90 days = medium | Urgency-based risk scaling. | ✓ |
| Risk by product type | OS upgrades = high, runtime = medium. | |

**User's choice:** Already EOL = high, within 90 days = medium (Recommended)

---

## Alerting Behavior

*User raised this via notes: "alert when EOL dates are near"*

**Scan mode:**

| Option | Description | Selected |
|--------|-------------|----------|
| Reactive only | Triage on incident handoff. No proactive scanning. | |
| Proactive scan + incident creation | Scheduled scan that creates incidents for EOL findings. | |
| Both reactive + proactive scan | Handles incident triage AND has a proactive scan tool. | ✓ |

**User's choice:** Both reactive + proactive scan (Recommended)

**Alert thresholds:**

| Option | Description | Selected |
|--------|-------------|----------|
| 90/60/30 day thresholds | Three alerting windows — standard enterprise lifecycle. | ✓ |
| 90 days only | Single notification. | |
| Configurable threshold | Env var–controlled. | |

**User's choice:** 90/60/30 day thresholds (Recommended)

---

## Claude's Discretion

- Exact KQL for ARG inventory queries
- HTTP client retry/timeout strategy
- Product slug normalization (ARG OS name → endoflife.date slug mapping)
- MS Lifecycle API endpoint and auth details
- Proactive scan trigger infrastructure
- Incident dedup logic for proactive scan
- Agent system prompt text
- Test fixture design
- Terraform RBAC role
- `EOL_AGENT_ID` env var name
- PostgreSQL index strategy for `eol_cache`

## Deferred Ideas

None raised during discussion.
