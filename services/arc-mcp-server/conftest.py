"""Root conftest.py for Arc MCP Server tests.

Makes the ``arc_mcp_server`` package importable regardless of how pytest is
invoked.  The source tree uses the directory name ``arc-mcp-server`` (with
hyphens) which Python cannot import directly, so this file registers the
directory under the canonical package name at the start of sys.path.
"""
import sys
import os

# Register services/arc-mcp-server/ as the arc_mcp_server package root so
# that `from arc_mcp_server.tools.x import y` resolves correctly.
_pkg_root = os.path.dirname(__file__)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

# Expose the directory as arc_mcp_server so absolute imports work from
# within the package itself (e.g. tools/arc_data.py imports arc_mcp_server.auth)
import types as _types  # noqa: E402

if "arc_mcp_server" not in sys.modules:
    import importlib.util as _ilu  # noqa: E402
    _spec = _ilu.spec_from_file_location(
        "arc_mcp_server",
        os.path.join(_pkg_root, "__init__.py"),
        submodule_search_locations=[_pkg_root],
    )
    _mod = _ilu.module_from_spec(_spec)
    _mod.__path__ = [_pkg_root]
    _mod.__package__ = "arc_mcp_server"
    sys.modules["arc_mcp_server"] = _mod
    _spec.loader.exec_module(_mod)
