# Debug: vm-tab-eol-date-blank

## Summary

VM tab EOL Date column exists but is always blank -- never shows data.

## Investigation (Round 3) -- 2026-04-12

### Prior fixes that didn't work

1. **Round 1:** Fixed `_parse_os_for_eol()` slug from `windows-server-{year}` to `windows-server` + year as cycle. Tests passed, deployed.
2. **Round 2:** Fixed stale null cache rows being served as hits. Tests passed, deployed.

**EOL date was STILL blank after both fixes.**

### End-to-end trace (Round 3)

| Layer | Status | Finding |
|-------|--------|---------|
| **Frontend (`VMTab.tsx`)** | OK | Correctly sends `POST /api/proxy/vms/eol` with `{ os_names: [...] }`, builds `eolMap[os_name]`, renders eol_date/is_eol. Field names match. |
| **Proxy route (`app/api/proxy/vms/eol/route.ts`)** | OK | Correctly proxies POST to `${apiGatewayUrl}/api/v1/vms/eol` with Content-Type and Auth headers. 15s timeout. Graceful `{results:[]}` on failure. |
| **Backend endpoint (`eol_endpoints.py`)** | DESIGN FLAW | The endoflife.date API call was **inside** the `try` block that required a successful PostgreSQL connection. If DB connection failed, the entire for-loop was skipped and all results returned as nulls. The API fallback was dead code when DB was unreachable. |
| **Terraform tfvars** | **ROOT CAUSE** | `terraform.tfvars` line 67 had `pgvector_connection_string = ""` which **overwrote** the valid DSN from `credentials.tfvars`. The CI workflow loads `-var-file credentials.tfvars -var-file terraform.tfvars` -- last file wins. The api-gateway Container App in prod had NO PostgreSQL env var set. |
| **OS normalization** | OK | `normalize_os()` -> `_parse_os_for_eol()` mapping is correct for all supported OS types. |
| **Auth** | OK | EOL endpoint has no `Depends(verify_token)`. Auth mode is `disabled` in prod. |
| **Field name alignment** | OK | Backend returns `EolResult.os_name`, frontend reads `entry.os_name` and `eolMap[vm.os_name]`. Exact match. |

### Root causes (confirmed)

#### Primary: `terraform.tfvars` overwrites `credentials.tfvars` DSN

```
# credentials.tfvars (loaded first)
pgvector_connection_string = "postgresql://aap_admin:...@aap-postgres-prod..."

# terraform.tfvars (loaded second -- WINS)
pgvector_connection_string = ""
```

The CI apply command: `terraform apply ... -var-file credentials.tfvars -var-file terraform.tfvars`

Terraform variable precedence: last `-var-file` wins. So the empty string in `terraform.tfvars` overwrites the valid DSN from `credentials.tfvars`.

The dynamic env block in `agent-apps/main.tf` line 218 only injects `PGVECTOR_CONNECTION_STRING` when the value is non-empty:
```hcl
for_each = each.key == "api-gateway" && var.pgvector_connection_string != "" ? [1] : []
```

Result: api-gateway Container App has NO PostgreSQL env var. `_resolve_dsn()` throws `RuntimeError`.

#### Secondary: Code design flaw -- API fallback requires DB

The old code structure:
```python
try:
    conn = await asyncpg.connect(dsn)   # <-- if this fails...
    for os_name in unique_names:        # <-- ...entire loop is skipped
        cached = await _lookup_cache(conn, ...)
        api_result = await _fetch_from_api(...)  # <-- dead code when DB fails
except Exception:
    # All results = unknowns
```

The endoflife.date API is a **public REST API** that requires no database. But the code made it unreachable when PostgreSQL was unavailable.

### Proof chain

1. `terraform.tfvars` sets `pgvector_connection_string = ""` (line 67)
2. CI loads it after `credentials.tfvars`, overwriting the valid DSN
3. `agent-apps/main.tf` dynamic block skips env injection (empty string)
4. api-gateway has no `PGVECTOR_CONNECTION_STRING`, no `POSTGRES_DSN`, no `POSTGRES_HOST`
5. `_resolve_dsn()` raises `RuntimeError("PostgreSQL not configured")`
6. Exception caught by outer `try/except`
7. `_fetch_from_api()` is never called
8. All results returned with `eol_date=None, is_eol=None`
9. Frontend renders "--" for every VM

## Fix (Round 3)

### 1. Remove empty override from terraform.tfvars

Removed `pgvector_connection_string = ""` from `terraform/envs/prod/terraform.tfvars`. Added comment warning not to set it here. The value from `credentials.tfvars` will now flow through correctly.

### 2. Decouple API fallback from DB connection

Refactored `batch_eol_lookup()` in `eol_endpoints.py`:
- DB connection is now attempted separately, before the main loop
- If DB fails, `conn` stays `None` and the loop proceeds
- Cache lookup is skipped when `conn is None` (with a guard)
- `_fetch_from_api()` is always reachable regardless of DB status
- Cache write is best-effort (only when `conn is not None`)

### 3. Updated tests

- Replaced `test_db_connection_failure_returns_unknowns` with three new tests:
  - `test_db_connection_failure_falls_through_to_api` -- DB down, API works -> valid EOL data
  - `test_db_and_api_both_fail_returns_unknowns` -- both down -> null fields
  - `test_dsn_not_configured_falls_through_to_api` -- no DSN at all, API works -> valid EOL data

## Files Changed

- `terraform/envs/prod/terraform.tfvars` -- removed `pgvector_connection_string = ""` override
- `services/api-gateway/eol_endpoints.py` -- decoupled API fallback from DB connection
- `services/api-gateway/tests/test_eol_endpoints.py` -- 3 new tests, 1 removed (net +2)

## Verification

- 29/29 unit tests pass (16 parse + 13 endpoint)
- The Terraform fix ensures the DSN reaches the api-gateway in prod
- The code fix ensures EOL data works even without any database

## Lesson

1. **Terraform var precedence kills silently.** When using multiple `-var-file` flags, the last one wins for conflicting keys. Never set sensitive variables to empty strings in the last-loaded tfvars file -- omit them entirely so earlier files provide the value.

2. **Optional dependencies must be optional in code, not just in comments.** If a feature has a cache layer and an API layer, a failure in the cache must not prevent the API from being called. Structure code so each layer can fail independently.
