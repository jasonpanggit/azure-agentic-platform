from __future__ import annotations
"""Unit tests for the Pattern Analyzer (PLATINT-001, PLATINT-002, PLATINT-003).

Tests cover:
- _severity_score mapping (tests 1–5)
- _group_incidents_by_pattern grouping (tests 6–7)
- _score_pattern scoring math (test 8)
- _extract_top_words returns list of strings (test 9)
- _compute_finops_summary returns dict with expected keys (tests 10–11)
- analyze_patterns returns PatternAnalysisResult with top_patterns <= 5 (test 12)
- Feedback tag aggregation: operator_flagged=True when >= 2 false_positive (test 13)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_gateway.pattern_analyzer import (
    _aggregate_feedback,
    _compute_finops_summary,
    _extract_top_words,
    _group_incidents_by_pattern,
    _run_analysis_sync,
    _score_pattern,
    _severity_score,
    analyze_patterns,
)


# ---------------------------------------------------------------------------
# Tests 1–5: _severity_score
# ---------------------------------------------------------------------------


class TestSeverityScore:
    """_severity_score maps severity strings to numeric scores."""

    def test_sev0_returns_4_0(self):
        """Sev0 maps to 4.0."""
        assert _severity_score("Sev0") == 4.0

    def test_sev1_returns_3_0(self):
        """Sev1 maps to 3.0."""
        assert _severity_score("Sev1") == 3.0

    def test_sev2_returns_2_0(self):
        """Sev2 maps to 2.0."""
        assert _severity_score("Sev2") == 2.0

    def test_sev3_returns_1_0(self):
        """Sev3 maps to 1.0."""
        assert _severity_score("Sev3") == 1.0

    def test_unknown_returns_1_5(self):
        """Unknown severity returns default 1.5."""
        assert _severity_score("unknown") == 1.5


# ---------------------------------------------------------------------------
# Tests 6–7: _group_incidents_by_pattern
# ---------------------------------------------------------------------------


class TestGroupIncidents:
    """_group_incidents_by_pattern groups incidents by (domain, resource_type, detection_rule)."""

    def test_groups_by_tuple(self):
        """3 incidents (2 compute/vm/cpu_alert, 1 network/lb/lb_alert) → 2 groups."""
        incidents = [
            {"domain": "compute", "resource_type": "vm", "detection_rule": "cpu_alert"},
            {"domain": "compute", "resource_type": "vm", "detection_rule": "cpu_alert"},
            {"domain": "network", "resource_type": "lb", "detection_rule": "lb_alert"},
        ]
        groups = _group_incidents_by_pattern(incidents)
        assert len(groups) == 2
        assert len(groups[("compute", "vm", "cpu_alert")]) == 2
        assert len(groups[("network", "lb", "lb_alert")]) == 1

    def test_empty_list(self):
        """Empty list returns empty dict."""
        groups = _group_incidents_by_pattern([])
        assert groups == {}


# ---------------------------------------------------------------------------
# Test 8: _score_pattern
# ---------------------------------------------------------------------------


class TestScorePattern:
    """_score_pattern computes count * avg_severity_score."""

    def test_score_pattern_math(self):
        """3 Sev1 incidents: score = 3 * 3.0 = 9.0."""
        incidents = [
            {"severity": "Sev1"},
            {"severity": "Sev1"},
            {"severity": "Sev1"},
        ]
        score = _score_pattern(incidents)
        assert score == 9.0

    def test_score_pattern_mixed_severity(self):
        """Mixed severities: score = 2 * avg(4.0, 2.0) = 2 * 3.0 = 6.0."""
        incidents = [
            {"severity": "Sev0"},
            {"severity": "Sev2"},
        ]
        score = _score_pattern(incidents)
        assert score == 6.0

    def test_score_pattern_empty(self):
        """Empty list returns 0.0."""
        assert _score_pattern([]) == 0.0


# ---------------------------------------------------------------------------
# Test 9: _extract_top_words
# ---------------------------------------------------------------------------


class TestExtractTopWords:
    """_extract_top_words extracts frequent words from incident titles."""

    def test_extracts_words(self):
        """Titles with repeated words ≥ 4 chars → those words appear in result."""
        incidents = [
            {"title": "High disk usage on vm-prod-01"},
            {"title": "High disk usage on vm-prod-02"},
        ]
        words = _extract_top_words(incidents)
        assert isinstance(words, list)
        # "high", "disk", "usage" all appear twice and have 4+ chars
        assert "high" in words
        assert "disk" in words

    def test_short_words_filtered(self):
        """Words with len < 4 are filtered out."""
        incidents = [
            {"title": "VM is up now"},
        ]
        words = _extract_top_words(incidents)
        # "vm", "is", "up" are all < 4 chars; "now" is 3 chars
        for word in words:
            assert len(word) >= 4

    def test_empty_incidents(self):
        """Empty incident list returns empty list."""
        words = _extract_top_words([])
        assert words == []


# ---------------------------------------------------------------------------
# Tests 10–11: _compute_finops_summary
# ---------------------------------------------------------------------------


class TestComputeFinopsSummary:
    """_compute_finops_summary returns FinOps cost estimates."""

    def test_returns_expected_keys(self):
        """Result has 'wasted_compute_usd' and 'automation_savings_usd' keys."""
        result = _compute_finops_summary([], [])
        assert "wasted_compute_usd" in result
        assert "automation_savings_usd" in result
        assert "complete_remediations" in result
        assert "compute_incidents_30min" in result

    def test_automation_savings_math(self):
        """2 complete remediations × (30/60) × 0.10 = 0.10 USD."""
        remediation_records = [
            {"status": "complete", "action_type": "execute"},
            {"status": "complete", "action_type": "execute"},
        ]
        result = _compute_finops_summary([], remediation_records)
        # 2 * (30/60) * 0.10 = 2 * 0.5 * 0.10 = 0.10
        assert result["automation_savings_usd"] == 0.10
        assert result["complete_remediations"] == 2

    def test_wasted_compute_usd_nonzero_for_compute_incidents(self):
        """Compute incidents contribute to wasted_compute_usd."""
        incidents = [
            {
                "domain": "compute",
                "severity": "Sev1",
                "affected_resources": [{"resource_id": "/subscriptions/abc/vm/01"}],
            }
        ]
        result = _compute_finops_summary(incidents, [])
        assert result["wasted_compute_usd"] > 0.0
        assert result["compute_incidents_30min"] == 1


# ---------------------------------------------------------------------------
# Test 12: analyze_patterns integration (mocked Cosmos)
# ---------------------------------------------------------------------------


class TestAnalyzePatterns:
    """analyze_patterns returns a result dict with top_patterns capped at 5."""

    def _make_incident(self, domain: str, resource_type: str, detection_rule: str, severity: str = "Sev1") -> dict:
        """Helper to build a minimal incident doc."""
        return {
            "incident_id": f"inc-{domain}-{resource_type}-{detection_rule}",
            "domain": domain,
            "resource_type": resource_type,
            "detection_rule": detection_rule,
            "severity": severity,
            "created_at": "2026-04-01T00:00:00+00:00",
            "title": f"{domain} {resource_type} alert",
            "affected_resources": [],
        }

    def test_analyze_patterns_returns_result_with_max_5_patterns(self):
        """Mock Cosmos returning 10 incidents across 7 patterns → top_patterns <= 5."""
        # 7 distinct patterns
        pattern_specs = [
            ("compute", "vm", "cpu_alert"),
            ("compute", "vm", "memory_alert"),
            ("network", "lb", "lb_alert"),
            ("storage", "blob", "capacity_alert"),
            ("security", "keyvault", "access_alert"),
            ("arc", "server", "connectivity_alert"),
            ("sre", "service", "latency_alert"),
        ]
        # Create 10 incidents: first 3 patterns get 2 each, last 4 get 1 each
        incidents = []
        for i, (domain, rt, rule) in enumerate(pattern_specs):
            count = 2 if i < 3 else 1
            for _ in range(count):
                incidents.append(self._make_incident(domain, rt, rule))

        assert len(incidents) == 10

        def mock_query(query, **kwargs):
            # Return incidents for the incidents container, empty for others
            if "incidents" in query or ("@cutoff" in query and "@action_type" not in query):
                # This is the incidents query
                return incidents
            return []

        # Set up mock Cosmos client
        mock_container = MagicMock()
        mock_container.query_items.side_effect = lambda query, **kwargs: iter(
            incidents if "action_type" not in query and "proposed_at" not in query else []
        )
        mock_container.upsert_item.return_value = None

        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_container

        mock_cosmos = MagicMock()
        mock_cosmos.get_database_client.return_value = mock_db

        result = _run_analysis_sync(mock_cosmos)

        assert result is not None
        assert "top_patterns" in result
        assert len(result["top_patterns"]) <= 5
        assert result["total_incidents_analyzed"] == 10
        assert "finops_summary" in result
        assert "analysis_date" in result


# ---------------------------------------------------------------------------
# Test 13: Feedback aggregation
# ---------------------------------------------------------------------------


class TestFeedbackAggregation:
    """_aggregate_feedback correctly detects operator_flagged patterns."""

    def test_operator_flagged_on_false_positive(self):
        """2+ approvals with 'false_positive' tag → operator_flagged=True."""
        pattern_key = ("compute", "vm", "cpu_alert")
        approval_records = [
            {
                "domain": "compute",
                "resource_type": "vm",
                "detection_rule": "cpu_alert",
                "feedback_tags": ["false_positive"],
            },
            {
                "domain": "compute",
                "resource_type": "vm",
                "detection_rule": "cpu_alert",
                "feedback_tags": ["false_positive", "not_useful"],
            },
        ]
        operator_flagged, common_feedback = _aggregate_feedback(approval_records, pattern_key)
        assert operator_flagged is True
        assert "false_positive" in common_feedback

    def test_operator_not_flagged_with_one_false_positive(self):
        """Only 1 approval with 'false_positive' → operator_flagged=False."""
        pattern_key = ("compute", "vm", "cpu_alert")
        approval_records = [
            {
                "domain": "compute",
                "resource_type": "vm",
                "detection_rule": "cpu_alert",
                "feedback_tags": ["false_positive"],
            },
        ]
        operator_flagged, common_feedback = _aggregate_feedback(approval_records, pattern_key)
        assert operator_flagged is False

    def test_no_matching_approvals(self):
        """No approvals match the pattern key → (False, [])."""
        pattern_key = ("compute", "vm", "cpu_alert")
        approval_records = [
            {
                "domain": "network",
                "resource_type": "lb",
                "detection_rule": "lb_alert",
                "feedback_tags": ["false_positive"],
            },
        ]
        operator_flagged, common_feedback = _aggregate_feedback(approval_records, pattern_key)
        assert operator_flagged is False
        assert common_feedback == []

    def test_common_feedback_top_3(self):
        """Returns top-3 most frequent tags from Counter."""
        pattern_key = ("security", "keyvault", "access_alert")
        approval_records = [
            {
                "domain": "security",
                "resource_type": "keyvault",
                "detection_rule": "access_alert",
                "feedback_tags": ["false_positive", "not_useful", "noisy"],
            },
            {
                "domain": "security",
                "resource_type": "keyvault",
                "detection_rule": "access_alert",
                "feedback_tags": ["false_positive", "noisy"],
            },
            {
                "domain": "security",
                "resource_type": "keyvault",
                "detection_rule": "access_alert",
                "feedback_tags": ["false_positive"],
            },
        ]
        operator_flagged, common_feedback = _aggregate_feedback(approval_records, pattern_key)
        assert operator_flagged is True
        # "false_positive" appears 3 times — should be first
        assert common_feedback[0] == "false_positive"
        # At most 3 tags returned
        assert len(common_feedback) <= 3


# ---------------------------------------------------------------------------
# Tests 14–19: compute_mttr_by_issue_type (LOOP-003)
# ---------------------------------------------------------------------------


class TestComputeMttrByIssueType:
    """compute_mttr_by_issue_type computes P50/P95/mean MTTR grouped by issue type."""

    def test_compute_mttr_empty_incidents(self):
        """Empty incident list returns empty dict."""
        from services.api_gateway.pattern_analyzer import compute_mttr_by_issue_type

        result = compute_mttr_by_issue_type([])
        assert result == {}

    def test_compute_mttr_no_resolved_incidents(self):
        """Incidents with status != resolved return empty dict."""
        from services.api_gateway.pattern_analyzer import compute_mttr_by_issue_type

        incidents = [
            {
                "status": "new",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": "2026-04-01T10:00:00+00:00",
            },
            {
                "status": "open",
                "domain": "network",
                "detection_rule": "NSGDrop",
                "severity": "Sev2",
                "created_at": "2026-04-01T11:00:00+00:00",
            },
            {
                "status": "investigating",
                "domain": "security",
                "detection_rule": "DefenderAlert",
                "severity": "Sev0",
                "created_at": "2026-04-01T12:00:00+00:00",
            },
        ]
        result = compute_mttr_by_issue_type(incidents)
        assert result == {}

    def test_compute_mttr_single_resolved(self):
        """Single resolved incident with 30-minute MTTR returns correct stats."""
        from services.api_gateway.pattern_analyzer import compute_mttr_by_issue_type

        incidents = [
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": "2026-04-01T10:00:00+00:00",
                "resolved_at": "2026-04-01T10:30:00+00:00",
            }
        ]
        result = compute_mttr_by_issue_type(incidents)
        assert "compute:HighCPU:Sev1" in result
        stats = result["compute:HighCPU:Sev1"]
        assert stats["count"] == 1
        assert stats["p50_min"] == 30.0
        assert stats["p95_min"] == 30.0
        assert stats["mean_min"] == 30.0

    def test_compute_mttr_multiple_resolved(self):
        """4 resolved incidents (10, 20, 30, 60 min) → correct P50/P95/mean."""
        from services.api_gateway.pattern_analyzer import compute_mttr_by_issue_type

        base_created = "2026-04-01T10:00:00+00:00"
        incidents = [
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": base_created,
                "resolved_at": "2026-04-01T10:10:00+00:00",  # 10 min
            },
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": base_created,
                "resolved_at": "2026-04-01T10:20:00+00:00",  # 20 min
            },
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": base_created,
                "resolved_at": "2026-04-01T10:30:00+00:00",  # 30 min
            },
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": base_created,
                "resolved_at": "2026-04-01T11:00:00+00:00",  # 60 min
            },
        ]
        result = compute_mttr_by_issue_type(incidents)
        assert "compute:HighCPU:Sev1" in result
        stats = result["compute:HighCPU:Sev1"]
        assert stats["count"] == 4
        # sorted: [10, 20, 30, 60]; p50_idx = int(4*0.50) = 2 → 30.0
        assert stats["p50_min"] == 30.0
        # p95_idx = min(int(4*0.95), 3) = min(3, 3) = 3 → 60.0
        assert stats["p95_min"] == 60.0
        # mean = (10+20+30+60)/4 = 30.0
        assert stats["mean_min"] == 30.0

    def test_compute_mttr_groups_by_issue_type(self):
        """Incidents from different domains produce separate keys in result."""
        from services.api_gateway.pattern_analyzer import compute_mttr_by_issue_type

        incidents = [
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": "2026-04-01T10:00:00+00:00",
                "resolved_at": "2026-04-01T10:30:00+00:00",
            },
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                "created_at": "2026-04-01T11:00:00+00:00",
                "resolved_at": "2026-04-01T11:45:00+00:00",
            },
            {
                "status": "resolved",
                "domain": "network",
                "detection_rule": "NSGDrop",
                "severity": "Sev2",
                "created_at": "2026-04-01T12:00:00+00:00",
                "resolved_at": "2026-04-01T12:20:00+00:00",
            },
        ]
        result = compute_mttr_by_issue_type(incidents)
        assert len(result) == 2
        assert "compute:HighCPU:Sev1" in result
        assert "network:NSGDrop:Sev2" in result
        assert result["compute:HighCPU:Sev1"]["count"] == 2

    def test_compute_mttr_skips_negative_mttr(self):
        """Incident where resolved_at < created_at is skipped."""
        from services.api_gateway.pattern_analyzer import compute_mttr_by_issue_type

        incidents = [
            {
                "status": "resolved",
                "domain": "compute",
                "detection_rule": "HighCPU",
                "severity": "Sev1",
                # resolved_at is BEFORE created_at — negative MTTR
                "created_at": "2026-04-01T10:30:00+00:00",
                "resolved_at": "2026-04-01T10:00:00+00:00",
            }
        ]
        result = compute_mttr_by_issue_type(incidents)
        assert result == {}
