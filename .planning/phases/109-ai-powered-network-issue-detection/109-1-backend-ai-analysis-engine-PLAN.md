---
wave: 1
phase: 109
title: Backend — Async AI Analysis Engine + ai-issues Endpoint
depends_on: "Phase 108 (fetch_network_topology, NetworkIssue schema, 17 detectors)"
files_modified:
  - services/api-gateway/network_topology_ai.py (NEW)
  - services/api-gateway/network_topology_endpoints.py (add GET /ai-issues route)
  - tests/test_network_topology_ai.py (NEW)
autonomous: true
---

# Wave 1 — Backend: Async AI Analysis Engine + ai-issues Endpoint

## Goal

Build a standalone module `network_topology_ai.py` that:
1. Accepts a topology snapshot (nodes + issues already found by rule engine)
2. Chunks it to ≤8k tokens
3. Calls the existing OpenAI client (`_get_openai_client()` from `foundry.py`) with a structured prompt
4. Validates + normalises the LLM response into `NetworkIssue` dicts with `source="ai"`
5. Stores results in a short-lived in-memory cache (5 min TTL, keyed by sorted subscription IDs)
6. Exposes `trigger_ai_analysis()` (fire-and-forget, runs in background thread) and `get_ai_issues()` (cache read)

A new FastAPI route `GET /api/v1/network-topology/ai-issues` is added to `network_topology_endpoints.py`.

---

## Task 1 — Create `network_topology_ai.py`

<read_first>
- services/api-gateway/network_topology_service.py lines 1–80 (NetworkIssue TypedDict, _make_issue_id, _SEVERITY_ORDER)
- services/api-gateway/foundry.py lines 90–140 (_get_openai_client signature and return type)
- services/api-gateway/arg_cache.py lines 1–110 (cache pattern for TTL reference only — we use a separate dict, not arg_cache)
</read_first>

<action>
**Step 0 — Add `source` field to `NetworkIssue` TypedDict in `network_topology_service.py`:**

In the `NetworkIssue` TypedDict definition, add `source: Optional[str]` as the last field before the closing class body. This keeps the Python schema canonical — rule-based issues have `source=None` implicitly (no change to existing call sites), AI issues set `"source": "ai"` explicitly.

```python
    source: Optional[str]  # "rule" | "ai" | None — added Phase 109
```

Also ensure `Optional` is in the `typing` import at the top of `network_topology_service.py`.

**Step 1 — Create `/services/api-gateway/network_topology_ai.py`** with the following exact structure:

```python
from __future__ import annotations
"""AI-powered network issue analysis — Phase 109.

Runs asynchronously after fetch_network_topology() returns rule-based issues.
Calls the LLM (via _get_openai_client) with a summarised topology JSON,
validates the response against NetworkIssue schema, and caches results for 5 min.

Public surface:
  trigger_ai_analysis(subscription_ids, topology_snapshot) -> None  (fire-and-forget)
  get_ai_issues(subscription_ids) -> Dict[str, Any]
    Returns {"status": "pending"|"ready"|"error", "issues": List[NetworkIssue], "error": str|None}
"""

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache: key -> {"status": str, "issues": list, "error": str|None, "expires_at": float}
# ---------------------------------------------------------------------------
_AI_CACHE: Dict[str, Dict[str, Any]] = {}
_AI_CACHE_LOCK = threading.Lock()
_AI_TTL_SECONDS = 300  # 5 min

_MAX_NODES_IN_PROMPT = 20      # top N nodes sent to LLM
_MAX_ISSUES_IN_PROMPT = 30     # existing rule issues summarised (not full objects)

# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def _cache_key(subscription_ids: List[str]) -> str:
    return "ai:" + hashlib.md5(",".join(sorted(subscription_ids)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public: get cached AI issues
# ---------------------------------------------------------------------------

def get_ai_issues(subscription_ids: List[str]) -> Dict[str, Any]:
    """Return cached AI analysis result or {"status": "pending"} if not ready."""
    key = _cache_key(subscription_ids)
    with _AI_CACHE_LOCK:
        entry = _AI_CACHE.get(key)
    if entry is None:
        return {"status": "pending", "issues": [], "error": None}
    if entry.get("expires_at", 0) < time.monotonic():
        with _AI_CACHE_LOCK:
            _AI_CACHE.pop(key, None)
        return {"status": "pending", "issues": [], "error": None}
    return {"status": entry["status"], "issues": entry.get("issues", []), "error": entry.get("error")}


# ---------------------------------------------------------------------------
# Public: fire-and-forget trigger
# ---------------------------------------------------------------------------

def trigger_ai_analysis(
    subscription_ids: List[str],
    topology_snapshot: Dict[str, Any],
) -> None:
    """Kick off LLM analysis in a daemon thread. Returns immediately."""
    key = _cache_key(subscription_ids)
    # Don't re-run if a fresh result is already cached
    with _AI_CACHE_LOCK:
        entry = _AI_CACHE.get(key)
        if entry and entry.get("status") == "ready" and entry.get("expires_at", 0) > time.monotonic():
            logger.debug("network_topology_ai: cache hit, skipping re-analysis | key=%s", key)
            return
        # Mark as pending immediately so the frontend shows the spinner
        _AI_CACHE[key] = {"status": "pending", "issues": [], "error": None, "expires_at": time.monotonic() + _AI_TTL_SECONDS}

    t = threading.Thread(
        target=_run_analysis,
        args=(key, subscription_ids, topology_snapshot),
        daemon=True,
    )
    t.start()
    logger.info("network_topology_ai: analysis thread started | key=%s subs=%s", key, subscription_ids)


# ---------------------------------------------------------------------------
# Internal: run analysis and store result
# ---------------------------------------------------------------------------

def _run_analysis(
    key: str,
    subscription_ids: List[str],
    topology_snapshot: Dict[str, Any],
) -> None:
    start = time.monotonic()
    try:
        issues = _analyze_topology(topology_snapshot)
        with _AI_CACHE_LOCK:
            _AI_CACHE[key] = {
                "status": "ready",
                "issues": issues,
                "error": None,
                "expires_at": time.monotonic() + _AI_TTL_SECONDS,
            }
        logger.info(
            "network_topology_ai: analysis complete | key=%s issues=%d (%.0fms)",
            key, len(issues), (time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        logger.error("network_topology_ai: analysis failed | key=%s error=%s", key, exc, exc_info=True)
        with _AI_CACHE_LOCK:
            _AI_CACHE[key] = {
                "status": "error",
                "issues": [],
                "error": str(exc),
                "expires_at": time.monotonic() + _AI_TTL_SECONDS,
            }


# ---------------------------------------------------------------------------
# Internal: build prompt + call LLM
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an Azure network security and architecture expert performing a deep topology analysis.

You will receive a JSON object describing an Azure network topology: nodes (VNets, subnets, NSGs,
VMs, gateways, firewalls, load balancers, private endpoints) and a summary of issues already
detected by automated rules.

Your task is to identify issues the automated rules DID NOT catch, such as:
- Novel security misconfigurations
- Architectural anti-patterns (e.g. spoke VNets peered directly to each other, bypassing hub)
- Cross-resource risks (e.g. unexpected reachability paths, transit routing chains)
- Compliance gaps aligned to CIS Azure Benchmark 2.0
- Redundancy / resilience gaps

Return ONLY a JSON array (no markdown, no prose). Each element must match this schema exactly:
{
  "type": "<snake_case string, e.g. ai_spoke_to_spoke_peering>",
  "severity": "critical" | "high" | "medium" | "low",
  "title": "<max 80 chars>",
  "explanation": "<2-4 plain-English sentences>",
  "impact": "<1-2 sentences>",
  "affected_resource_id": "<Azure resource ID or empty string>",
  "affected_resource_name": "<display name>",
  "related_resource_ids": ["<resource ID>", ...],
  "remediation_steps": [{"step": 1, "action": "<instruction>", "cli": "<az CLI command or null>"}],
  "portal_link": "<https://portal.azure.com/... or empty string>"
}

Return [] if no additional issues are found. Never repeat issues already in the existing_issues list.\
"""


def _build_prompt(topology_snapshot: Dict[str, Any]) -> str:
    """Summarise topology to fit within ~8k tokens."""
    nodes: List[Dict[str, Any]] = topology_snapshot.get("nodes", [])
    existing_issues: List[Dict[str, Any]] = topology_snapshot.get("issues", [])

    # Score node "complexity" as a proxy for risk surface: prefer NSGs, firewalls, VNets with many subnets
    def _node_score(n: Dict[str, Any]) -> int:
        t = n.get("type", "")
        scores = {"nsg": 4, "firewall": 4, "vnet": 3, "subnet": 2, "gateway": 3, "pe": 2, "lb": 2, "vm": 1}
        return scores.get(t, 0)

    top_nodes = sorted(nodes, key=_node_score, reverse=True)[:_MAX_NODES_IN_PROMPT]

    # Strip heavyweight / non-informative data fields before serialising
    def _slim_node(n: Dict[str, Any]) -> Dict[str, Any]:
        data = {k: v for k, v in (n.get("data") or {}).items()
                if k not in ("health",) and v not in (None, "", [], {})}
        return {"id": n["id"], "type": n["type"], "label": n.get("label", ""), "data": data}

    slim_nodes = [_slim_node(n) for n in top_nodes]

    # Summarise existing issues (type + title only, to avoid prompt bloat)
    existing_summary = [
        {"type": i.get("type", ""), "title": i.get("title", "")}
        for i in existing_issues[:_MAX_ISSUES_IN_PROMPT]
    ]

    payload = {
        "node_count": len(nodes),
        "top_nodes": slim_nodes,
        "existing_issues": existing_summary,
    }

    return json.dumps(payload, default=str)


def _analyze_topology(topology_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Call LLM and return validated NetworkIssue dicts with source='ai'."""
    from services.api_gateway.foundry import _get_openai_client  # local import avoids circular

    user_content = _build_prompt(topology_snapshot)

    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=2000,
        temperature=0.2,
    )

    raw_text = (response.choices[0].message.content or "").strip()
    return _parse_and_validate(raw_text)


def _parse_and_validate(raw_text: str) -> List[Dict[str, Any]]:
    """Parse LLM JSON output, validate each item, prefix IDs with 'ai-'."""
    # Strip markdown code fences if present
    text = raw_text
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(l for l in lines if not l.startswith("```")).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise ValueError(f"LLM returned non-list JSON: {type(parsed)}")

    valid: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for item in parsed:
        if not isinstance(item, dict):
            continue
        # Required fields
        issue_type = str(item.get("type", "")).strip()
        severity = str(item.get("severity", "medium")).strip().lower()
        title = str(item.get("title", "")).strip()[:80]
        if not issue_type or not title:
            logger.debug("network_topology_ai: skipping item missing type/title")
            continue
        if severity not in ("critical", "high", "medium", "low"):
            severity = "medium"

        affected_id = str(item.get("affected_resource_id", ""))
        issue_id = f"ai-{hashlib.md5(f'{issue_type}:{affected_id}'.encode()).hexdigest()[:12]}"
        if issue_id in seen_ids:
            continue
        seen_ids.add(issue_id)

        remediation_steps = []
        for step in (item.get("remediation_steps") or []):
            if isinstance(step, dict):
                remediation_steps.append({
                    "step": int(step.get("step", 1)),
                    "action": str(step.get("action", "")),
                    "cli": step.get("cli") or None,
                })

        valid.append({
            "id": issue_id,
            "type": issue_type,
            "severity": severity,
            "title": title,
            "explanation": str(item.get("explanation", "")),
            "impact": str(item.get("impact", "")),
            "affected_resource_id": affected_id,
            "affected_resource_name": str(item.get("affected_resource_name", "")),
            "related_resource_ids": [str(r) for r in (item.get("related_resource_ids") or [])],
            "remediation_steps": remediation_steps,
            "portal_link": str(item.get("portal_link", "")),
            "auto_fix_available": False,
            "auto_fix_label": None,
            "source": "ai",
            # Backward-compat nulls
            "source_nsg_id": None,
            "dest_nsg_id": None,
            "port": None,
            "description": None,
        })

    return valid
```
</action>

<acceptance_criteria>
- `grep -n "def trigger_ai_analysis" services/api-gateway/network_topology_ai.py` → line exists
- `grep -n "def get_ai_issues" services/api-gateway/network_topology_ai.py` → line exists
- `grep -n "def _parse_and_validate" services/api-gateway/network_topology_ai.py` → line exists
- `grep -n '"source": "ai"' services/api-gateway/network_topology_ai.py` → line exists
- `grep -n "_AI_TTL_SECONDS = 300" services/api-gateway/network_topology_ai.py` → line exists
- `grep -n "gpt-4.1" services/api-gateway/network_topology_ai.py` → model name present
</acceptance_criteria>

---

## Task 2 — Add `GET /api/v1/network-topology/ai-issues` to `network_topology_endpoints.py`

<read_first>
- services/api-gateway/network_topology_endpoints.py (full file — understand router, auth pattern, existing routes)
- services/api-gateway/network_topology_ai.py (just created — imports needed: trigger_ai_analysis, get_ai_issues)
</read_first>

<action>
Add the following to `network_topology_endpoints.py`:

1. **Import block** — add after the existing `from services.api_gateway.network_topology_service import ...` import:
```python
from services.api_gateway.network_topology_ai import (
    get_ai_issues,
    trigger_ai_analysis,
)
```

2. **Modify `get_topology()`** — after `result = fetch_network_topology(...)` and before the `logger.info(...)` call, add:
```python
    # Phase 109: kick off async AI analysis (fire-and-forget)
    trigger_ai_analysis(subscription_ids, result)
```

3. **New endpoint** — add after the `get_topology` function (before `remediate_issue`):
```python
@router.get("/ai-issues")
async def get_ai_issues_endpoint(
    request: Request,
    subscription_id: Optional[str] = Query(None, description="Filter by subscription ID"),
    token: Dict[str, Any] = Depends(verify_token),
) -> Dict[str, Any]:
    """Return AI-detected network issues from the async analysis layer.

    Returns {"status": "pending"|"ready"|"error", "issues": [...], "error": str|None}.
    The client polls this endpoint every 3s after loading topology until status == "ready".
    Issues have source="ai" and IDs prefixed with "ai-".
    """
    start_time = time.monotonic()
    subscription_ids = resolve_subscription_ids(subscription_id, request)
    result = get_ai_issues(subscription_ids)
    duration_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "GET /network-topology/ai-issues → status=%s issues=%d (%.0fms)",
        result.get("status"), len(result.get("issues", [])), duration_ms,
    )
    return result
```
</action>

<acceptance_criteria>
- `grep -n "ai-issues" services/api-gateway/network_topology_endpoints.py` → line exists (route decorator)
- `grep -n "trigger_ai_analysis" services/api-gateway/network_topology_endpoints.py` → called inside get_topology
- `grep -n "from services.api_gateway.network_topology_ai import" services/api-gateway/network_topology_endpoints.py` → import line exists
- `grep -n "get_ai_issues_endpoint" services/api-gateway/network_topology_endpoints.py` → function defined
</acceptance_criteria>

---

## Task 3 — Unit tests for `network_topology_ai.py`

<read_first>
- services/api-gateway/network_topology_ai.py (full, just created)
- tests/test_network_topology_service.py (test style and import patterns for this module)
</read_first>

<action>
Create `tests/test_network_topology_ai.py` with tests covering:

1. **`test_get_ai_issues_pending_when_empty`** — `get_ai_issues(["sub-1"])` returns `{"status": "pending", "issues": [], "error": None}` when cache is empty.

2. **`test_get_ai_issues_returns_cached_ready`** — manually inject a "ready" entry into `_AI_CACHE` and assert `get_ai_issues(["sub-1"])` returns `status="ready"` with the injected issues.

3. **`test_get_ai_issues_expired_entry_returns_pending`** — inject a "ready" entry with `expires_at = time.monotonic() - 1` and assert `get_ai_issues(["sub-1"])` returns `status="pending"`.

4. **`test_parse_and_validate_valid_json`** — call `_parse_and_validate` with a valid JSON array string and assert: (a) returns a list with one issue, (b) `issue["id"]` starts with `"ai-"`, (c) `issue["source"] == "ai"`, (d) `issue["severity"]` is one of the four valid values.

5. **`test_parse_and_validate_strips_code_fences`** — call `_parse_and_validate` with input wrapped in ` ```json ... ``` ` and assert valid issue returned.

6. **`test_parse_and_validate_invalid_json_raises`** — call `_parse_and_validate("not json")` and assert `ValueError` raised.

7. **`test_parse_and_validate_invalid_severity_defaults_to_medium`** — pass an item with `"severity": "extreme"` and assert output has `"severity": "medium"`.

8. **`test_parse_and_validate_skips_items_missing_type`** — pass `[{"title": "T1"}, {"type": "t", "title": "T2"}]` and assert only 1 issue returned.

9. **`test_trigger_ai_analysis_sets_pending`** — mock `_run_analysis` to do nothing (replace with a no-op thread), call `trigger_ai_analysis(["sub-1"], {})`, sleep 0.05s, assert cache has `status="pending"` entry for the key.

10. **`test_cache_key_is_order_independent`** — assert `_cache_key(["b", "a"]) == _cache_key(["a", "b"])`.

Use `pytest` + `unittest.mock.patch` where needed. No real network calls.
</action>

<acceptance_criteria>
- `grep -c "def test_" tests/test_network_topology_ai.py` → output ≥ 10
- `grep -n "from services.api_gateway.network_topology_ai import" tests/test_network_topology_ai.py` → import line exists
- `python -m pytest tests/test_network_topology_ai.py -x -q 2>&1 | tail -5` → `passed` with 0 failures (run from repo root with `PYTHONPATH=.`)
</acceptance_criteria>

---

## Verification

After all three tasks:

```bash
# Lint
cd /Users/jasonmba/workspace/azure-agentic-platform
python -m py_compile services/api-gateway/network_topology_ai.py && echo "OK"
python -m py_compile services/api-gateway/network_topology_endpoints.py && echo "OK"

# Tests
PYTHONPATH=. python -m pytest tests/test_network_topology_ai.py -x -q
```

Expected: both `py_compile` print `OK`, all 10+ tests pass.

## Must-Haves

- [ ] `network_topology_ai.py` exists with `trigger_ai_analysis`, `get_ai_issues`, `_parse_and_validate`
- [ ] `source="ai"` on every AI-generated issue
- [ ] IDs prefixed `ai-`
- [ ] `GET /api/v1/network-topology/ai-issues` route registered
- [ ] `trigger_ai_analysis` called from within `get_topology()` (fire-and-forget, not awaited)
- [ ] 5-min TTL cache (`_AI_TTL_SECONDS = 300`)
- [ ] 10+ unit tests, all passing
- [ ] No direct `import` of `foundry._get_openai_client` at module level (local import inside function to avoid circular)
