"""Root conftest.py — test configuration for azure-agentic-platform.

Registers hyphenated service directories as importable Python packages.
The directory `services/api-gateway/` is registered as `services.api_gateway`
to match the production import path used in the Dockerfile and runtime.

Also installs a lightweight agent_framework stub so that agent source modules
can be imported during tests without requiring the real agent-framework RC
package to be installed (it requires Python >=3.10 and is pre-release).
The stub exposes the symbols used by our source code; actual framework
behaviour is not needed for unit/integration tests.
"""
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# agent_framework stub
# ---------------------------------------------------------------------------

def _install_orchestrations_stub() -> None:
    """Install a minimal agent_framework_orchestrations stub."""
    if "agent_framework_orchestrations" in sys.modules:
        return

    stub = types.ModuleType("agent_framework_orchestrations")

    class HandoffBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def participants(self, participants):
            return self

        def build(self):
            return None

    stub.HandoffBuilder = HandoffBuilder
    sys.modules["agent_framework_orchestrations"] = stub


def _install_agent_framework_stub() -> None:
    """Install a minimal agent_framework stub into sys.modules.

    Provides the symbols referenced in our agent source files (rc5 API):
        Agent, tool, MCPStreamableHTTPTool
    Also installs agent_framework_orchestrations stub with HandoffBuilder.
    Real framework behaviour is not required for unit/integration tests.
    Only installed when the real package is not present OR when the real
    package does not export these symbols (RC API mismatch).
    """
    # Check if the real package already exports the rc5 symbols we need
    real_pkg = sys.modules.get("agent_framework")
    if real_pkg is not None and hasattr(real_pkg, "Agent") and hasattr(real_pkg, "tool"):
        _install_orchestrations_stub()
        return  # Real rc5 package is present

    stub = types.ModuleType("agent_framework")

    def tool(fn=None, **kwargs):
        """No-op decorator — returns the function unchanged."""
        if fn is None:
            def decorator(f):
                return f
            return decorator
        return fn

    # Legacy alias so any remaining old-API references don't crash on import
    ai_function = tool

    class _Base:
        def __init__(self, *args, **kwargs):
            pass

        def serve(self):
            pass

    class Agent(_Base):
        pass

    class MCPStreamableHTTPTool(_Base):
        pass

    # Legacy aliases — kept so old test stubs that reference these don't break
    class ChatAgent(_Base):
        pass

    class AgentTarget(_Base):
        pass

    class HandoffOrchestrator(_Base):
        def add_target(self, target):
            pass

    stub.tool = tool
    stub.ai_function = ai_function
    stub.Agent = Agent
    stub.MCPStreamableHTTPTool = MCPStreamableHTTPTool
    stub.ChatAgent = ChatAgent
    stub.AgentTarget = AgentTarget
    stub.HandoffOrchestrator = HandoffOrchestrator

    sys.modules["agent_framework"] = stub
    _install_orchestrations_stub()


_install_agent_framework_stub()


def _register_hyphenated_package(hyphenated_path: Path, import_name: str) -> None:
    """Register a hyphenated directory as an importable Python package.

    Adds the package to sys.modules AND sets it as an attribute on the parent
    module so that unittest.mock.patch() can resolve it via getattr().

    Args:
        hyphenated_path: Absolute path to the directory (e.g., services/api-gateway).
        import_name: Dotted import name (e.g., services.api_gateway).
    """
    if import_name in sys.modules:
        return  # Already registered

    parts = import_name.split(".")

    # Ensure all parent packages exist in sys.modules with correct __path__
    for i in range(1, len(parts)):
        parent_name = ".".join(parts[:i])
        if parent_name not in sys.modules:
            parent_mod = types.ModuleType(parent_name)
            parent_mod.__path__ = [str(_ROOT / Path(*parts[:i]))]
            parent_mod.__package__ = parent_name
            sys.modules[parent_name] = parent_mod

    # Create the leaf module pointing at the hyphenated directory
    mod = types.ModuleType(import_name)
    mod.__path__ = [str(hyphenated_path)]
    mod.__package__ = import_name
    mod.__file__ = str(hyphenated_path / "__init__.py")
    sys.modules[import_name] = mod

    # Set the module as an attribute on its parent so mock.patch can resolve it
    # via `getattr(parent_module, leaf_name)` (required by unittest.mock._importer)
    leaf_name = parts[-1]
    parent_name = ".".join(parts[:-1])
    if parent_name in sys.modules:
        setattr(sys.modules[parent_name], leaf_name, mod)


# Register services/api-gateway as services.api_gateway
_register_hyphenated_package(
    _ROOT / "services" / "api-gateway",
    "services.api_gateway",
)
