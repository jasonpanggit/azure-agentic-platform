# Phase 4: Detection Plane - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 04-detection-plane
**Areas discussed:** Fabric Terraform module design, KQL schema & classify_domain() logic, Activator → API gateway call path, Alert deduplication strategy

---

## Fabric Terraform Module Design

### Q1: Fabric module structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single fabric module | One `terraform/modules/fabric/` provisions all: capacity, Eventhouse, Activator, OneLake | ✓ |
| Three separate Fabric modules | `fabric-capacity/`, `eventhouse/`, `activator/` as separate modules | |
| Terraform Event Hub only, Fabric manual | Terraform only for Event Hub; Fabric resources provisioned manually | |

**User's choice:** Single fabric module (Recommended)
**Notes:** Standard per-domain module pattern; simpler, one apply.

---

### Q2: Fabric capacity provisioning

| Option | Description | Selected |
|--------|-------------|----------|
| Provision capacity in Terraform | Capacity (F2/F4 SKU) provisioned inside the fabric module — fully reproducible IaC | ✓ |
| Reference pre-existing capacity | Module references an already-existing capacity by name/ID | |

**User's choice:** Provision capacity in Terraform (Recommended)
**Notes:** Full IaC reproducibility preferred.

---

## KQL Schema & classify_domain() Logic

### Q1: classify_domain() primary signal

| Option | Description | Selected |
|--------|-------------|----------|
| ARM resource_type | Domain inferred from resource_type prefix — most deterministic | ✓ |
| Alert rule name prefix | Domain inferred from alert rule name (e.g., 'VM-*' → compute) | |
| Lookup table combining both | KQL datatable maps resource_type + alert rule patterns — covers Arc ambiguity | |

**User's choice:** ARM resource_type (Recommended)
**Notes:** Most deterministic; Claude's discretion for Arc edge cases.

---

### Q2: classify_domain() fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Fallback to SRE | Unclassifiable alerts route to SRE agent (domain='sre') | ✓ |
| Park as unclassified, alert operator | domain='unclassified', Activator rule alerts operator — no auto thread | |
| Drop unclassified alerts | Silently drop alerts that can't be classified | |

**User's choice:** Fallback to SRE (Recommended)
**Notes:** Nothing dropped; SRE is the catch-all domain agent.

---

### Q3: KQL table pipeline depth

| Option | Description | Selected |
|--------|-------------|----------|
| RawAlerts → EnrichedAlerts → DetectionResults | Three tables; enrichment and classification in separate update policies | ✓ |
| Single-pass: RawAlerts → DetectionResults | One update policy for both enrichment and classification | |

**User's choice:** Three-table pipeline (Recommended)
**Notes:** Matches DETECT-002 exactly; easier to debug intermediate states.

---

## Activator → API Gateway Call Path

### Q1: Fabric User Data Function authentication

| Option | Description | Selected |
|--------|-------------|----------|
| Service Principal (client credentials) | Dedicated app registration; client_id/secret in Key Vault; Bearer token call | ✓ |
| Fabric workspace managed identity | Fabric managed identity for outbound calls — still maturing | |
| Shared API key (contradicts D-10) | Long-lived API key — contradicts Phase 2 Entra-auth decision | |

**User's choice:** Service Principal (client credentials) (Recommended)
**Notes:** Client credentials flow is the standard for non-interactive callers; Key Vault secret injection aligns with existing platform patterns.

---

### Q2: Activator trigger path

| Option | Description | Selected |
|--------|-------------|----------|
| Activator → User Data Function → gateway | Single trigger; Python function formats and POSTs to gateway | ✓ |
| Activator → Power Automate → gateway | Power Automate HTTP action; no custom Python required | |

**User's choice:** Activator → User Data Function → gateway (Recommended per DETECT-003)
**Notes:** Aligns with DETECT-003; avoids Power Automate connector dependency.

---

## Alert Deduplication Strategy

### Q1: Cosmos DB incidents partition key

| Option | Description | Selected |
|--------|-------------|----------|
| resource_id | One partition per Azure resource; efficient for open-incident check | ✓ |
| domain | Collocates all incidents per domain; hot partitions risk | |
| subscription_id | Scopes by subscription; uneven partition sizes | |

**User's choice:** resource_id as partition key (Recommended)
**Notes:** Most efficient for DETECT-005 layer 2 open-incident query.

---

### Q2: Dedup layer 2 — correlated alert handling

| Option | Description | Selected |
|--------|-------------|----------|
| Add to correlated_alerts array | New alert appended to existing incident's correlated_alerts; operator sees correlated count | ✓ |
| Write suppressed record referencing parent | New Cosmos record with status='suppressed' and parent incident_id reference | |
| Drop the duplicate alert silently | Silently discard; only original incident record exists | |

**User's choice:** Add to correlated_alerts array on existing incident (Recommended)
**Notes:** Preserves signal; operator sees correlated alert frequency; Orchestrator gets all context.

---

## Claude's Discretion

- Exact Fabric capacity SKU per environment
- KQL `EnrichedAlerts` resource inventory join specifics
- Fabric User Data Function Python packaging approach
- Event Hub partition count per environment
- Activity Log export pipeline to OneLake specifics
- `classify_domain()` Arc edge case disambiguation beyond resource_type mappings

## Deferred Ideas

- Fabric IQ semantic layer — Preview, keep off critical path; revisit Phase 7 / v2
- Alert suppression rule management UI — v2 scope
- Event Hub consumer group isolation — defer if second consumer added
- Fabric workspace managed identity for outbound calls — re-evaluate at GA
