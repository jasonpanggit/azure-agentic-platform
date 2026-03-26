"""Integration tests for session budget enforcement (AGENT-007).

Validates ROADMAP Phase 2 Success Criterion 5:
A session budget threshold of $5 is enforced: a test session forced to
exceed the limit is aborted with a budget_exceeded event; the Cosmos DB
session record reflects status: aborted with the final cost snapshot.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.shared.budget import (
    BudgetExceededException,
    BudgetTracker,
    MaxIterationsExceededException,
    calculate_cost,
    DEFAULT_BUDGET_THRESHOLD_USD,
    DEFAULT_MAX_ITERATIONS,
)


@pytest.mark.integration
class TestBudgetEnforcement:
    """Verify budget limits are enforced end-to-end."""

    @pytest.fixture()
    def mock_container(self):
        """Mock Cosmos DB container."""
        container = MagicMock()
        container.create_item.return_value = {"id": "sess-int-001", "status": "active"}
        return container

    @pytest.fixture()
    def tracker(self, mock_container):
        return BudgetTracker(
            container=mock_container,
            session_id="sess-int-001",
            incident_id="inc-int-001",
            thread_id="thread-int-abc",
            agent_name="compute-agent",
            threshold_usd=5.00,
            max_iterations=10,
        )

    def test_session_aborted_at_5_dollar_threshold(self, tracker, mock_container):
        """Session exceeding $5 threshold is aborted (SC-5)."""
        mock_container.read_item.return_value = {
            "id": "sess-int-001",
            "incident_id": "inc-int-001",
            "total_tokens": 1_800_000,
            "total_cost_usd": 4.95,
            "iteration_count": 5,
            "status": "active",
            "_etag": "etag-budget",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-int-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {}

        with pytest.raises(BudgetExceededException) as exc_info:
            tracker.check_and_record("sess-int-001", tokens_used=50_000, cost_usd=0.10)

        assert exc_info.value.total_cost_usd == pytest.approx(5.05)
        assert exc_info.value.threshold_usd == 5.00
        assert exc_info.value.session_id == "sess-int-001"

    def test_cosmos_record_shows_aborted_status(self, tracker, mock_container):
        """Cosmos DB record updated to status: aborted on budget exceeded."""
        mock_container.read_item.return_value = {
            "id": "sess-int-001",
            "incident_id": "inc-int-001",
            "total_tokens": 2_000_000,
            "total_cost_usd": 4.99,
            "iteration_count": 8,
            "status": "active",
            "_etag": "etag-status",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-int-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {}

        with pytest.raises(BudgetExceededException):
            tracker.check_and_record("sess-int-001", tokens_used=10_000, cost_usd=0.05)

        replace_call = mock_container.replace_item.call_args
        # replace_item is called with keyword arg body= or positional arg
        body = replace_call.kwargs.get("body") or replace_call[1].get("body") or replace_call[0][1]
        assert body["status"] == "aborted"
        assert "Budget limit" in body["abort_reason"]
        assert body["total_cost_usd"] == pytest.approx(5.04)

    def test_max_iterations_enforced(self, tracker, mock_container):
        """Session aborted when max iterations (10) reached."""
        mock_container.read_item.return_value = {
            "id": "sess-int-001",
            "incident_id": "inc-int-001",
            "total_tokens": 5000,
            "total_cost_usd": 0.05,
            "iteration_count": 9,
            "status": "active",
            "_etag": "etag-iter",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-int-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {}

        with pytest.raises(MaxIterationsExceededException) as exc_info:
            tracker.check_and_record("sess-int-001", tokens_used=100, cost_usd=0.001)

        assert exc_info.value.iterations == 10
        assert exc_info.value.max_iterations == 10

    def test_session_within_budget_continues(self, tracker, mock_container):
        """Session under budget continues normally."""
        mock_container.read_item.return_value = {
            "id": "sess-int-001",
            "incident_id": "inc-int-001",
            "total_tokens": 500,
            "total_cost_usd": 0.005,
            "iteration_count": 1,
            "status": "active",
            "_etag": "etag-ok",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-int-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {"status": "active"}

        result = tracker.check_and_record("sess-int-001", tokens_used=200, cost_usd=0.002)
        assert result["status"] == "active"

    def test_cost_calculation_accuracy(self):
        """Cost calculation uses correct gpt-4o pricing."""
        # 100K input tokens: (100,000 / 1,000,000) * $2.50 = $0.25
        # 50K output tokens: (50,000 / 1,000,000) * $10.00 = $0.50
        # Total: $0.75
        cost = calculate_cost(100_000, 50_000, 2.50, 10.00)
        assert cost == pytest.approx(0.75)

    def test_default_threshold_is_5_dollars(self):
        """Default budget threshold is $5.00."""
        assert DEFAULT_BUDGET_THRESHOLD_USD == 5.00

    def test_default_max_iterations_is_10(self):
        """Default max iterations is 10."""
        assert DEFAULT_MAX_ITERATIONS == 10

    def test_etag_used_for_optimistic_concurrency(self, tracker, mock_container):
        """Cosmos DB updates use ETag for concurrency control."""
        mock_container.read_item.return_value = {
            "id": "sess-int-001",
            "incident_id": "inc-int-001",
            "total_tokens": 100,
            "total_cost_usd": 0.001,
            "iteration_count": 0,
            "status": "active",
            "_etag": "specific-etag-value",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-int-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {"status": "active"}

        tracker.check_and_record("sess-int-001", tokens_used=50, cost_usd=0.0005)

        replace_call = mock_container.replace_item.call_args
        # Verify that the specific etag was passed — either as kwarg or in str repr
        assert replace_call.kwargs.get("etag") == "specific-etag-value" or \
            "specific-etag-value" in str(replace_call)

    def test_budget_exception_message_includes_cost(self):
        """BudgetExceededException message includes session_id and costs."""
        exc = BudgetExceededException(
            session_id="sess-abc",
            total_cost_usd=5.1234,
            threshold_usd=5.00,
        )
        msg = str(exc)
        assert "sess-abc" in msg
        assert "5.00" in msg

    def test_max_iterations_exception_message_includes_counts(self):
        """MaxIterationsExceededException message includes iteration counts."""
        exc = MaxIterationsExceededException(
            session_id="sess-abc",
            iterations=10,
            max_iterations=10,
        )
        msg = str(exc)
        assert "10" in msg

    def test_budget_tracker_constructor_uses_defaults(self, mock_container):
        """BudgetTracker uses DEFAULT_BUDGET_THRESHOLD_USD when threshold_usd is None."""
        tracker = BudgetTracker(
            container=mock_container,
            session_id="sess-defaults",
            incident_id="inc-defaults",
            thread_id="thread-defaults",
            agent_name="sre-agent",
        )
        assert tracker.threshold_usd == DEFAULT_BUDGET_THRESHOLD_USD
        assert tracker.max_iterations == DEFAULT_MAX_ITERATIONS
