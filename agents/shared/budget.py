"""Per-session token budget tracking in Cosmos DB (AGENT-007).

Sessions are aborted at a configurable threshold (default $5).
max_iterations is capped at 10 per agent session.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from azure.cosmos import ContainerProxy, CosmosClient
from azure.identity import DefaultAzureCredential


class BudgetExceededException(Exception):
    """Raised when a session exceeds its token budget threshold."""

    def __init__(self, session_id: str, total_cost_usd: float, threshold_usd: float):
        self.session_id = session_id
        self.total_cost_usd = total_cost_usd
        self.threshold_usd = threshold_usd
        super().__init__(
            f"Session {session_id} exceeded budget: "
            f"${total_cost_usd:.4f} > ${threshold_usd:.2f}"
        )


class MaxIterationsExceededException(Exception):
    """Raised when a session exceeds maximum allowed iterations."""

    def __init__(self, session_id: str, iterations: int, max_iterations: int):
        self.session_id = session_id
        self.iterations = iterations
        self.max_iterations = max_iterations
        super().__init__(
            f"Session {session_id} exceeded max iterations: "
            f"{iterations} >= {max_iterations}"
        )


# Default gpt-4o pricing (configurable via env vars)
DEFAULT_INPUT_PRICE_PER_1M = 2.50
DEFAULT_OUTPUT_PRICE_PER_1M = 10.00
DEFAULT_BUDGET_THRESHOLD_USD = 5.00
DEFAULT_MAX_ITERATIONS = 10

SESSIONS_CONTAINER_NAME = "sessions"


def _get_sessions_container() -> ContainerProxy:
    """Get the Cosmos DB sessions container using DefaultAzureCredential."""
    endpoint = os.environ["COSMOS_ENDPOINT"]
    database_name = os.environ["COSMOS_DATABASE_NAME"]

    credential = DefaultAzureCredential()
    client = CosmosClient(url=endpoint, credential=credential)
    database = client.get_database_client(database_name)
    return database.get_container_client(SESSIONS_CONTAINER_NAME)


def calculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_1m: float | None = None,
    output_price_per_1m: float | None = None,
) -> float:
    """Calculate USD cost from token counts.

    Args:
        prompt_tokens: Number of input/prompt tokens.
        completion_tokens: Number of output/completion tokens.
        input_price_per_1m: Price per 1M input tokens (default: env or $2.50).
        output_price_per_1m: Price per 1M output tokens (default: env or $10.00).

    Returns:
        Estimated cost in USD.
    """
    if input_price_per_1m is None:
        input_price_per_1m = float(
            os.environ.get("INPUT_PRICE_PER_1M", DEFAULT_INPUT_PRICE_PER_1M)
        )
    if output_price_per_1m is None:
        output_price_per_1m = float(
            os.environ.get("OUTPUT_PRICE_PER_1M", DEFAULT_OUTPUT_PRICE_PER_1M)
        )

    input_cost = (prompt_tokens / 1_000_000) * input_price_per_1m
    output_cost = (completion_tokens / 1_000_000) * output_price_per_1m
    return input_cost + output_cost


class BudgetTracker:
    """Tracks per-session token budget in Cosmos DB.

    Each session has a cost ceiling (default $5) and iteration cap (default 10).
    Exceeding either limit raises an exception and marks the session as aborted
    in Cosmos DB.

    Cosmos record schema:
    {
        "id": session_id,
        "incident_id": str (partition key),
        "thread_id": str,
        "agent_name": str,
        "total_tokens": int,
        "total_cost_usd": float,
        "status": "active" | "completed" | "aborted",
        "last_updated": str (ISO 8601),
        "threshold_usd": float,
        "max_iterations": int,
        "iteration_count": int,
        "abort_reason": str | None,
    }
    """

    def __init__(
        self,
        container: ContainerProxy,
        session_id: str,
        incident_id: str,
        thread_id: str,
        agent_name: str,
        threshold_usd: float | None = None,
        max_iterations: int | None = None,
    ):
        self.container = container
        self.session_id = session_id
        self.incident_id = incident_id
        self.thread_id = thread_id
        self.agent_name = agent_name
        self.threshold_usd = threshold_usd or float(
            os.environ.get("BUDGET_THRESHOLD_USD", DEFAULT_BUDGET_THRESHOLD_USD)
        )
        self.max_iterations = max_iterations or int(
            os.environ.get("MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS)
        )

    def create_session(self) -> dict[str, Any]:
        """Create the initial session record in Cosmos DB.

        Returns:
            The created Cosmos DB document.
        """
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": self.session_id,
            "incident_id": self.incident_id,
            "thread_id": self.thread_id,
            "agent_name": self.agent_name,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "status": "active",
            "last_updated": now,
            "threshold_usd": self.threshold_usd,
            "max_iterations": self.max_iterations,
            "iteration_count": 0,
            "abort_reason": None,
        }
        return self.container.create_item(body=record)

    def check_and_record(
        self,
        session_id: str,
        tokens_used: int,
        cost_usd: float,
    ) -> dict[str, Any]:
        """Record token usage and check budget limits.

        Uses ETag optimistic concurrency for safe concurrent updates.

        Args:
            session_id: Session ID (must match self.session_id).
            tokens_used: Number of tokens consumed in this iteration.
            cost_usd: USD cost of this iteration.

        Returns:
            Updated Cosmos DB session record.

        Raises:
            BudgetExceededException: If total cost exceeds threshold.
            MaxIterationsExceededException: If iteration count exceeds max.
        """
        record = self.container.read_item(
            item=session_id,
            partition_key=self.incident_id,
        )
        etag = record["_etag"]

        new_total_tokens = record["total_tokens"] + tokens_used
        new_total_cost = record["total_cost_usd"] + cost_usd
        new_iteration_count = record["iteration_count"] + 1
        now = datetime.now(timezone.utc).isoformat()

        updated_record = {
            **record,
            "total_tokens": new_total_tokens,
            "total_cost_usd": new_total_cost,
            "iteration_count": new_iteration_count,
            "last_updated": now,
        }

        # Check budget threshold
        if new_total_cost > self.threshold_usd:
            updated_record["status"] = "aborted"
            updated_record["abort_reason"] = (
                f"Budget limit ${self.threshold_usd:.2f} exceeded: "
                f"${new_total_cost:.4f}"
            )
            self.container.replace_item(
                item=session_id,
                body=updated_record,
                etag=etag,
                match_condition="IfMatch",
            )
            raise BudgetExceededException(
                session_id=session_id,
                total_cost_usd=new_total_cost,
                threshold_usd=self.threshold_usd,
            )

        # Check iteration limit
        if new_iteration_count >= self.max_iterations:
            updated_record["status"] = "aborted"
            updated_record["abort_reason"] = (
                f"Max iterations ({self.max_iterations}) reached"
            )
            self.container.replace_item(
                item=session_id,
                body=updated_record,
                etag=etag,
                match_condition="IfMatch",
            )
            raise MaxIterationsExceededException(
                session_id=session_id,
                iterations=new_iteration_count,
                max_iterations=self.max_iterations,
            )

        # Within limits — update record
        result = self.container.replace_item(
            item=session_id,
            body=updated_record,
            etag=etag,
            match_condition="IfMatch",
        )
        return result

    def complete_session(self) -> dict[str, Any]:
        """Mark the session as completed.

        Returns:
            Updated Cosmos DB session record.
        """
        record = self.container.read_item(
            item=self.session_id,
            partition_key=self.incident_id,
        )
        now = datetime.now(timezone.utc).isoformat()
        updated_record = {
            **record,
            "status": "completed",
            "last_updated": now,
        }
        return self.container.replace_item(
            item=self.session_id,
            body=updated_record,
            etag=record["_etag"],
            match_condition="IfMatch",
        )
