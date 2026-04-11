"""Tests for agents/shared/telemetry.py — AIProjectInstrumentor setup and span helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestSetupFoundryTracing:
    """Verify setup_foundry_tracing wires configure_azure_monitor + AIProjectInstrumentor."""

    @patch("agents.shared.telemetry.AIProjectInstrumentor")
    @patch("agents.shared.telemetry.configure_azure_monitor")
    def test_calls_configure_azure_monitor_with_connection_string(
        self, mock_configure, mock_instrumentor
    ):
        mock_project = MagicMock()
        mock_project.telemetry.get_application_insights_connection_string.return_value = (
            "InstrumentationKey=test-key"
        )
        mock_instrumentor_instance = MagicMock()
        mock_instrumentor.return_value = mock_instrumentor_instance

        from agents.shared.telemetry import setup_foundry_tracing

        setup_foundry_tracing(mock_project, "aiops-compute-agent")

        mock_configure.assert_called_once_with(
            connection_string="InstrumentationKey=test-key"
        )

    def test_calls_instrumentor_instrument(self):
        """Patch at module level so the None-fallback guard is bypassed correctly."""
        mock_instrumentor_cls = MagicMock()
        mock_instrumentor_instance = MagicMock()
        mock_instrumentor_cls.return_value = mock_instrumentor_instance

        mock_project = MagicMock()
        mock_project.telemetry.get_application_insights_connection_string.return_value = (
            "InstrumentationKey=test-key"
        )

        import agents.shared.telemetry as telemetry_module
        original = telemetry_module.AIProjectInstrumentor

        try:
            telemetry_module.AIProjectInstrumentor = mock_instrumentor_cls
            from agents.shared.telemetry import setup_foundry_tracing
            with patch("agents.shared.telemetry.configure_azure_monitor"):
                setup_foundry_tracing(mock_project, "aiops-compute-agent")
        finally:
            telemetry_module.AIProjectInstrumentor = original

        mock_instrumentor_instance.instrument.assert_called_once()

    @patch("agents.shared.telemetry.AIProjectInstrumentor")
    @patch("agents.shared.telemetry.configure_azure_monitor")
    def test_returns_none(self, mock_configure, mock_instrumentor):
        mock_project = MagicMock()
        mock_project.telemetry.get_application_insights_connection_string.return_value = (
            "conn"
        )
        mock_instrumentor.return_value = MagicMock()

        from agents.shared.telemetry import setup_foundry_tracing

        result = setup_foundry_tracing(mock_project, "test-agent")
        assert result is None


class TestGetTracer:
    """Verify get_tracer returns an OTel tracer."""

    def test_returns_tracer(self):
        from agents.shared.telemetry import get_tracer

        tracer = get_tracer("test-agent")
        assert tracer is not None

    def test_returns_different_tracers_for_different_names(self):
        from agents.shared.telemetry import get_tracer

        t1 = get_tracer("agent-a")
        t2 = get_tracer("agent-b")
        # OTel returns named tracers; the names should differ
        assert t1 != t2
