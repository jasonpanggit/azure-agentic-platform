# services/api-gateway/Dockerfile
# Standalone API gateway for incident ingestion
FROM python:3.12-slim

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

# Copy scripts so startup migrations can load seed data (e.g. compliance mappings)
COPY scripts/ ./scripts/

# Copy detection-plane shared modules needed by dedup_integration.py.
# dedup_integration adds /app/services/detection-plane to sys.path and then
# does bare `from dedup import ...` — so the files must land at that exact path.
COPY services/detection-plane/dedup.py ./services/detection-plane/dedup.py
COPY services/detection-plane/models.py ./services/detection-plane/models.py
COPY services/detection-plane/__init__.py ./services/detection-plane/__init__.py

# Non-root user for security — must be created after npm install
# so /usr/local/lib/node_modules is readable by all
RUN useradd --create-home --shell /bin/bash gatewayuser && \
    chmod -R a+r /usr/local/lib/node_modules/@azure/mcp 2>/dev/null || true
USER gatewayuser

EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "services.api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
