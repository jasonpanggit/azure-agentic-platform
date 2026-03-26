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

def _install_agent_framework_stub() -> None:
    """Install a minimal agent_framework stub into sys.modules.

    Provides the symbols referenced in our agent source files:
        AgentTarget, HandoffOrchestrator, ChatAgent, ai_function
    Real framework behaviour is not required for unit/integration tests.
    Only installed when the real package is not present OR when the real
    package does not export these symbols (RC API mismatch).
    """
    # Check if the real package already exports the symbols we need
    real_pkg = sys.modules.get("agent_framework")
    if real_pkg is not None and hasattr(real_pkg, "ai_function"):
        return  # Real package is present and has the right API

    stub = types.ModuleType("agent_framework")

    def ai_function(fn=None, **kwargs):
        """No-op decorator — returns the function unchanged."""
        if fn is None:
            # Called as @ai_function(name=...) — return decorator
            def decorator(f):
                return f
            return decorator
        return fn

    class _Base:
        def __init__(self, *args, **kwargs):
            pass

        def add_target(self, target):
            pass

        def serve(self):
            pass

    class AgentTarget(_Base):
        pass

    class HandoffOrchestrator(_Base):
        pass

    class ChatAgent(_Base):
        pass

    stub.ai_function = ai_function
    stub.AgentTarget = AgentTarget
    stub.HandoffOrchestrator = HandoffOrchestrator
    stub.ChatAgent = ChatAgent

    sys.modules["agent_framework"] = stub


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
