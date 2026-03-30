# Azure MCP Server Container
#
# Hosts the official Azure MCP Server (@azure/mcp) as an HTTP endpoint
# for AI Foundry agent MCP tool connections.
#
# Transport: Streamable HTTP on port 5000
# Auth: DefaultAzureCredential (managed identity in Container Apps)

FROM node:20

ARG AZURE_MCP_VERSION=2.0.0-beta.34

# Create non-root user
RUN groupadd -r mcp && useradd -r -g mcp -m mcp

WORKDIR /app

# Install a known-good Azure MCP Server version at build time.
RUN npm install -g "@azure/mcp@${AZURE_MCP_VERSION}" && npm cache clean --force

# Azure MCP Server uses DefaultAzureCredential from @azure/identity
# which reads AZURE_CLIENT_ID etc. from environment

USER mcp

EXPOSE 5000

# Start Azure MCP Server in HTTP transport mode
CMD ["azmcp", "server", "start", "--transport", "http"]
