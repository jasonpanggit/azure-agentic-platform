# Azure MCP Server Container
#
# Architecture: azmcp (localhost:5000) + lightweight Node.js reverse proxy (0.0.0.0:8080)
#
# azmcp on linux/amd64 always binds to localhost:5000. Container Apps ingress requires
# 0.0.0.0 binding. The proxy starts immediately on 8080 so startup probes pass,
# then azmcp starts and handles requests.
#
# Auth: DefaultAzureCredential (managed identity in Container Apps)

FROM node:20

ARG AZURE_MCP_VERSION=2.0.0

WORKDIR /app

# Install azmcp globally at build time
RUN npm install -g "@azure/mcp@${AZURE_MCP_VERSION}" && npm cache clean --force \
    && rm -rf /root/.npm

# Reverse proxy: binds to 0.0.0.0:8080, forwards to azmcp on localhost:5000.
COPY proxy.js /app/proxy.js

# Create non-root user
RUN groupadd -r mcp && useradd -r -g mcp -m mcp && chown -R mcp:mcp /app
USER mcp

EXPOSE 8080

# Start proxy first (8080, returns 503 while azmcp warms up), then azmcp.
# Redirect azmcp stderr to stdout so errors are visible in Container Apps logs.
# SEC-001: --dangerously-disable-http-incoming-auth removed. Container App uses
# internal-only ingress (external_enabled=false); only traffic from within the
# Container Apps environment reaches azmcp. Defense-in-depth: network boundary
# + process boundary.
CMD ["sh", "-c", "node /app/proxy.js & azmcp server start --transport http 2>&1; echo 'azmcp exited'; wait"]
