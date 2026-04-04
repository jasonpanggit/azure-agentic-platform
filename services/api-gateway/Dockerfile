# services/api-gateway/Dockerfile
# Standalone API gateway for incident ingestion
FROM mcr.microsoft.com/mirror/docker/library/python:3.12-slim

WORKDIR /app

# System dependencies + Node.js for @azure/mcp stdio subprocess
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        nodejs \
        npm \
    && npm install -g @azure/mcp@2.0.0-beta.34 \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY services/api-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy package roots so Python can resolve `services.api_gateway.*` and `agents.shared.*`
COPY services/__init__.py ./services/__init__.py
COPY services/api-gateway/ ./services/api_gateway/
COPY agents/ ./agents/

# Non-root user for security — must be created after npm install
# so /usr/local/lib/node_modules is readable by all
RUN useradd --create-home --shell /bin/bash gatewayuser && \
    chmod -R a+r /usr/local/lib/node_modules/@azure/mcp 2>/dev/null || true
USER gatewayuser

EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "services.api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
