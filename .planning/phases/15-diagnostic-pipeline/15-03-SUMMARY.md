# Plan 15-03 Summary: Enrich IncidentSummary Model

**Status:** COMPLETE
**Commit:** `3cfdcf0`
**Branch:** `gsd/phase-15-diagnostic-pipeline`
**Date:** 2026-04-01

---

## What Was Done

### Task 1 — Extend `IncidentSummary` (`services/api-gateway/models.py`)

Added 5 new optional fields to `IncidentSummary`:
- `resource_name: Optional[str]` — last segment of the ARM resource ID
- `resource_group: Optional[str]` — resource group name from the ARM resource ID
- `resource_type: Optional[str]` — e.g. `"microsoft.compute/virtualmachines"` (lowercased)
- `investigation_status: Optional[str]` — `pending | evidence_ready | investigating | resolved`
- `evidence_collected_at: Optional[str]` — ISO 8601 timestamp when evidence was gathered

### Task 2 — Add `_parse_resource_id()` helper (`services/api-gateway/incidents_list.py`)

New pure function that extracts `resource_name`, `resource_group`, `resource_type`, and `subscription_id` from a standard ARM resource ID of the form:
```
/subscriptions/{sub}/resourceGroups/{rg}/providers/{namespace}/{type}/{name}
```
- Returns all-`None` dict for `None` or empty input (safe for missing data)
- Fallback: uses last non-empty path segment as `resource_name` for non-standard paths
- Type comparisons done on lowercased path; original-case values returned for names

### Task 3 — Update `list_incidents()` (`services/api-gateway/incidents_list.py`)

- Extended the Cosmos query `SELECT` to also fetch `c.affected_resources`, `c.investigation_status`, `c.evidence_collected_at`
- After the subscription filter, enriches each document with `_parse_resource_id()` results
- Falls back to `doc.get("affected_resources")[0]["resource_id"]` when top-level `resource_id` is absent
- `investigation_status` defaults to `"pending"` when not present in the document

### Task 4 — Update `AlertFeed.tsx` (`services/web-ui/components/AlertFeed.tsx`)

- Extended `Incident` TypeScript interface with all 5 new optional fields
- Added **Resource Group** column and **Investigation** column to both the loading skeleton and the data table
- Resource column: shows `resource_name` (truncated to 20 chars) when available; falls back to title/resource_id/incident_id
- Investigation column: shows green **"Evidence Ready"** badge when `investigation_status === 'evidence_ready'`; shows other statuses as plain badge; shows `—` for `pending`/missing

### Task 5 — Unit Tests (`services/api-gateway/tests/test_incidents_list.py`)

Added 8 new tests in `TestParseResourceId`:
1. `test_parse_resource_id_vm` — standard VM ARM ID
2. `test_parse_resource_id_storage` — storage account ARM ID
3. `test_parse_resource_id_none` — `None` input → all-None dict
4. `test_parse_resource_id_malformed` — `/invalid/path` → fallback last segment
5. `test_parse_resource_id_empty_string` — `""` input → all-None dict
6. `test_parse_resource_id_key_vault` — Key Vault ARM ID
7. `test_parse_resource_id_nsg` — NSG ARM ID
8. `test_incident_summary_has_new_fields` — validates all 5 new model fields

---

## Verification

```
34 passed in 0.13s   (services/api-gateway/tests/test_incidents_list.py)
npx tsc --noEmit     exits 0 (services/web-ui)
```

All 26 pre-existing tests continue to pass; 8 new tests added.

---

## Success Criteria — All Met

- [x] `IncidentSummary` has 5 new optional fields
- [x] `_parse_resource_id()` correctly parses standard ARM resource IDs
- [x] `list_incidents()` populates new fields from Cosmos documents
- [x] AlertFeed shows `resource_name` and `resource_group` columns (shows `—` when null)
- [x] AlertFeed shows "Evidence Ready" badge when `investigation_status === 'evidence_ready'`
- [x] AlertFeed TypeScript interface updated with all new fields
- [x] 8 unit tests pass for `_parse_resource_id` (exceeds 5+ requirement)
- [x] Single atomic commit (`3cfdcf0`)
- [x] SUMMARY.md created
