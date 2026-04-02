"""Tests for Arc MCP Server OTel initialization in __main__.py."""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Resolve the path to __main__.py relative to this test file
_MAIN_PY = Path(__file__).resolve().parent.parent / "__main__.py"


def _load_main_module() -> object:
    """Load __main__.py as a fresh module from file path.

    We cannot use ``import arc_mcp_server.__main__`` because the test
    environment patches ``sys.modules["arc_mcp_server"]`` with a MagicMock,
    which prevents submodule resolution. Instead we load directly from file.
    """
    spec = importlib.util.spec_from_file_location(
        "arc_mcp_server.__main__", str(_MAIN_PY)
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_otel_configured_when_env_var_present() -> None:
    """configure_azure_monitor() is called when APPLICATIONINSIGHTS_CONNECTION_STRING is set."""
    mock_configure = MagicMock()
    fake_conn = "InstrumentationKey=00000000-0000-0000-0000-000000000000"

    with (
        patch.dict(
            os.environ,
            {"APPLICATIONINSIGHTS_CONNECTION_STRING": fake_conn},
        ),
        patch(
            "azure.monitor.opentelemetry.configure_azure_monitor",
            mock_configure,
        ),
        patch.dict(
            "sys.modules",
            {
                "arc_mcp_server.auth_middleware": MagicMock(),
                "arc_mcp_server.server": MagicMock(),
            },
        ),
    ):
        _load_main_module()

    mock_configure.assert_called_once_with(connection_string=fake_conn)


def test_otel_disabled_when_env_var_missing() -> None:
    """configure_azure_monitor() is NOT called when APPLICATIONINSIGHTS_CONNECTION_STRING is absent."""
    mock_configure = MagicMock()

    # Build a clean env without the App Insights key
    clean_env = {
        k: v for k, v in os.environ.items() if k != "APPLICATIONINSIGHTS_CONNECTION_STRING"
    }

    with (
        patch.dict(os.environ, clean_env, clear=True),
        patch(
            "azure.monitor.opentelemetry.configure_azure_monitor",
            mock_configure,
        ),
        patch.dict(
            "sys.modules",
            {
                "arc_mcp_server.auth_middleware": MagicMock(),
                "arc_mcp_server.server": MagicMock(),
            },
        ),
    ):
        _load_main_module()

    mock_configure.assert_not_called()
