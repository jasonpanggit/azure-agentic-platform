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
    return "ai:" + hashlib.md5(",".join(sorted(subscription_ids)).encode(), usedforsecurity=False).hexdigest()[:16]


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
        issue_id = f"ai-{hashlib.md5(f'{issue_type}:{affected_id}'.encode(), usedforsecurity=False).hexdigest()[:12]}"
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
