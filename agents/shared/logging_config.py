"""Structured logging setup for all AAP agent containers."""
from __future__ import annotations

import logging
import os


def setup_logging(agent_name: str) -> logging.Logger:
    """Configure structured logging for an agent container.

    Reads LOG_LEVEL from environment (default: INFO).
    Format: timestamp level logger_name message -- machine-readable for Azure Monitor.

    Args:
        agent_name: Short agent name for the root logger context (e.g., "compute").

    Returns:
        A Logger instance for the calling module.
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return logging.getLogger(f"aiops.{agent_name}")
