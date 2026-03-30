# Phase 12: EOL Domain Agent — Research

**Researcher:** Claude
**Date:** 2026-03-31
**Status:** Complete

---

## Table of Contents

1. [endoflife.date API](#1-endoflifedate-api)
2. [Microsoft Product Lifecycle API](#2-microsoft-product-lifecycle-api)
3. [Source Routing Strategy](#3-source-routing-strategy)
4. [ARG Queries for OS/Software Inventory](#4-arg-queries-for-ossoftware-inventory)
5. [ConfigurationData Table (Log Analytics)](#5-configurationdata-table-log-analytics)
6. [PostgreSQL Cache Pattern](#6-postgresql-cache-pattern)
7. [Microsoft Agent Framework @tool Pattern](#7-microsoft-agent-framework-tool-pattern)
8. [Proactive Scan and Incident Creation](#8-proactive-scan-and-incident-creation)
9. [Existing Agent Structure (Template: Patch Agent)](#9-existing-agent-structure-template-patch-agent)
10. [httpx in the Codebase](#10-httpx-in-the-codebase)
11. [Test Patterns and conftest.py](#11-test-patterns-and-conftestpy)
12. [Terraform and CI/CD Changes](#12-terraform-and-cicd-changes)
13. [Risks and Open Questions](#13-risks-and-open-questions)

---

## 1. endoflife.date API

### Overview

Free, public REST API. No authentication required. No API key. ~394 products tracked.

**Base URL:** `https://endoflife.date/api/`

### Endpoints

| Endpoint | Description | Returns |
|----------|-------------|---------|
| `GET /api/all.json` | List all product slugs | `string[]` — flat array of slug strings |
| `GET /api/{product}.json` | All cycles for a product | `CycleInfo[]` — array of cycle objects, newest-first |
| `GET /api/{product}/{cycle}.json` | Single cycle detail | `CycleInfo` — single object |

### Response Schema (CycleInfo)

Verified by fetching actual responses for ubuntu, python, rhel, dotnet, windows-server, nodejs, azure-kubernetes-service, mssqlserver:

| Field | Type | Always present? | Notes |
|-------|------|-----------------|-------|
| `cycle` | `string` | Yes | Version/release identifier (e.g., "24.04", "3.12", "2022") |
| `releaseDate` | `string` (ISO date) | Yes | `YYYY-MM-DD` |
| `eol` | `string \| boolean` | Yes | ISO date string OR `true` (already EOL) / `false` (no planned EOL). **Polymorphic.** |
| `latest` | `string` | Yes | Most recent patch version (e.g., "3.12.13") |
| `latestReleaseDate` | `string` (ISO date) | Yes | Date of latest release |
| `lts` | `boolean \| string` | Yes | `true`/`false` for most; some products return a date string (Node.js returns LTS start date) |
| `support` | `string \| boolean` | Sometimes | Active/mainstream support end date. May be absent, may be `false` |
| `extendedSupport` | `string \| boolean` | Sometimes | Extended support end date, or `false` if none |
| `link` | `string \| null` | Sometimes | Release notes URL (optional, often absent) |
| `releaseLabel` | `string` | Rarely | Display label (dotnet uses `"__RELEASE_CYCLE__"` template) |
| `codename` | `string` | Ubuntu only | e.g., "Noble Numbat" |
| `pep` | `string` | Python only | e.g., "PEP-0693" |

### Product Slugs (In-Scope)

| Software | endoflife.date Slug | Verified? |
|----------|-------------------|-----------|
| Windows Server | `windows-server` | ✅ Yes — returns cycles for 2000, 2003, 2008, 2012, 2016, 2019, 2022, 2025 + SAC/AC |
| Ubuntu LTS | `ubuntu` | ✅ Yes — returns all LTS + non-LTS releases |
| RHEL | `rhel` | ✅ Yes — returns cycles 4–10 |
| .NET | `dotnet` | ✅ Yes — returns .NET 1.0–10, includes Core history |
| Python | `python` | ✅ Yes — returns 2.x and 3.x cycles |
| Node.js | `nodejs` | ✅ Yes — returns all major versions; `lts` is polymorphic (date or false) |
| PostgreSQL | `postgresql` | ✅ Yes (slug confirmed from all.json) |
| MySQL | `mysql` | ✅ Yes (slug confirmed from all.json) |
| Kubernetes (AKS) | `azure-kubernetes-service` | ✅ Yes — returns AKS-specific K8s version cycles with extendedSupport |
| Kubernetes (upstream) | `kubernetes` | ✅ Yes (slug confirmed from all.json) |
| SQL Server | `mssqlserver` | ✅ Yes — **NOT** `sql-server` or `sqlserver` (those return 404) |

### Rate Limits

- **No published rate limit.** The site is backed by a static site (GitHub Pages + CDN).
- Reasonable usage expected. Community reports indicate no issues at 1-2 req/s.
- **Recommended for EOL agent:** Max 5 requests/second with exponential backoff on 429/5xx. Cache eliminates most requests (24h TTL means ~1 query per product-version per day).

### Key Implementation Notes

1. **`eol` field is polymorphic:** Can be a date string (`"2028-10-31"`), `true` (already EOL with no fixed date), or `false` (no planned EOL). Must handle all three types.
2. **`lts` field is polymorphic for Node.js:** Returns the LTS start date (a string) instead of `true`.
3. **`support` and `extendedSupport` may be absent:** Not all products define these fields. Check with `field in response` before accessing.
4. **Cycle parameter is the `cycle` field value:** For `/api/{product}/{cycle}.json`, use the `cycle` string from the list response (e.g., `"3.12"` for Python, `"2022"` for Windows Server, `"24.04"` for Ubuntu).
5. **SQL Server slug is `mssqlserver`**, not `sql-server`. This is the most likely slug-mapping gotcha.

---

## 2. Microsoft Product Lifecycle API

### Overview

**A proper REST API exists** at `learn.microsoft.com/api/lifecycle/`. Documented at [Lifecycle API reference](https://learn.microsoft.com/en-us/lifecycle/reference). **No authentication required.** Rate limit: **1 request per second** (documented).

### Products Endpoint

**URL:** `GET https://learn.microsoft.com/api/lifecycle/products`

**OData Query Parameters:**

| Parameter | Type | Valid Values |
|-----------|------|-------------|
| `$orderBy` | string | `releaseDate` only |
| `$filter` | string | Properties: `productName`, `productFamilyName`, `productCategoryName`. Operators: `eq`, `contains` |
| `$expand` | string | `releases` only (includes releases inline) |
| `$skip` | int | Pagination offset |

**Response Schema:**

```json
{
  "products": [
    {
      "id": "uuid",
      "productName": "Windows Server 2016",
      "releaseDate": "2016-10-15T00:00:00.0000000+00:00",
      "lifecyclePolicy": "Fixed",
      "link": "https://learn.microsoft.com/lifecycle/products/windows-server-2016",
      "eolDate": "2022-01-11T00:00:00.0000000+00:00",
      "eosDate": "2027-01-12T00:00:00.0000000+00:00",
      "ltscDate": null,
      "productFamilyName": "Windows",
      "productCategoryName": "Windows"
    }
  ],
  "$count": 78,
  "$skip": 0,
  "$orderBy": "releaseDate"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `productName` | string | Full product name |
| `releaseDate` | DateOnly | Release date |
| `lifecyclePolicy` | string | `"Fixed"` or `"Modern"` |
| `link` | string | URL to product's lifecycle page |
| `eolDate` | DateOnly | End of mainstream support ("End of Life") |
| `eosDate` | DateOnly | Extended end of support |
| `ltscDate` | DateOnly/null | Long-Term Servicing Channel end date |
| `productFamilyName` | string | Product family |
| `productCategoryName` | string | Product category |

### Releases Endpoint

**URL:** `GET https://learn.microsoft.com/api/lifecycle/products/{product-slug}/releases`

The `{product-slug}` is the URL slug from the product's lifecycle page URL (case-insensitive). Examples: `windows-server-2016`, `sql-server-2019`, `windows-11`.

**Response:**

```json
{
  "releases": [
    {
      "id": "uuid",
      "releaseName": "Windows Server 2016",
      "releaseDate": "2016-10-15T00:00:00.0000000+00:00",
      "eolDate": "2022-01-11T00:00:00.0000000+00:00",
      "eosDate": "2027-01-12T00:00:00.0000000+00:00",
      "ltscDate": null
    }
  ],
  "$count": 8,
  "$skip": 0,
  "$orderBy": "releaseDate"
}
```

### Key Differences from endoflife.date

| Aspect | endoflife.date | MS Lifecycle API |
|--------|---------------|-----------------|
| Authentication | None | None |
| Rate limit | Undocumented (~5 rps safe) | 1 request/second (documented) |
| Product scope | 394+ products (cross-vendor) | Microsoft products only |
| Response format | Flat array of cycles | Paginated object with `$count`, `$skip` |
| EOL field | `eol` — polymorphic (date/bool) | `eolDate` — always DateOnly |
| Extended support | `extendedSupport` — polymorphic | `eosDate` — always DateOnly |
| Version identification | `cycle` string | `releaseName` string |
| Slug format | Lowercase-hyphenated (`mssqlserver`) | URL slug from lifecycle page (`sql-server-2019`) |

### MS Lifecycle Product Slugs (In-Scope)

These are the URL slugs to use in the `/products/{slug}/releases` endpoint:

| Product | MS Lifecycle Slug | Family Filter |
|---------|-----------------|---------------|
| Windows Server 2016 | `windows-server-2016` | `productFamilyName eq 'Windows'` |
| Windows Server 2019 | `windows-server-2019` | |
| Windows Server 2022 | `windows-server-2022` | |
| Windows Server 2025 | `windows-server-2025` | |
| SQL Server 2016 | `sql-server-2016` | `productFamilyName eq 'SQL Server'` |
| SQL Server 2019 | `sql-server-2019` | |
| SQL Server 2022 | `sql-server-2022` | |
| .NET 6 | `.net-6.0` | `productFamilyName eq 'Developer Tools'` |
| .NET 7 | `.net-7.0` | |
| .NET 8 | `.net-8.0` | |
| .NET 9 | `.net-9.0` | |

### Implementation Note: Use Products Filter, Not Per-Product Releases

The Products endpoint with `$filter=contains(productName,'Windows Server')` is more practical for bulk lookups than hitting per-product Release endpoints. Strategy:

1. **Cache all MS products once daily** using `GET /api/lifecycle/products?$expand=releases` (paginated, ~3-5 pages).
2. **Or query per product on cache miss** using `$filter=contains(productName,'Windows Server 2016')`.

For the EOL agent, per-product-on-cache-miss is simpler and aligns with the synchronous refresh design (D-10).

---

## 3. Source Routing Strategy

Per D-02:

**Microsoft Lifecycle API first** for:
- Windows Server (all versions)
- SQL Server (all versions)
- .NET / .NET Core (all versions)
- Exchange, IIS, Azure services (if added later)

**endoflife.date first** for:
- Ubuntu, RHEL (all Linux distros)
- Python, Node.js (all language runtimes not from MS)
- PostgreSQL, MySQL (all non-MS databases)
- Kubernetes / AKS

**Fallback:** If MS API returns no result for a Microsoft product, silently fall through to endoflife.date.

### Product Slug Normalization Map

The agent needs a mapping from ARG-discovered software names to API slugs:

```python
PRODUCT_SLUG_MAP = {
    # ARG OS name / ConfigurationData → (source, slug)
    # Windows Server
    "windows server 2012": ("ms-lifecycle", "windows-server-2012"),
    "windows server 2016": ("ms-lifecycle", "windows-server-2016"),
    "windows server 2019": ("ms-lifecycle", "windows-server-2019"),
    "windows server 2022": ("ms-lifecycle", "windows-server-2022"),
    "windows server 2025": ("ms-lifecycle", "windows-server-2025"),
    # SQL Server
    "sql server 2016": ("ms-lifecycle", "sql-server-2016"),
    "sql server 2019": ("ms-lifecycle", "sql-server-2019"),
    "sql server 2022": ("ms-lifecycle", "sql-server-2022"),
    # .NET
    "dotnet 6": ("ms-lifecycle", ".net-6.0"),
    "dotnet 7": ("ms-lifecycle", ".net-7.0"),
    "dotnet 8": ("ms-lifecycle", ".net-8.0"),
    # Linux
    "ubuntu": ("endoflife.date", "ubuntu"),
    "rhel": ("endoflife.date", "rhel"),
    "red hat enterprise linux": ("endoflife.date", "rhel"),
    # Runtimes
    "python": ("endoflife.date", "python"),
    "nodejs": ("endoflife.date", "nodejs"),
    "node.js": ("endoflife.date", "nodejs"),
    # Databases
    "postgresql": ("endoflife.date", "postgresql"),
    "mysql": ("endoflife.date", "mysql"),
    "mssqlserver": ("endoflife.date", "mssqlserver"),  # fallback for SQL Server
    # Kubernetes
    "kubernetes": ("endoflife.date", "azure-kubernetes-service"),
}
```

The normalization logic will need to:
1. Lowercase the ARG/ConfigurationData software name
2. Extract product name and version
3. Look up the slug map
4. Return `(source, product_slug, version_cycle)` tuple

---

## 4. ARG Queries for OS/Software Inventory

### Azure VMs — OS Version

```kusto
resources
| where type == "microsoft.compute/virtualmachines"
| extend osName = tostring(properties.extended.instanceView.osName)
| extend osVersion = tostring(properties.extended.instanceView.osVersion)
| extend osType = tostring(properties.storageProfile.osDisk.osType)
| extend publisher = tostring(properties.storageProfile.imageReference.publisher)
| extend offer = tostring(properties.storageProfile.imageReference.offer)
| extend sku = tostring(properties.storageProfile.imageReference.sku)
| project id, name, resourceGroup, subscriptionId, osName, osVersion, osType, publisher, offer, sku
```

**Key fields:**
- `properties.extended.instanceView.osName` — "Windows Server 2022 Datacenter" (requires Guest Agent running)
- `properties.extended.instanceView.osVersion` — "10.0.20348" (build number)
- `properties.storageProfile.imageReference.sku` — "2022-datacenter" (from deployment template)
- `properties.storageProfile.imageReference.offer` — "WindowsServer"
- `properties.storageProfile.imageReference.publisher` — "MicrosoftWindowsServer"

**For EOL detection:** Use `osName` first (human-readable). Fall back to `sku` + `offer` + `publisher` for parsing if `osName` is empty (VM deallocated or Guest Agent not reporting).

### Arc-enabled Servers — OS Version

```kusto
resources
| where type == "microsoft.hybridcompute/machines"
| extend osName = tostring(properties.osName)
| extend osVersion = tostring(properties.osVersion)
| extend osType = tostring(properties.osType)
| extend osSku = tostring(properties.osSku)
| extend status = tostring(properties.status)
| project id, name, resourceGroup, subscriptionId, osName, osVersion, osType, osSku, status
```

**Key fields:**
- `properties.osName` — "Windows Server 2025", "ubuntu" (lowercase for Linux)
- `properties.osVersion` — "10.0.26100" for Windows, "22.04" for Ubuntu
- `properties.osSku` — "Windows Server 2025 Standard", "22.04 LTS"
- `properties.osType` — "Windows" or "Linux"
- `properties.status` — "Connected", "Disconnected", "Expired"

**For EOL detection:** `osName` + `osVersion` together provide enough to determine product + cycle. For Ubuntu, `osVersion` directly maps to the cycle (e.g., "22.04"). For Windows Server, `osSku` gives the full name including year.

### Arc-enabled Kubernetes Clusters

```kusto
resources
| where type == "microsoft.kubernetes/connectedclusters"
| extend kubernetesVersion = tostring(properties.kubernetesVersion)
| extend distribution = tostring(properties.distribution)
| extend totalNodeCount = toint(properties.totalNodeCount)
| extend connectivityStatus = tostring(properties.connectivityStatus)
| project id, name, resourceGroup, subscriptionId, kubernetesVersion, distribution, totalNodeCount, connectivityStatus
```

**For EOL detection:** `kubernetesVersion` (e.g., "1.28.5") maps to AKS support lifecycle. Use `azure-kubernetes-service` slug on endoflife.date with the major.minor as the cycle (e.g., "1.28").

### Pagination

All ARG queries use `skip_token` pagination (same pattern as patch agent). The `ResourceGraphClient.resources()` returns a `skip_token` when there are more results; loop until `skip_token` is None.

---

## 5. ConfigurationData Table (Log Analytics)

### Schema (Azure Monitor reference)

| Column | Type | Description |
|--------|------|-------------|
| `Computer` | string | Machine hostname |
| `SoftwareName` | string | Installed software name (e.g., "Python 3.12.1", "Node.js 20.11.0") |
| `CurrentVersion` | string | Installed version string |
| `Publisher` | string | Software publisher |
| `SoftwareType` | string | "Application", "Update", "Package" |
| `ConfigDataType` | string | "Software" for software inventory |
| `TimeGenerated` | datetime | When data was collected |
| `_ResourceId` | string | ARM resource ID of the machine |

### KQL for Installed Runtimes/Databases

```kusto
ConfigurationData
| where ConfigDataType == "Software"
| where SoftwareType in ("Application", "Package")
| where SoftwareName has_any ("python", "nodejs", "node.js", "dotnet", ".net",
                              "postgresql", "mysql", "sql server")
| project Computer, SoftwareName, CurrentVersion, Publisher, TimeGenerated, _ResourceId
| order by TimeGenerated desc
```

### Workspace Discovery

The EOL agent queries across Log Analytics workspaces. The workspace ID must be known. Options:
1. Pass workspace ID as an env var (e.g., `LOG_ANALYTICS_WORKSPACE_ID`)
2. Use ARG to discover workspaces: `resources | where type == "microsoft.operationalinsights/workspaces"`
3. Use the Azure MCP Server's `monitor.query_logs` tool (already in ALLOWED_MCP_TOOLS)

**Recommended:** Use `monitor.query_logs` MCP tool for ConfigurationData queries (same as patch agent). The MCP tool handles workspace resolution internally.

### Merge Strategy with ARG Data

Per D-06 (from Phase 11): Merge by machine. ARG provides the resource ID and OS version. ConfigurationData provides installed software (runtimes, databases). Merge key: `_ResourceId` from ConfigurationData matches ARG `id` for Azure VMs; for Arc machines, match by `Computer` (hostname) as fallback.

---

## 6. PostgreSQL Cache Pattern

### Existing Pattern: `resolve_postgres_dsn()` in `runbook_rag.py`

```python
def resolve_postgres_dsn() -> str:
    """Resolve the runbook PostgreSQL DSN from supported env vars."""
    pgvector_dsn = os.environ.get("PGVECTOR_CONNECTION_STRING", "").strip()
    if pgvector_dsn:
        return pgvector_dsn
    postgres_dsn = os.environ.get("POSTGRES_DSN", "").strip()
    if postgres_dsn:
        return postgres_dsn
    postgres_host = os.environ.get("POSTGRES_HOST", "").strip()
    if postgres_host:
        return _build_dsn()
    raise RunbookSearchUnavailableError(...)
```

The EOL agent should replicate this pattern in `agents/eol/tools.py`:
- Same env var resolution order: `PGVECTOR_CONNECTION_STRING` → `POSTGRES_DSN` → `POSTGRES_*`
- Same asyncpg connection pattern: `conn = await asyncpg.connect(dsn)`
- Same error handling: raise or return gracefully if DB unavailable

### Cache Table: `eol_cache`

Migration `004_create_eol_cache_table.sql` (note: 003 is already taken by gitops_cluster_config):

```sql
CREATE TABLE IF NOT EXISTS eol_cache (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product     TEXT NOT NULL,
    version     TEXT NOT NULL,
    eol_date    DATE,
    is_eol      BOOLEAN NOT NULL,
    lts         BOOLEAN,
    latest_version TEXT,
    support_end DATE,
    source      TEXT NOT NULL,
    raw_response JSONB,
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (product, version, source)
);

CREATE INDEX IF NOT EXISTS idx_eol_cache_lookup
    ON eol_cache (product, version, expires_at);

COMMENT ON TABLE eol_cache IS 'EOL lifecycle cache — Phase 12. 24h TTL, synchronous refresh on miss.';
```

**Key additions vs. D-08 schema:**
- `raw_response JSONB` — store the full upstream JSON for debugging/audit
- `latest_version TEXT` — cached recommended upgrade target
- `lts BOOLEAN` — cached LTS status
- `support_end DATE` — mainstream support end (distinct from EOL)

### Cache Helpers

```python
async def get_cached_eol(product: str, version: str) -> Optional[dict]:
    """Return cached EOL record if not expired, else None."""
    dsn = resolve_postgres_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            """SELECT * FROM eol_cache
               WHERE product = $1 AND version = $2 AND expires_at > now()
               ORDER BY cached_at DESC LIMIT 1""",
            product, version,
        )
        return dict(row) if row else None
    finally:
        await conn.close()

async def set_cached_eol(product: str, version: str, source: str, ...) -> None:
    """Upsert EOL cache record with 24h TTL."""
    dsn = resolve_postgres_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """INSERT INTO eol_cache (product, version, eol_date, is_eol, lts,
                                      latest_version, support_end, source,
                                      raw_response, cached_at, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now(), now() + INTERVAL '24 hours')
               ON CONFLICT (product, version, source)
               DO UPDATE SET eol_date = EXCLUDED.eol_date, is_eol = EXCLUDED.is_eol,
                            lts = EXCLUDED.lts, latest_version = EXCLUDED.latest_version,
                            support_end = EXCLUDED.support_end, raw_response = EXCLUDED.raw_response,
                            cached_at = now(), expires_at = now() + INTERVAL '24 hours'
            """,
            product, version, eol_date, is_eol, lts, latest_version, support_end, source, raw_response,
        )
    finally:
        await conn.close()
```

### Connection Pooling Consideration

The `runbook_rag.py` pattern opens a new connection per request (`asyncpg.connect(dsn)`). This is fine for low-frequency cache lookups (EOL data changes daily at most). For proactive scan (potentially 100s of lookups), consider creating a pool:

```python
pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)
async with pool.acquire() as conn:
    ...
```

However, for consistency with the existing pattern, start with per-connection and optimize only if proactive scan performance requires it.

---

## 7. Microsoft Agent Framework @tool Pattern

### Import and Decorator (rc5 API)

From `agents/patch/tools.py`:

```python
from agent_framework import tool

@tool
def my_function(arg1: str, arg2: int = 5) -> Dict[str, Any]:
    """Docstring becomes the tool description for the LLM."""
    ...
```

**Key observations from the codebase:**
1. **Import:** `from agent_framework import tool` (NOT `@ai_function` — the 12-CONTEXT.md mentions `@ai_function` but the actual codebase uses `@tool` per rc5)
2. **Decorator:** `@tool` (bare, no arguments)
3. **Return type:** `Dict[str, Any]` — all tools return dicts
4. **Type annotations:** Required on all parameters for the framework to generate JSON schema
5. **Sync functions:** Tools are sync (not async) despite using `instrument_tool_call`. The `search_runbooks` wrapper bridges async/sync with `asyncio.run()` in a thread pool.
6. **OTel instrumentation:** Every tool wraps its body in `with instrument_tool_call(...):`

### Agent Factory (from `agents/patch/agent.py`)

```python
from agent_framework import Agent, MCPStreamableHTTPTool

def create_eol_agent() -> Agent:
    client = get_foundry_client()
    tools = [tool_fn_1, tool_fn_2, ...]

    if azure_mcp_url:
        tools.append(MCPStreamableHTTPTool(
            name="azure-mcp",
            url=azure_mcp_url,
            allowed_tools=ALLOWED_MCP_TOOLS,
        ))

    return Agent(
        client,
        SYSTEM_PROMPT,
        name="eol-agent",
        description="...",
        tools=tools,
    )
```

### Entry Point

```python
if __name__ == "__main__":
    from azure.ai.agentserver.agentframework import from_agent_framework
    from_agent_framework(create_eol_agent()).run()
```

### Important: `@tool` NOT `@ai_function`

The 12-CONTEXT.md references `@ai_function` in several places (D-03, D-12, D-13, D-20, D-23). However, the actual codebase uses `@tool` everywhere (patch agent, orchestrator). The conftest.py stub also registers `tool` as the primary decorator and `ai_function` as a legacy alias. **Use `@tool` in implementation.**

---

## 8. Proactive Scan and Incident Creation

### Incident Creation Endpoint

`POST /api/v1/incidents` via the API gateway. Uses `IncidentPayload` model:

```python
class IncidentPayload(BaseModel):
    incident_id: str
    severity: str  # Sev0-Sev3
    domain: str    # compute|network|storage|security|arc|sre  ⚠️
    affected_resources: list[AffectedResource]
    detection_rule: str
    kql_evidence: Optional[str]
    title: Optional[str]
    description: Optional[str]
```

### ⚠️ CRITICAL FINDING: `domain` Regex Constraint

The `IncidentPayload.domain` field has a regex validator: `^(compute|network|storage|security|arc|sre)$`. **Neither `patch` nor `eol` are in this list.** This means:

1. The proactive scan cannot create incidents with `domain: "eol"` using the current model
2. **Action required in Phase 12:** Add `eol` (and `patch`) to the domain regex: `^(compute|network|storage|security|arc|sre|patch|eol)$`
3. This is a shared model change in `services/api-gateway/models.py`

### Dedup Logic for Proactive Scan

Per D-14, the proactive scan creates one incident per threshold per resource per product (idempotent). Dedup strategy:

1. **Generate deterministic `incident_id`:** `eol-{product}-{version}-{resource_id_hash}-{threshold}` (e.g., `eol-ubuntu-18.04-abc123-30d`)
2. **Check existing incidents in Cosmos DB** before creating: The api-gateway already has dedup logic (DETECT-005) that checks for active incidents with the same `resource_id` before creating new ones.
3. **The `incident_id` uniqueness** in Cosmos DB prevents duplicate creation. If a scan runs daily and the same product-version-resource-threshold combo exists, the Cosmos upsert will skip.

### Proactive Scan Trigger

Per D-15, the trigger is either:
- **Fabric Activator timer rule** (daily at 02:00 UTC)
- **Azure Logic App timer trigger**
- **Manual invocation** via chat ("scan my estate for EOL software")

For Phase 12, implement the `scan_estate_eol()` `@tool` function. The timer infrastructure is at implementer's discretion (Terraform Activator rule or Logic App).

---

## 9. Existing Agent Structure (Template: Patch Agent)

### File Layout (to replicate for `agents/eol/`)

```
agents/eol/
├── __init__.py          # """AAP EOL Agent — End-of-Life lifecycle specialist."""
├── agent.py             # Agent factory, system prompt, create_eol_agent()
├── tools.py             # @tool functions, ALLOWED_MCP_TOOLS, cache helpers
├── Dockerfile           # FROM ${BASE_IMAGE}, CMD ["python", "-m", "eol.agent"]
└── requirements.txt     # Agent-specific deps (httpx, asyncpg already in base?)
```

### Dockerfile (from patch agent)

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE:-aap-agents-base:latest}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./eol/

CMD ["python", "-m", "eol.agent"]
```

### Test Layout (to create)

```
agents/tests/eol/
├── __init__.py
├── test_eol_tools.py    # Unit tests for all @tool functions
├── test_eol_agent.py    # System prompt tests, agent factory tests
└── test_routing.py      # Orchestrator routing integration tests for EOL keywords
```

### Files to Modify (orchestrator routing)

1. **`agents/orchestrator/agent.py`:**
   - Add `"eol": "eol-agent"` to `DOMAIN_AGENT_MAP`
   - Add `"microsoft.lifecycle": "eol"` to `RESOURCE_TYPE_TO_DOMAIN`
   - Update system prompt routing rules to include EOL domain
   - Add EOL `AgentTarget` with `EOL_AGENT_ID` env var

2. **`agents/shared/routing.py`:**
   - Add `"eol"` entry to `QUERY_DOMAIN_KEYWORDS` tuple (insert after `"patch"`, before `"compute"` for specificity ordering)
   - Keywords: `"end of life"`, `"eol"`, `"end-of-life"`, `"outdated software"`, `"software lifecycle"`, `"unsupported version"`, `"lifecycle status"`, `"deprecated version"`

3. **`services/api-gateway/models.py`:**
   - Update `IncidentPayload.domain` regex to include `eol` and `patch`

### Spec File

Create `docs/agents/eol-agent.spec.md` following the format of `docs/agents/patch-agent.spec.md`:
- Frontmatter: agent, requirements, phase
- Sections: Persona, Goals, Workflow, Tool Permissions, Safety Constraints, Example Flows

---

## 10. httpx in the Codebase

### Already Used

`httpx` is already used in two places:
1. **`agents/patch/tools.py`:** `import httpx` + `httpx.get()` for MSRC CVRF API calls (sync)
2. **`agents/shared/runbook_tool.py`:** `import httpx` + `httpx.AsyncClient()` for API gateway calls (async)

### NOT in `agents/requirements-base.txt`

`httpx` is **not** listed in `agents/requirements-base.txt`. It must be getting pulled in transitively by another dependency (possibly `mcp[cli]` or `azure-ai-projects`).

**Decision:** Since `httpx` is already imported and used in multiple agent files without being in `requirements-base.txt`, it's a transitive dependency. For safety, add it to `agents/eol/requirements.txt` explicitly (same pattern as patch agent adding `azure-mgmt-resourcegraph`).

### Pattern for EOL Agent

```python
# Sync call (for @tool functions that block)
import httpx

response = httpx.get(
    f"https://endoflife.date/api/{product}/{cycle}.json",
    timeout=10.0,
)
response.raise_for_status()
data = response.json()
```

For MS Lifecycle API (1 req/s limit):
```python
response = httpx.get(
    "https://learn.microsoft.com/api/lifecycle/products",
    params={"$filter": f"contains(productName,'{product_name}')"},
    timeout=15.0,
)
```

### Retry Strategy

Use httpx with manual retry (no external retry library needed):

```python
def _fetch_with_retry(url: str, params: dict = None, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            response = httpx.get(url, params=params, timeout=10.0)
            if response.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            if attempt == max_retries - 1:
                raise
            time.sleep(1)
    return {}
```

---

## 11. Test Patterns and conftest.py

### Root conftest.py

The root `conftest.py` installs an `agent_framework` stub module that provides:
- `tool` decorator (no-op — returns function unchanged)
- `ai_function` alias (same as `tool`)
- `Agent` class stub
- `MCPStreamableHTTPTool` class stub
- `ChatAgent`, `AgentTarget`, `HandoffOrchestrator` stubs

This means agent source modules can be imported in tests without the real `agent-framework` RC package.

### Test Pattern (from `agents/tests/patch/test_patch_tools.py`)

1. **Mock `instrument_tool_call`** as a context manager:
```python
@patch("agents.eol.tools.instrument_tool_call")
@patch("agents.eol.tools.get_agent_identity", return_value="test-entra-id")
def test_my_tool(self, mock_identity, mock_instrument):
    mock_instrument.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock_instrument.return_value.__exit__ = MagicMock(return_value=False)

    from agents.eol.tools import my_tool
    result = my_tool(arg1="test")

    assert result["query_status"] == "success"
```

2. **Mock external HTTP calls** for endoflife.date and MS Lifecycle:
```python
@patch("agents.eol.tools.httpx.get")
def test_query_endoflife_date(self, mock_httpx_get, ...):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "cycle": "22.04",
        "eol": "2027-04-01",
        "lts": True,
        ...
    }
    mock_response.status_code = 200
    mock_httpx_get.return_value = mock_response
```

3. **Mock asyncpg for cache tests**:
```python
@patch("agents.eol.tools.asyncpg.connect")
def test_get_cached_eol(self, mock_connect, ...):
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"product": "ubuntu", ...}
    mock_connect.return_value = mock_conn
```

4. **Test classes by category**: `TestAllowedMcpTools`, `TestQueryEndoflifeDate`, `TestQueryMsLifecycle`, `TestCacheHelpers`, `TestScanEstateEol`

### Test Coverage Targets

Following the patch agent pattern (~49 unit tests):
- ALLOWED_MCP_TOOLS validation (3 tests)
- Each @tool function: expected structure, error handling, edge cases (5-8 tests each)
- Cache helpers: hit, miss, expired, upsert, DB unavailable (5-6 tests)
- Slug normalization: Windows, Ubuntu, RHEL, Python, Node.js, SQL Server edge cases (6-8 tests)
- System prompt content assertions (10-12 tests)
- Agent factory tests (5-6 tests)
- Routing keywords and domain map integration tests (8-10 tests)
- **Target: 50-60 unit tests**

---

## 12. Terraform and CI/CD Changes

### Terraform Module: `agent-apps`

**`terraform/modules/agent-apps/main.tf`:**

Add `eol` to `local.agents`:

```hcl
locals {
  agents = {
    ...
    patch = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
    eol   = { cpu = 0.5, memory = "1Gi", ingress_external = false, min_replicas = 1, max_replicas = 3, target_port = 8000 }
  }
}
```

Add dynamic `EOL_AGENT_ID` env block for orchestrator:

```hcl
dynamic "env" {
  for_each = each.key == "orchestrator" && var.eol_agent_id != "" ? [1] : []
  content {
    name  = "EOL_AGENT_ID"
    value = var.eol_agent_id
  }
}
```

Add PostgreSQL env vars for EOL agent (if connecting directly to PostgreSQL for cache):

```hcl
# EOL agent needs PostgreSQL DSN for eol_cache table
dynamic "env" {
  for_each = each.key == "eol" && var.postgres_dsn != "" ? [1] : []
  content {
    name  = "POSTGRES_DSN"
    value = var.postgres_dsn
  }
}
```

**`terraform/modules/agent-apps/variables.tf`:**

```hcl
variable "eol_agent_id" {
  description = "Foundry Agent ID for the EOL domain agent"
  type        = string
  default     = ""
}
```

### RBAC

EOL agent needs:
- `Reader` on all subscriptions (for ARG queries)
- `Monitoring Reader` on all subscriptions (for Log Analytics ConfigurationData)
- These are the same roles as the patch agent

### CI/CD: `deploy-all-images.yml`

Add `build-eol` job (copy `build-patch` pattern):

```yaml
build-eol:
  name: Build EOL Agent
  needs: build-agent-base
  uses: ./.github/workflows/docker-push.yml
  with:
    image_name: agents/eol
    dockerfile_path: agents/eol/Dockerfile
    build_context: agents/eol/
    image_tag: ${{ needs.build-agent-base.outputs.image_tag }}
    build_args: |
      BASE_IMAGE=${{ vars.ACR_LOGIN_SERVER }}/agents/base:${{ needs.build-agent-base.outputs.image_tag }}
  secrets:
    AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
    AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
    AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
    AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

### Environment Files

Staging and prod tfvars need:
- `eol_agent_id = ""` (populated after Foundry agent creation)
- PostgreSQL DSN or env vars for eol_cache access

---

## 13. Risks and Open Questions

### Confirmed Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **R-01:** `IncidentPayload.domain` regex does not include `eol` or `patch` | HIGH | Must update `models.py` regex before proactive scan can create incidents. Also affects patch agent if it ever creates incidents. |
| **R-02:** endoflife.date `eol` field is polymorphic (string/bool) | MEDIUM | Must handle `True`/`False` in addition to date strings. `True` = already EOL (no fixed date), `False` = no planned EOL. |
| **R-03:** Node.js `lts` field returns date string instead of boolean | LOW | Type-check `lts` field: `isinstance(lts, str)` means LTS with start date; `True`/`False` is boolean LTS flag. |
| **R-04:** MS Lifecycle API rate limit is 1 req/s (documented) | MEDIUM | Cache eliminates most requests. For proactive scan with many MS products, stagger requests with 1.1s delay between calls. |
| **R-05:** `mssqlserver` slug is unintuitive | LOW | Document in slug map; catch 404 from wrong slug and log warning. |
| **R-06:** Migration number collision — 003 already taken | LOW | Use `004_create_eol_cache_table.sql`. |
| **R-07:** `httpx` is not in `requirements-base.txt` | LOW | Add to `agents/eol/requirements.txt` explicitly. May also be worth adding to base for all agents to share. |
| **R-08:** ARG `osName` may be empty for deallocated VMs | MEDIUM | Fall back to `storageProfile.imageReference.sku` + `offer` + `publisher`. Proactive scan should flag VMs with no discoverable OS as "unresolvable". |
| **R-09:** ConfigurationData requires AMA agent | MEDIUM | Machines without AMA won't have software inventory. The scan report should note "AMA not reporting" for such machines. |

### Open Questions (Resolved by Research)

| Question | Answer |
|----------|--------|
| Does Microsoft Product Lifecycle REST API exist? | **Yes** — fully documented at `learn.microsoft.com/en-us/lifecycle/reference`. No auth required, 1 req/s rate limit. |
| What is the SQL Server slug on endoflife.date? | **`mssqlserver`** (not `sql-server` or `sqlserver`) |
| What ARG table gives OS version? | **`resources`** table with `type == "microsoft.compute/virtualmachines"` and `properties.extended.instanceView.osName` |
| What ARG table gives Arc server OS? | **`resources`** table with `type == "microsoft.hybridcompute/machines"` and `properties.osName` + `properties.osVersion` |
| Is `@ai_function` or `@tool` the current decorator? | **`@tool`** — the codebase uses `from agent_framework import tool`. `@ai_function` is a legacy alias in the conftest stub. |
| What migration number is next? | **004** — 001 (runbooks), 003 (gitops_cluster_config) exist. 002 appears to be skipped/missing. Use 004. |
| Is httpx in requirements-base? | **No** — it's a transitive dependency. Add to `agents/eol/requirements.txt`. |

---

## Summary: What You Need to Plan This Phase Well

### Phase 12 is structurally identical to Phase 11 (Patch Agent) with three key additions:

1. **External HTTP API integration** (two sources: endoflife.date + MS Lifecycle API) — requires slug normalization, polymorphic response handling, and retry logic
2. **PostgreSQL cache layer** (new table + asyncpg helpers) — extends the existing `resolve_postgres_dsn()` pattern
3. **Proactive scan mode** with incident creation — requires `IncidentPayload.domain` regex update and deterministic dedup IDs

### Implementation can follow the same 3-plan structure as Phase 11:
- **Plan 12-01:** Agent spec + core implementation (agent.py, tools.py, Dockerfile, requirements.txt, migration)
- **Plan 12-02:** Orchestrator routing (routing.py, agent.py, system prompt, models.py domain regex fix)
- **Plan 12-03:** Terraform + CI/CD (agent-apps module, variables, RBAC, build job, environment wiring)

### Files to Create (8)
- `agents/eol/__init__.py`
- `agents/eol/agent.py`
- `agents/eol/tools.py`
- `agents/eol/Dockerfile`
- `agents/eol/requirements.txt`
- `docs/agents/eol-agent.spec.md`
- `services/api-gateway/migrations/004_create_eol_cache_table.sql`
- `agents/tests/eol/` (3 test files)

### Files to Modify (6)
- `agents/orchestrator/agent.py` — DOMAIN_AGENT_MAP, RESOURCE_TYPE_TO_DOMAIN, system prompt
- `agents/shared/routing.py` — QUERY_DOMAIN_KEYWORDS
- `services/api-gateway/models.py` — IncidentPayload.domain regex
- `terraform/modules/agent-apps/main.tf` — local.agents, env blocks
- `terraform/modules/agent-apps/variables.tf` — eol_agent_id variable
- `.github/workflows/deploy-all-images.yml` — build-eol job

---

*Research complete — 2026-03-31*
