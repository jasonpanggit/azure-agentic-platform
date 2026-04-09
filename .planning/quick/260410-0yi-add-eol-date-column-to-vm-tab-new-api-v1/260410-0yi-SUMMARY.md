# Summary: Add EOL Date Column to VM Tab

**Task ID:** 260410-0yi
**Branch:** `gsd/add-eol-date-column-to-vm-tab`
**Commits:** 3

---

## What Changed

### Task 1: Backend — `POST /api/v1/vms/eol` endpoint
- **Created** `services/api-gateway/eol_endpoints.py` — new FastAPI router with batch EOL lookup
  - `_parse_os_for_eol()` normalises OS display names to endoflife.date product/cycle slugs
  - Supports Windows Server 2008–2025 (including R2 variants) and Ubuntu
  - Cache-first: queries `eol_cache` PostgreSQL table (24h TTL), falls back to endoflife.date API
  - Module-level `asyncpg` and `httpx` imports with try/except (project SDK scaffold pattern)
  - Tool function never raises — returns structured null-field results on any error
- **Modified** `services/api-gateway/main.py` — imported and registered `eol_router`
- **Modified** `services/api-gateway/requirements.txt` — added `httpx>=0.27.0`

### Task 2: Frontend — proxy route + EOL Date column
- **Created** `services/web-ui/app/api/proxy/vms/eol/route.ts` — POST proxy route following existing pattern (getApiGatewayUrl + buildUpstreamHeaders + AbortSignal.timeout(15000))
- **Modified** `services/web-ui/components/VMTab.tsx`:
  - Added `eolMap` state (`Record<string, EolEntry>`)
  - After VM fetch, collects unique `os_name` values and fires POST to `/api/proxy/vms/eol`
  - Added "EOL Date" column between "OS" and "Type" columns
  - Red "EOL" badge using `color-mix(in srgb, var(--accent-red) 15%, transparent)` for past-EOL VMs
  - Formatted "MMM YYYY" date for active-support VMs
  - "—" for unrecognised OS names
  - All styling uses CSS semantic tokens — no hardcoded Tailwind colours

### Task 3: Tests — 20 unit tests
- **Created** `services/api-gateway/tests/test_eol_endpoints.py`
  - 11 `_parse_os_for_eol` normalisation tests (Windows Server variants, Ubuntu, unknown, empty, case-insensitive)
  - 9 endpoint tests: empty input, unrecognised OS, cache hit, cache miss + API fallback, API failure, DB connection failure, deduplication, boolean EOL, mixed input

---

## Verification

| Check | Result |
|-------|--------|
| `pytest services/api-gateway/tests/test_eol_endpoints.py` | 20/20 passed |
| `pytest services/api-gateway/tests/` | 697 passed, 2 skipped, 0 failures |
| `npx tsc --noEmit` | Zero TypeScript errors |
| No imports from `agents/eol/tools.py` | Confirmed |
| CSS uses `var(--accent-*)` semantic tokens | Confirmed |
| No `console.log` in committed code | Confirmed |
| No hardcoded Tailwind colours | Confirmed |
