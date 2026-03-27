# services/teams-bot/Dockerfile
# Multi-stage build for Azure Agentic Platform Teams bot

# Stage 1: Build
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci --legacy-peer-deps

COPY . .
RUN npm run build

# Stage 2: Runtime
FROM node:20-alpine
WORKDIR /app

COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY package.json ./

# Non-root user for security
RUN addgroup -S botgroup && adduser -S botuser -G botgroup
USER botuser

EXPOSE 3978

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:3978/health || exit 1

CMD ["node", "dist/index.js"]
