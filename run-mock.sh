#!/usr/bin/env bash
# run-mock.sh — Start api-gateway locally with mock/dev env vars.
# All Azure dependencies (OTel, Cosmos, Foundry, Postgres) are stubbed out
# via absent or placeholder env vars. Auth is bypassed (dev mode).
#
# Usage: ./run-mock.sh [--port PORT]
set -euo pipefail

PORT=${PORT:-8000}

# Parse --port flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  api-gateway — local mock mode                      ║"
echo "║  http://localhost:${PORT}                              ║"
echo "║  Auth:    disabled (no AZURE_CLIENT_ID)             ║"
echo "║  OTel:    disabled (no APPINSIGHTS_CONNECTION_STR)  ║"
echo "║  Cosmos:  disabled (no COSMOS_ENDPOINT)             ║"
echo "║  Foundry: disabled (no AZURE_PROJECT_ENDPOINT)      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Dev / mock environment ──────────────────────────────────────────────────
export CORS_ALLOWED_ORIGINS="*"

# Auth: leave AZURE_CLIENT_ID unset → dev mode (all requests allowed)
unset AZURE_CLIENT_ID  2>/dev/null || true
unset AZURE_TENANT_ID  2>/dev/null || true

# OTel: leave unset → logs a warning but does NOT crash
unset APPLICATIONINSIGHTS_CONNECTION_STRING 2>/dev/null || true

# Cosmos: leave unset → approvals endpoints will 503 gracefully
unset COSMOS_ENDPOINT 2>/dev/null || true

# Foundry: leave unset → chat/incident endpoints will 503 gracefully
unset AZURE_PROJECT_ENDPOINT   2>/dev/null || true
unset ORCHESTRATOR_AGENT_ID    2>/dev/null || true

# Fabric OneLake: leave unset → remediation logger is a no-op
unset FABRIC_WORKSPACE_NAME    2>/dev/null || true
unset FABRIC_LAKEHOUSE_NAME    2>/dev/null || true

# ── Dependency check ────────────────────────────────────────────────────────
if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "⚠  Missing dependencies. Installing..."
  pip install -r services/api-gateway/requirements.txt -q
fi

# ── Hyphen shim ─────────────────────────────────────────────────────────────
# Python cannot import a package whose directory name contains a hyphen.
# This bootstrap registers services/api-gateway as services.api_gateway in
# sys.modules before uvicorn imports the app.
cat > _aap_bootstrap.py << 'PYEOF'
import sys
import importlib.util
import types

# Register services.api_gateway → services/api-gateway on disk
_root = sys.modules.get("services") or types.ModuleType("services")
_root.__path__ = ["services"]
sys.modules.setdefault("services", _root)

_spec = importlib.util.spec_from_file_location(
    "services.api_gateway",
    "services/api-gateway/__init__.py",
    submodule_search_locations=["services/api-gateway"],
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = "services.api_gateway"
sys.modules["services.api_gateway"] = _mod
setattr(_root, "api_gateway", _mod)
_spec.loader.exec_module(_mod)

# Re-export the FastAPI app for uvicorn
from services.api_gateway.main import app  # noqa: E402, F401
PYEOF

# ── Launch ──────────────────────────────────────────────────────────────────
echo "▶  Starting on port ${PORT}..."
echo "   GET http://localhost:${PORT}/health"
echo ""
exec uvicorn _aap_bootstrap:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --reload \
  --reload-dir services/api-gateway \
  --log-level info
