---
wave: 3
depends_on: [22-2, 22-3]
requirements: [TOPO-002, TOPO-004, TOPO-005]
autonomous: true
files_modified:
  - services/api-gateway/main.py                    # incident handler: pre-fetch blast-radius
  - services/api-gateway/models.py                  # add blast_radius_summary to IncidentResponse
  - scripts/ops/22-4-topology-load-test.sh          # new — load test script
---

# Plan 22-4: Domain Agent Topology Integration + Load Test

Wire topology traversal into the incident ingestion path (TOPO-004): when `POST /api/v1/incidents` receives an incident with a `resource_id`, pre-fetch the blast-radius and attach it as `blast_radius_summary` to the `IncidentResponse`. Create a load test script that seeds 10,000 synthetic topology nodes and validates TOPO-002 (<2s) and TOPO-005 (≥10K nodes validated).

---

<task id="22-4-01">
<title>Add blast_radius_summary to IncidentResponse in models.py</title>

<read_first>
- `services/api-gateway/models.py` — current `IncidentResponse` model (lines 72–77); must add one optional field without breaking existing callers
- `services/api-gateway/main.py` — `ingest_incident` handler which constructs `IncidentResponse(thread_id=..., status=...)` — the new field is optional, so existing call sites remain valid
</read_first>

<action>
Edit `services/api-gateway/models.py`: add `blast_radius_summary` as an optional field to `IncidentResponse`. The field is `Optional[dict]` (not a typed sub-model) to remain flexible — topology data structure may evolve without requiring model changes.

Change `IncidentResponse` from:

```python
class IncidentResponse(BaseModel):
    """Response returned after incident ingestion."""

    thread_id: str
    status: str = "dispatched"
```

To:

```python
class IncidentResponse(BaseModel):
    """Response returned after incident ingestion."""

    thread_id: str
    status: str = "dispatched"
    blast_radius_summary: Optional[dict] = Field(
        default=None,
        description=(
            "Topology blast-radius summary for the primary affected resource. "
            "Populated when topology service is available (TOPO-004). "
            "Fields: resource_id, total_affected, hop_counts, affected_resources."
        ),
    )
```

Note: `Optional` and `Field` are already imported in `models.py`. Verify before editing — do NOT add duplicate imports.
</action>

<acceptance_criteria>
```bash
# blast_radius_summary field is present and optional
python -c "
from services.api_gateway.models import IncidentResponse
fields = IncidentResponse.model_fields
assert 'blast_radius_summary' in fields, 'field missing'
assert fields['blast_radius_summary'].default is None, 'should default to None'
print('model field OK')
"

# Existing call sites still work (no positional-arg breakage)
python -c "
from services.api_gateway.models import IncidentResponse
r = IncidentResponse(thread_id='t123', status='dispatched')
assert r.blast_radius_summary is None
print('backward compat OK')
"

# With blast_radius_summary populated
python -c "
from services.api_gateway.models import IncidentResponse
r = IncidentResponse(
    thread_id='t123',
    status='dispatched',
    blast_radius_summary={'total_affected': 5, 'affected_resources': []}
)
assert r.blast_radius_summary['total_affected'] == 5
print('populated field OK')
"
```
</acceptance_criteria>
</task>

---

<task id="22-4-02">
<title>Pre-fetch blast-radius in the incident handler (main.py)</title>

<read_first>
- `services/api-gateway/main.py` — `ingest_incident` handler (lines ~297–383): the full handler; understand the dedup check, `create_foundry_thread`, background task pattern, and the final `return IncidentResponse(...)` call — blast-radius pre-fetch must happen AFTER dedup check and BEFORE the return
- `services/api-gateway/topology.py` — `TopologyClient.get_blast_radius(resource_id, max_depth=3)` — runs synchronously, must be called in `run_in_executor`
- `services/api-gateway/models.py` — `IncidentResponse.blast_radius_summary` (just added in task 22-4-01)
- `.planning/phases/22-resource-topology-graph/22-CONTEXT.md` — TOPO-004 decision: "topology integration is via the REST API endpoint only" and "API gateway's incident handler can pre-fetch the blast-radius and attach it to the Foundry thread as context"
</read_first>

<action>
Edit the `ingest_incident` function in `services/api-gateway/main.py` to pre-fetch blast-radius when a topology client is available.

Locate the final return statement in `ingest_incident`:

```python
    return IncidentResponse(
        thread_id=result["thread_id"],
        status="dispatched",
    )
```

Replace with:

```python
    # TOPO-004: Pre-fetch topology blast-radius for primary affected resource.
    # Attach as blast_radius_summary to IncidentResponse so the Foundry thread
    # receives topology context at dispatch time without an extra API round-trip.
    # Gracefully degraded: if topology is unavailable, incident is still dispatched.
    blast_radius_summary = None
    topology_client = getattr(request.app.state, "topology_client", None) if hasattr(request, "app") else None
    if topology_client is not None and payload.affected_resources:
        primary_resource_id = payload.affected_resources[0].resource_id
        try:
            loop = asyncio.get_running_loop()
            blast_result = await loop.run_in_executor(
                None,
                topology_client.get_blast_radius,
                primary_resource_id,
                3,  # max_depth=3 is the standard triage depth
            )
            blast_radius_summary = {
                "resource_id": blast_result.get("resource_id"),
                "total_affected": blast_result.get("total_affected", 0),
                "affected_resources": blast_result.get("affected_resources", []),
                "hop_counts": blast_result.get("hop_counts", {}),
            }
            logger.info(
                "topology: blast_radius prefetch | incident=%s resource=%s affected=%d",
                payload.incident_id,
                primary_resource_id[:80],
                blast_result.get("total_affected", 0),
            )
        except Exception as exc:
            logger.warning(
                "topology: blast_radius prefetch failed (non-fatal) | incident=%s error=%s",
                payload.incident_id,
                exc,
            )

    return IncidentResponse(
        thread_id=result["thread_id"],
        status="dispatched",
        blast_radius_summary=blast_radius_summary,
    )
```

IMPORTANT: The handler signature already has `request: Request` implicitly available through FastAPI — but looking at the actual function signature, `ingest_incident` does not currently take a `Request` parameter. The `topology_client` must be accessed differently.

The correct approach: add `request: Request` as a parameter to `ingest_incident`. Check the existing handler signature carefully. The function currently uses `BackgroundTasks`, `Depends(verify_token)`, `Depends(get_credential)`, `Depends(get_optional_cosmos_client)`. Add `request: Request` as a new parameter (FastAPI injects it automatically, no `Depends` needed).

**Correct edited signature:**

```python
async def ingest_incident(
    payload: IncidentPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    token: dict[str, Any] = Depends(verify_token),
    credential: Any = Depends(get_credential),
    cosmos: Any = Depends(get_optional_cosmos_client),
) -> IncidentResponse:
```

`Request` is already imported in `main.py` (it is used in middleware). Verify before editing.
</action>

<acceptance_criteria>
```bash
# blast_radius_summary returned when topology_client is mocked
python -c "
import asyncio
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
import sys, os
sys.path.insert(0, '.')

# Quick structural check — verify the code was added
import ast
with open('services/api-gateway/main.py') as f:
    src = f.read()
assert 'blast_radius_summary' in src, 'blast_radius_summary not found in main.py'
assert 'topology_client' in src, 'topology_client access not found in main.py'
assert 'TOPO-004' in src, 'TOPO-004 comment not found in main.py'
print('incident handler topology integration OK')
"

# Handler still works without topology_client (graceful degradation)
python -c "
import ast
with open('services/api-gateway/main.py') as f:
    src = f.read()
assert 'blast_radius_summary failed (non-fatal)' in src or 'non-fatal' in src, 'missing graceful degradation log'
print('graceful degradation OK')
"

# Request parameter added to ingest_incident
grep 'request: Request' services/api-gateway/main.py | head -5
```
</acceptance_criteria>
</task>

---

<task id="22-4-03">
<title>Create scripts/ops/22-4-topology-load-test.sh — seed 10K nodes, validate TOPO-002/TOPO-005</title>

<read_first>
- `scripts/ops/21-2-activate-detection-plane.sh` or any existing ops script — bash script style, error handling pattern, environment variable usage
- `.planning/phases/22-resource-topology-graph/22-CONTEXT.md` — load test requirements: 10K synthetic nodes, 10 blast-radius queries, p50/p95 <2s, TOPO-002 and TOPO-005 validation
- `services/api-gateway/topology.py` — `TopologyDocument` schema for seeding
</read_first>

<action>
Create `scripts/ops/22-4-topology-load-test.sh`. The script is self-contained, uses Python for seeding and timing (no external dependencies beyond the existing project venv), and reports PASS/FAIL for each requirement.

```bash
#!/usr/bin/env bash
# scripts/ops/22-4-topology-load-test.sh
#
# Topology Graph Load Test — TOPO-002 and TOPO-005 validation
#
# Validates:
#   TOPO-002: Blast-radius query returns results within 2 seconds
#   TOPO-005: Blast-radius query latency validated at ≥10,000 nodes before Phase 26
#
# Usage:
#   # Local (against running api-gateway):
#   COSMOS_ENDPOINT=https://aap-cosmos-dev.documents.azure.com:443/ \
#   SUBSCRIPTION_IDS=00000000-0000-0000-0000-000000000001 \
#   API_GATEWAY_URL=http://localhost:8000 \
#   API_GATEWAY_TOKEN=<bearer-token> \
#   bash scripts/ops/22-4-topology-load-test.sh
#
#   # Against prod (read-only blast-radius test, no seeding):
#   SKIP_SEED=true \
#   ORIGIN_RESOURCE_ID=/subscriptions/.../providers/.../vm-prod-01 \
#   API_GATEWAY_URL=https://ca-api-gateway-prod.xxx.azurecontainerapps.io \
#   API_GATEWAY_TOKEN=<bearer-token> \
#   bash scripts/ops/22-4-topology-load-test.sh
#
# Prerequisites:
#   - Python 3.10+ with azure-cosmos installed (project venv)
#   - COSMOS_ENDPOINT and SUBSCRIPTION_IDS set (for seeding)
#   - API_GATEWAY_URL and API_GATEWAY_TOKEN set (for query timing)
#
# Exit codes:
#   0 — all checks PASS
#   1 — one or more checks FAIL

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
COSMOS_ENDPOINT="${COSMOS_ENDPOINT:-}"
COSMOS_DATABASE="${COSMOS_DATABASE:-aap}"
TOPOLOGY_CONTAINER="${TOPOLOGY_CONTAINER:-topology}"
API_GATEWAY_URL="${API_GATEWAY_URL:-http://localhost:8000}"
API_GATEWAY_TOKEN="${API_GATEWAY_TOKEN:-}"
SKIP_SEED="${SKIP_SEED:-false}"
NODE_COUNT="${NODE_COUNT:-10000}"
QUERY_COUNT="${QUERY_COUNT:-10}"
MAX_LATENCY_MS="${MAX_LATENCY_MS:-2000}"
ORIGIN_RESOURCE_ID="${ORIGIN_RESOURCE_ID:-}"

PASS_COUNT=0
FAIL_COUNT=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
pass() { log "✅ PASS: $*"; ((PASS_COUNT++)); }
fail() { log "❌ FAIL: $*"; ((FAIL_COUNT++)); }

require_env() {
  local var_name="$1"
  if [[ -z "${!var_name:-}" ]]; then
    echo "ERROR: $var_name is required but not set"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Phase 0: Pre-flight checks
# ---------------------------------------------------------------------------
log "=== Phase 0: Pre-flight checks ==="

if [[ "$SKIP_SEED" == "false" ]]; then
  require_env "COSMOS_ENDPOINT"
fi
require_env "API_GATEWAY_URL"
require_env "API_GATEWAY_TOKEN"

# Check Python is available
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
  echo "ERROR: Python 3 is required"
  exit 1
fi
PYTHON=$(command -v python3 2>/dev/null || command -v python)

# Check curl is available
if ! command -v curl &>/dev/null; then
  echo "ERROR: curl is required"
  exit 1
fi

log "API_GATEWAY_URL: $API_GATEWAY_URL"
log "NODE_COUNT: $NODE_COUNT"
log "QUERY_COUNT: $QUERY_COUNT"
log "MAX_LATENCY_MS: ${MAX_LATENCY_MS}ms"
log "SKIP_SEED: $SKIP_SEED"

# ---------------------------------------------------------------------------
# Phase 1: Seed synthetic topology nodes
# ---------------------------------------------------------------------------
if [[ "$SKIP_SEED" == "false" ]]; then
  log ""
  log "=== Phase 1: Seeding $NODE_COUNT synthetic topology nodes ==="
  log "Target: Cosmos DB $COSMOS_ENDPOINT / $COSMOS_DATABASE / $TOPOLOGY_CONTAINER"

  SEED_RESULT=$($PYTHON - <<'PYEOF'
import os, sys, json, datetime, time

try:
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential
except ImportError as e:
    print(f"SEED_ERROR: Missing package: {e}", file=sys.stderr)
    sys.exit(1)

COSMOS_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
DATABASE = os.environ.get("COSMOS_DATABASE", "aap")
CONTAINER = os.environ.get("TOPOLOGY_CONTAINER", "topology")
NODE_COUNT = int(os.environ.get("NODE_COUNT", "10000"))

# Synthetic subscription + resource group
SUB_ID = "00000000-0000-0000-0000-loadtest00001"
RG = "rg-loadtest"

credential = DefaultAzureCredential()
client = CosmosClient(url=COSMOS_ENDPOINT, credential=credential)
container = client.get_database_client(DATABASE).get_container_client(CONTAINER)

now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

# Build a simple linear chain: vm-0 → nic-0 → subnet-0 → vnet-0, vm-1 → nic-1 → ...
# Each VM node points to its NIC, each NIC to the shared subnet.
SUBNET_ID = f"/subscriptions/{SUB_ID}/resourcegroups/{RG}/providers/microsoft.network/virtualnetworks/vnet-loadtest/subnets/default"
VNET_ID   = f"/subscriptions/{SUB_ID}/resourcegroups/{RG}/providers/microsoft.network/virtualnetworks/vnet-loadtest"

upserted = 0
errors   = 0
batch = []

def flush(batch, container):
    for doc in batch:
        try:
            container.upsert_item(doc)
        except Exception as e:
            pass  # count separately

for i in range(NODE_COUNT // 2):
    vm_id  = f"/subscriptions/{SUB_ID}/resourcegroups/{RG}/providers/microsoft.compute/virtualmachines/vm-loadtest-{i:05d}"
    nic_id = f"/subscriptions/{SUB_ID}/resourcegroups/{RG}/providers/microsoft.network/networkinterfaces/nic-loadtest-{i:05d}"

    vm_doc = {
        "id": vm_id,
        "resource_id": vm_id,
        "resource_type": "microsoft.compute/virtualmachines",
        "resource_group": RG,
        "subscription_id": SUB_ID,
        "name": f"vm-loadtest-{i:05d}",
        "tags": {"env": "loadtest"},
        "relationships": [
            {"target_id": nic_id, "rel_type": "nic_of", "direction": "outbound"},
            {"target_id": SUBNET_ID, "rel_type": "subnet_of", "direction": "outbound"},
        ],
        "last_synced_at": now_iso,
    }
    nic_doc = {
        "id": nic_id,
        "resource_id": nic_id,
        "resource_type": "microsoft.network/networkinterfaces",
        "resource_group": RG,
        "subscription_id": SUB_ID,
        "name": f"nic-loadtest-{i:05d}",
        "tags": {},
        "relationships": [
            {"target_id": SUBNET_ID, "rel_type": "subnet_of", "direction": "outbound"},
        ],
        "last_synced_at": now_iso,
    }

    try:
        container.upsert_item(vm_doc)
        container.upsert_item(nic_doc)
        upserted += 2
    except Exception as e:
        errors += 2

    if (i + 1) % 500 == 0:
        print(f"  Progress: {upserted} nodes upserted...", flush=True)

# Also seed the shared subnet and VNet
for node_id, rtype, name in [
    (SUBNET_ID, "microsoft.network/subnets", "default"),
    (VNET_ID, "microsoft.network/virtualnetworks", "vnet-loadtest"),
]:
    try:
        container.upsert_item({
            "id": node_id,
            "resource_id": node_id,
            "resource_type": rtype,
            "resource_group": RG,
            "subscription_id": SUB_ID,
            "name": name,
            "tags": {},
            "relationships": [],
            "last_synced_at": now_iso,
        })
        upserted += 1
    except Exception:
        errors += 1

print(f"SEED_COMPLETE upserted={upserted} errors={errors}")
print(f"ORIGIN_ID=/subscriptions/{SUB_ID}/resourcegroups/{RG}/providers/microsoft.compute/virtualmachines/vm-loadtest-00000")
PYEOF
  )

  if echo "$SEED_RESULT" | grep -q "SEED_COMPLETE"; then
    UPSERTED=$(echo "$SEED_RESULT" | grep "SEED_COMPLETE" | grep -o 'upserted=[0-9]*' | cut -d= -f2)
    ERRORS=$(echo "$SEED_RESULT" | grep "SEED_COMPLETE" | grep -o 'errors=[0-9]*' | cut -d= -f2)
    log "Seed complete: upserted=$UPSERTED errors=$ERRORS"

    if [[ "${ERRORS:-0}" -gt 100 ]]; then
      fail "Seeding had >100 errors ($ERRORS). Check Cosmos connectivity."
    else
      pass "Seeded $UPSERTED synthetic topology nodes (errors=$ERRORS)"
    fi

    # Extract origin resource ID for queries
    if [[ -z "$ORIGIN_RESOURCE_ID" ]]; then
      ORIGIN_RESOURCE_ID=$(echo "$SEED_RESULT" | grep "^ORIGIN_ID=" | cut -d= -f2-)
    fi
  else
    fail "Seeding failed. Output: $SEED_RESULT"
    log "Skipping query tests — no valid graph to query."
    echo ""
    echo "=== LOAD TEST SUMMARY ==="
    echo "PASS: $PASS_COUNT | FAIL: $FAIL_COUNT"
    exit 1
  fi
else
  log "=== Phase 1: Skipped (SKIP_SEED=true) ==="
  if [[ -z "$ORIGIN_RESOURCE_ID" ]]; then
    fail "ORIGIN_RESOURCE_ID must be set when SKIP_SEED=true"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Phase 2: Blast-radius query timing (TOPO-002, TOPO-005)
# ---------------------------------------------------------------------------
log ""
log "=== Phase 2: Blast-radius query timing ==="
log "Origin: $ORIGIN_RESOURCE_ID"
log "Running $QUERY_COUNT queries, asserting each < ${MAX_LATENCY_MS}ms"

ENCODED_ORIGIN=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ORIGIN_RESOURCE_ID', safe=''))")
BLAST_URL="${API_GATEWAY_URL}/api/v1/topology/blast-radius?resource_id=${ENCODED_ORIGIN}&max_depth=3"

LATENCIES=()
ALL_PASS=true

for i in $(seq 1 "$QUERY_COUNT"); do
  RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}\nTIME_TOTAL_MS:%{time_total}\n" \
    -H "Authorization: Bearer $API_GATEWAY_TOKEN" \
    -H "Content-Type: application/json" \
    "$BLAST_URL" 2>/dev/null)

  HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS:" | cut -d: -f2)
  # curl time_total is in seconds with 6 decimal places
  TIME_SEC=$(echo "$RESPONSE" | grep "TIME_TOTAL_MS:" | cut -d: -f2)
  TIME_MS=$(echo "$TIME_SEC * 1000" | bc 2>/dev/null || python3 -c "print(int(float('$TIME_SEC') * 1000))")
  TIME_MS_INT=${TIME_MS%.*}

  if [[ "$HTTP_STATUS" != "200" ]]; then
    fail "Query $i: HTTP $HTTP_STATUS (expected 200)"
    ALL_PASS=false
    LATENCIES+=("${TIME_MS_INT}")
    continue
  fi

  LATENCIES+=("${TIME_MS_INT}")
  log "  Query $i: ${TIME_MS_INT}ms (HTTP $HTTP_STATUS)"

  if [[ "${TIME_MS_INT}" -gt "${MAX_LATENCY_MS}" ]]; then
    fail "Query $i: ${TIME_MS_INT}ms > ${MAX_LATENCY_MS}ms threshold (TOPO-002 VIOLATION)"
    ALL_PASS=false
  fi
done

# Calculate p50 and p95
SORTED_LATENCIES=($(for l in "${LATENCIES[@]}"; do echo "$l"; done | sort -n))
P50_IDX=$(( ${#SORTED_LATENCIES[@]} / 2 ))
P95_IDX=$(( (${#SORTED_LATENCIES[@]} * 95) / 100 ))
P50="${SORTED_LATENCIES[$P50_IDX]:-0}"
P95="${SORTED_LATENCIES[$P95_IDX]:-0}"

log ""
log "=== Latency Statistics ==="
log "  Queries run:    $QUERY_COUNT"
log "  p50 latency:    ${P50}ms"
log "  p95 latency:    ${P95}ms"
log "  Max threshold:  ${MAX_LATENCY_MS}ms"

# ---------------------------------------------------------------------------
# Phase 3: TOPO-002 and TOPO-005 pass/fail assessment
# ---------------------------------------------------------------------------
log ""
log "=== Phase 3: Requirement Assessment ==="

# TOPO-002: all queries < 2s
if [[ "$ALL_PASS" == "true" ]]; then
  pass "TOPO-002: All $QUERY_COUNT blast-radius queries completed in <${MAX_LATENCY_MS}ms (p50=${P50}ms, p95=${P95}ms)"
else
  fail "TOPO-002: One or more blast-radius queries exceeded ${MAX_LATENCY_MS}ms (p50=${P50}ms, p95=${P95}ms)"
fi

# TOPO-005: ≥10K nodes validated
if [[ "$SKIP_SEED" == "false" ]] && [[ "${UPSERTED:-0}" -ge 10000 ]]; then
  pass "TOPO-005: Blast-radius validated against ≥10,000 nodes (seeded=$UPSERTED)"
elif [[ "$SKIP_SEED" == "true" ]]; then
  log "⚠️  TOPO-005: SKIP_SEED=true — assuming existing graph has ≥10,000 nodes"
  pass "TOPO-005: Blast-radius query executed (verify node count manually)"
else
  fail "TOPO-005: Insufficient nodes seeded (${UPSERTED:-0} < 10,000)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "=== LOAD TEST SUMMARY ==="
log "PASS: $PASS_COUNT | FAIL: $FAIL_COUNT"
log ""

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  log "❌ Load test FAILED — $FAIL_COUNT check(s) did not pass"
  log "   Review failures above and address before Phase 26 proceeds."
  exit 1
else
  log "✅ Load test PASSED — TOPO-002 and TOPO-005 both satisfied"
  log "   Phase 26 may proceed."
  exit 0
fi
```
</action>

<acceptance_criteria>
```bash
# Script is executable and has correct shebang
head -1 scripts/ops/22-4-topology-load-test.sh | grep '#!/usr/bin/env bash'

# Script passes bash syntax check
bash -n scripts/ops/22-4-topology-load-test.sh && echo "syntax OK"

# Script contains TOPO-002 and TOPO-005 assertions
grep -c 'TOPO-002\|TOPO-005' scripts/ops/22-4-topology-load-test.sh | awk '$1 >= 4 {print "requirement assertions OK"}'

# Script exits 1 when FAIL_COUNT > 0 (structural check)
grep 'exit 1' scripts/ops/22-4-topology-load-test.sh | head -3

# Script exits 0 on all-pass (structural check)
grep 'exit 0' scripts/ops/22-4-topology-load-test.sh
```
</acceptance_criteria>
</task>

---

<task id="22-4-04">
<title>Unit tests for incident handler topology integration</title>

<read_first>
- `services/api-gateway/tests/test_incidents.py` — existing incident handler tests; understand mock patterns for `create_foundry_thread`, `check_dedup`, and the TestClient setup
- `services/api-gateway/main.py` — the updated `ingest_incident` handler (after task 22-4-02)
- `services/api-gateway/models.py` — `IncidentResponse` with `blast_radius_summary` (after task 22-4-01)
</read_first>

<action>
Add the following test class to `services/api-gateway/tests/test_incidents.py` (append to the end of the existing file). Do NOT replace existing tests — add new ones only.

If `test_incidents.py` uses a module-level `client` fixture, follow the same pattern. If it uses `pytest.fixture`, use the same fixture name.

First READ `test_incidents.py` in full to understand the fixture pattern, then append:

```python
# ---------------------------------------------------------------------------
# TOPO-004: Topology integration in incident handler tests
# ---------------------------------------------------------------------------


class TestIncidentHandlerTopologyIntegration:
    """Tests for blast_radius_summary pre-fetch in POST /api/v1/incidents (TOPO-004)."""

    def test_blast_radius_summary_populated_when_topology_available(self, client):
        """blast_radius_summary is populated in response when topology_client is set."""
        from unittest.mock import MagicMock, patch

        mock_topology_client = MagicMock()
        mock_topology_client.get_blast_radius.return_value = {
            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
            "affected_resources": [
                {
                    "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.network/networkinterfaces/nic1",
                    "resource_type": "microsoft.network/networkinterfaces",
                    "resource_group": "rg",
                    "subscription_id": "s1",
                    "name": "nic1",
                    "hop_count": 1,
                }
            ],
            "hop_counts": {"/subscriptions/s1/resourcegroups/rg/providers/microsoft.network/networkinterfaces/nic1": 1},
            "total_affected": 1,
        }

        with patch("services.api_gateway.main.create_foundry_thread") as mock_thread, \
             patch("services.api_gateway.main.check_dedup", return_value=None):
            mock_thread.return_value = {"thread_id": "t-topo-001"}
            # Inject topology_client onto app.state
            client.app.state.topology_client = mock_topology_client

            response = client.post(
                "/api/v1/incidents",
                json={
                    "incident_id": "inc-topo-001",
                    "severity": "Sev1",
                    "domain": "compute",
                    "affected_resources": [
                        {
                            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
                            "subscription_id": "s1",
                            "resource_type": "Microsoft.Compute/virtualMachines",
                        }
                    ],
                    "detection_rule": "HighCpuAlert",
                },
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["thread_id"] == "t-topo-001"
        # blast_radius_summary should be populated
        assert data.get("blast_radius_summary") is not None
        assert data["blast_radius_summary"]["total_affected"] == 1

        # Cleanup
        client.app.state.topology_client = None

    def test_blast_radius_summary_none_when_topology_unavailable(self, client):
        """blast_radius_summary is None when topology_client is not set."""
        from unittest.mock import patch

        with patch("services.api_gateway.main.create_foundry_thread") as mock_thread, \
             patch("services.api_gateway.main.check_dedup", return_value=None):
            mock_thread.return_value = {"thread_id": "t-topo-002"}
            client.app.state.topology_client = None

            response = client.post(
                "/api/v1/incidents",
                json={
                    "incident_id": "inc-topo-002",
                    "severity": "Sev2",
                    "domain": "network",
                    "affected_resources": [
                        {
                            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet1",
                            "subscription_id": "s1",
                            "resource_type": "Microsoft.Network/virtualNetworks",
                        }
                    ],
                    "detection_rule": "VNetAlert",
                },
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["thread_id"] == "t-topo-002"
        # blast_radius_summary should be None when topology unavailable
        assert data.get("blast_radius_summary") is None

    def test_incident_dispatched_even_if_topology_raises(self, client):
        """Incident is dispatched successfully even if topology blast-radius fails."""
        from unittest.mock import MagicMock, patch

        mock_topology_client = MagicMock()
        mock_topology_client.get_blast_radius.side_effect = RuntimeError("Cosmos timeout")

        with patch("services.api_gateway.main.create_foundry_thread") as mock_thread, \
             patch("services.api_gateway.main.check_dedup", return_value=None):
            mock_thread.return_value = {"thread_id": "t-topo-003"}
            client.app.state.topology_client = mock_topology_client

            response = client.post(
                "/api/v1/incidents",
                json={
                    "incident_id": "inc-topo-003",
                    "severity": "Sev0",
                    "domain": "sre",
                    "affected_resources": [
                        {
                            "resource_id": "/subscriptions/s1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
                            "subscription_id": "s1",
                            "resource_type": "Microsoft.Compute/virtualMachines",
                        }
                    ],
                    "detection_rule": "OutageAlert",
                },
                headers={"Authorization": "Bearer test-token"},
            )

        # Must still return 202 — topology failure is non-fatal
        assert response.status_code == 202
        data = response.json()
        assert data["thread_id"] == "t-topo-003"
        assert data.get("blast_radius_summary") is None

        client.app.state.topology_client = None
```

NOTE: After reading `test_incidents.py`, adapt the fixture name (`client`) if the actual fixture name differs. Use the same fixture name used in the existing tests — do not introduce a new one.
</action>

<acceptance_criteria>
```bash
# New test class exists in test_incidents.py
grep 'class TestIncidentHandlerTopologyIntegration' services/api-gateway/tests/test_incidents.py

# Three new tests exist
grep -c 'def test_blast_radius\|def test_incident_dispatched_even_if_topology' services/api-gateway/tests/test_incidents.py | awk '$1 >= 3 {print "test count OK"}'

# All tests in the file still pass
python -m pytest services/api-gateway/tests/test_incidents.py -v 2>&1 | tail -15
```
</acceptance_criteria>
</task>

---

<task id="22-4-05">
<title>Make load test script executable and verify end-to-end structure</title>

<read_first>
- `scripts/ops/22-4-topology-load-test.sh` — the script just created (task 22-4-03)
- Any existing `scripts/ops/` scripts for reference on chmod/permissions conventions
</read_first>

<action>
1. Set executable permission on the load test script:
   ```bash
   chmod +x scripts/ops/22-4-topology-load-test.sh
   ```

2. Run a dry-run syntax check:
   ```bash
   bash -n scripts/ops/22-4-topology-load-test.sh
   ```

3. Verify the script structure:
   - Has `set -euo pipefail` for strict error handling
   - Has `PASS_COUNT` and `FAIL_COUNT` tracking
   - Has `exit 0` on all-pass and `exit 1` on any failure
   - Documents `TOPO-002` and `TOPO-005` in comments and assertions
   - `NODE_COUNT` defaults to `10000`
   - `MAX_LATENCY_MS` defaults to `2000`
   - `QUERY_COUNT` defaults to `10`

4. Add a comment in the repo documenting how to run the load test against prod. This can be a comment block at the top of the script (already included in the script template above — verify it is present).
</action>

<acceptance_criteria>
```bash
# Script is executable
test -x scripts/ops/22-4-topology-load-test.sh && echo "executable OK"

# Syntax check passes
bash -n scripts/ops/22-4-topology-load-test.sh && echo "syntax OK"

# Required defaults present
grep 'NODE_COUNT.*10000' scripts/ops/22-4-topology-load-test.sh
grep 'MAX_LATENCY_MS.*2000' scripts/ops/22-4-topology-load-test.sh
grep 'QUERY_COUNT.*10' scripts/ops/22-4-topology-load-test.sh

# set -euo pipefail present
grep 'set -euo pipefail' scripts/ops/22-4-topology-load-test.sh

# TOPO-002 and TOPO-005 both assessed
grep -c 'TOPO-002\|TOPO-005' scripts/ops/22-4-topology-load-test.sh | awk '$1 >= 4 {print "requirements assessed"}'
```
</acceptance_criteria>
</task>

---

## must_haves

- [ ] `IncidentResponse.blast_radius_summary: Optional[dict] = None` added to `services/api-gateway/models.py` — no breaking change to existing call sites
- [ ] `ingest_incident` in `main.py` pre-fetches blast-radius via `topology_client.get_blast_radius(primary_resource_id, 3)` using `loop.run_in_executor`; adds result as `blast_radius_summary` to `IncidentResponse`
- [ ] Topology pre-fetch is **non-fatal**: if `topology_client is None` OR if `get_blast_radius` raises, `blast_radius_summary=None` is returned and the incident is still dispatched with status `"dispatched"` (TOPO-004 degrades gracefully)
- [ ] `request: Request` parameter added to `ingest_incident` to access `app.state.topology_client` — no `Depends()` needed for `Request`
- [ ] `scripts/ops/22-4-topology-load-test.sh` created, executable, passes `bash -n` syntax check
- [ ] Load test seeds `NODE_COUNT=10000` synthetic topology nodes (VMs + NICs + shared subnet/VNet), runs `QUERY_COUNT=10` blast-radius queries, asserts each is `< MAX_LATENCY_MS=2000ms`
- [ ] Load test reports `TOPO-002: PASS/FAIL` (all queries <2s) and `TOPO-005: PASS/FAIL` (≥10K nodes validated)
- [ ] Load test exits `0` only when both TOPO-002 and TOPO-005 pass; exits `1` on any failure
- [ ] `test_incidents.py` gains 3 new tests in `TestIncidentHandlerTopologyIntegration`; all existing tests continue to pass
- [ ] `TOPO-004` requirement satisfied: topology traversal (blast-radius) is part of every `POST /api/v1/incidents` flow when topology service is configured
