"""Root conftest.py — test configuration for azure-agentic-platform.

Registers hyphenated service directories as importable Python packages.
The directory `services/api-gateway/` is registered as `services.api_gateway`
to match the production import path used in the Dockerfile and runtime.

Also installs a lightweight agent_framework stub so that agent source modules
can be imported during tests without requiring the real agent-framework package.
The stub exposes the symbols used by our source code (beta API: ChatAgent,
ai_function, HandoffBuilder); actual framework behaviour is not needed for tests.

Path note: agent source files use `from shared.xxx import ...` which matches
the container filesystem (/app/shared/). In the test environment the shared
package lives at agents/shared/, so we add agents/ to sys.path so that
`import shared` resolves to agents/shared/ during testing.
"""
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).parent

# Make `import shared` resolve to agents/shared/ in test context,
# matching the container runtime path /app/shared/.
_AGENTS_DIR = str(_ROOT / "agents")
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)


# ---------------------------------------------------------------------------
# agent_framework stub
# ---------------------------------------------------------------------------

def _install_agent_framework_stub() -> None:
    """Install a minimal agent_framework stub into sys.modules.

    Provides the symbols referenced in our agent source files (beta API):
        ChatAgent, ai_function, HandoffBuilder, AgentTarget, HandoffOrchestrator
    Only installed when the real package is not present OR when the real
    package does not export these symbols.
    """
    real_pkg = sys.modules.get("agent_framework")
    if real_pkg is not None and hasattr(real_pkg, "ai_function") and hasattr(real_pkg, "ChatAgent"):
        return  # Real beta package is present with correct API

    stub = types.ModuleType("agent_framework")

    def ai_function(fn=None, **kwargs):
        """No-op decorator — returns the function unchanged."""
        if fn is None:
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

    class ChatAgent(_Base):
        pass

    class AgentTarget(_Base):
        pass

    class HandoffOrchestrator(_Base):
        pass

    # rc5-style aliases (kept so any forward references don't break)
    Agent = ChatAgent
    tool = ai_function

    stub.ai_function = ai_function
    stub.ChatAgent = ChatAgent
    stub.AgentTarget = AgentTarget
    stub.HandoffOrchestrator = HandoffOrchestrator
    stub.Agent = Agent
    stub.tool = tool
    stub.MCPTool = _Base  # MCPTool used by eol agent

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


def _register_api_gateway_module(module_name: str) -> None:
    """Import and register a module from services/api-gateway/ into sys.modules.

    Uses importlib to load the actual .py file so that the module is fully
    executable and mock.patch() can resolve attributes on it.

    Args:
        module_name: Leaf module name without package prefix (e.g., 'noise_reducer').
    """
    import importlib.util

    full_name = f"services.api_gateway.{module_name}"
    if full_name in sys.modules:
        return  # Already loaded

    spec = importlib.util.spec_from_file_location(
        full_name,
        str(_ROOT / "services" / "api-gateway" / f"{module_name}.py"),
    )
    if spec is None or spec.loader is None:
        return  # File not found — skip silently

    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "services.api_gateway"
    sys.modules[full_name] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        # Registration failure is non-fatal; import will surface the error properly.
        del sys.modules[full_name]
        return

    # Expose as attribute on the package so mock._importer can resolve it
    pkg = sys.modules.get("services.api_gateway")
    if pkg is not None:
        setattr(pkg, module_name, mod)


# Register services/api-gateway as services.api_gateway
_register_hyphenated_package(
    _ROOT / "services" / "api-gateway",
    "services.api_gateway",
)

# Register modules required for test-time mock.patch() resolution.
# Add new modules here when they are patched in tests but not yet imported
# transitively by main.py at collection time.
_register_api_gateway_module("noise_reducer")
