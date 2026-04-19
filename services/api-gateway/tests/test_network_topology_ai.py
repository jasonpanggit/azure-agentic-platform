"""Unit tests for network_topology_ai.py — Phase 109."""
from __future__ import annotations

import json
import time
import threading
import pytest

from services.api_gateway.network_topology_ai import (
    _AI_CACHE,
    _AI_CACHE_LOCK,
    _AI_TTL_SECONDS,
    _cache_key,
    _parse_and_validate,
    get_ai_issues,
    trigger_ai_analysis,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_cache():
    with _AI_CACHE_LOCK:
        _AI_CACHE.clear()


def _inject_entry(subscription_ids, status, issues=None, offset=0):
    key = _cache_key(subscription_ids)
    with _AI_CACHE_LOCK:
        _AI_CACHE[key] = {
            "status": status,
            "issues": issues or [],
            "error": None,
            "expires_at": time.monotonic() + _AI_TTL_SECONDS + offset,
        }
    return key


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_ai_issues_pending_when_empty():
    _clear_cache()
    result = get_ai_issues(["sub-1"])
    assert result == {"status": "pending", "issues": [], "error": None}


def test_get_ai_issues_returns_cached_ready():
    _clear_cache()
    fake_issues = [{"id": "ai-abc", "type": "ai_test", "severity": "medium", "title": "Test"}]
    _inject_entry(["sub-1"], "ready", fake_issues)
    result = get_ai_issues(["sub-1"])
    assert result["status"] == "ready"
    assert result["issues"] == fake_issues


def test_get_ai_issues_expired_entry_returns_pending():
    _clear_cache()
    _inject_entry(["sub-1"], "ready", offset=-(_AI_TTL_SECONDS + 1))
    result = get_ai_issues(["sub-1"])
    assert result["status"] == "pending"
    assert result["issues"] == []


def test_parse_and_validate_valid_json():
    raw = json.dumps([{
        "type": "ai_test_issue",
        "severity": "high",
        "title": "Test Issue",
        "explanation": "Some explanation.",
        "impact": "Some impact.",
        "affected_resource_id": "/subscriptions/sub1/resourceGroups/rg1",
        "affected_resource_name": "rg1",
        "related_resource_ids": [],
        "remediation_steps": [{"step": 1, "action": "Do something", "cli": None}],
        "portal_link": "",
    }])
    issues = _parse_and_validate(raw)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["id"].startswith("ai-")
    assert issue["source"] == "ai"
    assert issue["severity"] in ("critical", "high", "medium", "low")


def test_parse_and_validate_strips_code_fences():
    inner = json.dumps([{
        "type": "ai_fenced",
        "severity": "low",
        "title": "Fenced Issue",
        "explanation": "",
        "impact": "",
        "affected_resource_id": "",
        "affected_resource_name": "",
        "related_resource_ids": [],
        "remediation_steps": [],
        "portal_link": "",
    }])
    raw = f"```json\n{inner}\n```"
    issues = _parse_and_validate(raw)
    assert len(issues) == 1
    assert issues[0]["type"] == "ai_fenced"


def test_parse_and_validate_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_and_validate("not json")


def test_parse_and_validate_invalid_severity_defaults_to_medium():
    raw = json.dumps([{
        "type": "ai_bad_severity",
        "severity": "extreme",
        "title": "Bad Severity",
        "explanation": "",
        "impact": "",
        "affected_resource_id": "",
        "affected_resource_name": "",
        "related_resource_ids": [],
        "remediation_steps": [],
        "portal_link": "",
    }])
    issues = _parse_and_validate(raw)
    assert issues[0]["severity"] == "medium"


def test_parse_and_validate_skips_items_missing_type():
    raw = json.dumps([
        {"title": "T1"},  # missing type — should be skipped
        {"type": "ai_has_type", "title": "T2", "severity": "low",
         "explanation": "", "impact": "", "affected_resource_id": "",
         "affected_resource_name": "", "related_resource_ids": [],
         "remediation_steps": [], "portal_link": ""},
    ])
    issues = _parse_and_validate(raw)
    assert len(issues) == 1
    assert issues[0]["type"] == "ai_has_type"


def test_trigger_ai_analysis_sets_pending():
    _clear_cache()

    # Patch _run_analysis to be a no-op so the thread doesn't call LLM
    import services.api_gateway.network_topology_ai as mod
    original = mod._run_analysis

    def _noop(key, subscription_ids, snapshot):
        pass  # do nothing — leave the pending entry

    mod._run_analysis = _noop
    try:
        trigger_ai_analysis(["sub-1"], {})
        time.sleep(0.05)
        result = get_ai_issues(["sub-1"])
        assert result["status"] == "pending"
    finally:
        mod._run_analysis = original


def test_cache_key_is_order_independent():
    assert _cache_key(["b", "a"]) == _cache_key(["a", "b"])
