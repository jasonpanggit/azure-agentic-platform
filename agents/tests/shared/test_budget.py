"""Tests for agents.shared.budget (AGENT-007)."""
import pytest
from unittest.mock import MagicMock
from agents.shared.budget import (
    BudgetExceededException,
    MaxIterationsExceededException,
    BudgetTracker,
    calculate_cost,
    DEFAULT_BUDGET_THRESHOLD_USD,
    DEFAULT_MAX_ITERATIONS,
)


class TestCalculateCost:
    """Verify cost calculation from token counts."""

    def test_zero_tokens_returns_zero(self):
        assert calculate_cost(0, 0, 2.50, 10.00) == 0.0

    def test_input_only_cost(self):
        # 1M input tokens at $2.50/1M = $2.50
        cost = calculate_cost(1_000_000, 0, 2.50, 10.00)
        assert abs(cost - 2.50) < 0.001

    def test_output_only_cost(self):
        # 1M output tokens at $10.00/1M = $10.00
        cost = calculate_cost(0, 1_000_000, 2.50, 10.00)
        assert abs(cost - 10.00) < 0.001

    def test_mixed_cost(self):
        # 500K input ($1.25) + 100K output ($1.00) = $2.25
        cost = calculate_cost(500_000, 100_000, 2.50, 10.00)
        assert abs(cost - 2.25) < 0.001


class TestBudgetDefaults:
    """Verify budget defaults."""

    def test_default_threshold(self):
        assert DEFAULT_BUDGET_THRESHOLD_USD == 5.00

    def test_default_max_iterations(self):
        assert DEFAULT_MAX_ITERATIONS == 10


class TestBudgetTracker:
    """Verify BudgetTracker enforces limits."""

    @pytest.fixture()
    def mock_container(self):
        container = MagicMock()
        container.create_item.return_value = {"id": "sess-001", "status": "active"}
        return container

    @pytest.fixture()
    def tracker(self, mock_container):
        return BudgetTracker(
            container=mock_container,
            session_id="sess-001",
            incident_id="inc-001",
            thread_id="thread-abc",
            agent_name="compute-agent",
            threshold_usd=5.00,
            max_iterations=10,
        )

    def test_create_session_sets_active_status(self, tracker, mock_container):
        tracker.create_session()
        call_args = mock_container.create_item.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body") or call_args[0][0]
        assert body["status"] == "active"
        assert body["total_cost_usd"] == 0.0
        assert body["total_tokens"] == 0

    def test_check_and_record_raises_on_budget_exceeded(self, tracker, mock_container):
        mock_container.read_item.return_value = {
            "id": "sess-001",
            "incident_id": "inc-001",
            "total_tokens": 900_000,
            "total_cost_usd": 4.90,
            "iteration_count": 2,
            "status": "active",
            "_etag": "etag-1",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {}

        with pytest.raises(BudgetExceededException) as exc_info:
            tracker.check_and_record("sess-001", tokens_used=50_000, cost_usd=0.20)

        assert exc_info.value.total_cost_usd == pytest.approx(5.10)
        assert exc_info.value.threshold_usd == 5.00

        # Verify Cosmos record updated to aborted
        replace_call = mock_container.replace_item.call_args
        body = replace_call.kwargs.get("body") or replace_call[0][1]
        assert body["status"] == "aborted"

    def test_check_and_record_raises_on_max_iterations(self, tracker, mock_container):
        mock_container.read_item.return_value = {
            "id": "sess-001",
            "incident_id": "inc-001",
            "total_tokens": 1000,
            "total_cost_usd": 0.01,
            "iteration_count": 9,
            "status": "active",
            "_etag": "etag-2",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {}

        with pytest.raises(MaxIterationsExceededException):
            tracker.check_and_record("sess-001", tokens_used=100, cost_usd=0.001)

    def test_check_and_record_within_limits_returns_record(self, tracker, mock_container):
        mock_container.read_item.return_value = {
            "id": "sess-001",
            "incident_id": "inc-001",
            "total_tokens": 1000,
            "total_cost_usd": 0.01,
            "iteration_count": 1,
            "status": "active",
            "_etag": "etag-3",
            "threshold_usd": 5.00,
            "max_iterations": 10,
            "thread_id": "thread-abc",
            "agent_name": "compute-agent",
            "last_updated": "2026-03-26T14:00:00Z",
            "abort_reason": None,
        }
        mock_container.replace_item.return_value = {"status": "active"}

        result = tracker.check_and_record("sess-001", tokens_used=500, cost_usd=0.005)
        assert result["status"] == "active"
