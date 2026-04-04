# Arc MCP Server — standalone FastMCP container (AGENT-005)
# Does NOT extend agents/Dockerfile.base — MCP servers have a different
# dependency set (mcp[cli], Azure Arc SDKs) and do not need agent-framework
# or azure-ai-agentserver packages.

FROM python:3.11-slim

# Build args
ARG IMAGE_TAG=latest
LABEL org.opencontainers.image.title="arc-mcp-server"
LABEL org.opencontainers.image.description="Azure Arc MCP Server — FastMCP with HybridCompute, ConnectedK8s, ArcData tools"
LABEL org.opencontainers.image.version="${IMAGE_TAG}"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# The package is named arc_mcp_server matching the directory with __main__.py
COPY . /app/arc_mcp_server/

# Set PYTHONPATH so `python -m arc_mcp_server` resolves correctly
ENV PYTHONPATH=/app

# FastMCP server configuration
ENV ARC_DISCONNECT_ALERT_HOURS=1

# Entra JWT auth (14-12): enabled by default in the container.
# Override with ARC_MCP_AUTH_DISABLED=true for local dev / CI.
ENV ARC_MCP_AUTH_DISABLED=false

# Non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Expose FastMCP streamable-http port
EXPOSE 8080

# Health check — MCP endpoint responds to GET /mcp/health or POST /mcp
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/mcp || exit 1

# Entry point: python -m arc_mcp_server invokes __main__.py
CMD ["python", "-m", "arc_mcp_server"]
